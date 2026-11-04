"""Ключи подписи: плановая и немедленная ротация, JWKS, администрирование (шаг 3.3)."""

from __future__ import annotations

from datetime import timedelta

import jwt
from helpers import bearer, login

from app.db import aware
from app.models import AuditLog, Event, SigningKey


def admin(client):
    token, _ = login(client)
    return bearer(token)


def kid_of(token: str) -> str:
    return jwt.get_unverified_header(token)["kid"]


def jwks_kids(client) -> list[str]:
    return [k["kid"] for k in client.get("/.well-known/jwks.json").json()["keys"]]


def shift(db, kid: str, field: str, seconds: int) -> None:
    key = db.get(SigningKey, kid)
    setattr(key, field, aware(getattr(key, field)) - timedelta(seconds=seconds))
    db.commit()


def test_scheduled_rotation_publishes_next_before_it_signs(client, db):
    from app.security import keys

    old_token, _ = login(client)
    old_kid = kid_of(old_token)

    # Ключ ещё молодой: шаг планировщика ничего не делает.
    keys.tick(db)
    assert db.query(SigningKey).filter_by(status="next").count() == 0

    # До срока осталось меньше key_next_lead_seconds: публикуется next.
    shift(db, old_kid, "activated_at", 90 * 86400 - 600)
    keys.tick(db)
    nxt = db.query(SigningKey).filter_by(status="next").one()
    assert nxt.kid in jwks_kids(client)
    # Подписывает по-прежнему старый ключ, повторный шаг второй next не создаёт.
    assert kid_of(login(client)[0]) == old_kid
    keys.tick(db)
    assert db.query(SigningKey).filter_by(status="next").count() == 1

    # next пробыл в JWKS key_next_lead_seconds — становится активным.
    shift(db, nxt.kid, "created_at", 1200)
    keys.tick(db)
    db.expire_all()
    assert db.get(SigningKey, nxt.kid).status == "active"
    assert db.get(SigningKey, old_kid).status == "retired"
    new_token, _ = login(client)
    assert kid_of(new_token) == nxt.kid

    # Прежний ключ ещё в JWKS: выданные им токены доживают свой срок.
    assert old_kid in jwks_kids(client)
    assert client.get("/me", headers=bearer(old_token)).status_code == 200

    # Через jwks_retain_seconds прежний ключ уходит из JWKS, приватная часть стирается.
    shift(db, old_kid, "retired_at", 1800)
    keys.tick(db)
    db.expire_all()
    assert old_kid not in jwks_kids(client)
    assert db.get(SigningKey, old_kid).private_key_enc == ""
    assert client.get("/me", headers=bearer(new_token)).status_code == 200

    actions = [a.action for a in db.query(AuditLog).filter(AuditLog.object.like("signing_key/%"))]
    assert actions == ["keys.next_published", "keys.activated"]
    # Публикация next события не порождает, смена активного ключа — одно событие.
    ev = db.query(Event).filter_by(type="platform.keys.rotated").one()
    assert ev.source == "platform" and ev.data == {"kid": nxt.kid, "revoked": []}


def test_every_signing_kid_was_published_before_use(client, db):
    """Критерий шага 3.3: в плановом цикле ключ появляется в JWKS раньше, чем им подписывают."""
    from app.security import keys

    seen = set(jwks_kids(client))
    signed = []
    for _ in range(3):
        active = db.query(SigningKey).filter_by(status="active").one()
        shift(db, active.kid, "activated_at", 90 * 86400)
        keys.tick(db)  # публикует next
        seen |= set(jwks_kids(client))
        nxt = db.query(SigningKey).filter_by(status="next").one()
        shift(db, nxt.kid, "created_at", 1200)
        keys.tick(db)  # активирует
        db.expire_all()
        signed.append(kid_of(login(client)[0]))
    assert len(set(signed)) == 3
    assert set(signed) <= seen


def test_admin_api_lists_keys_without_private_material(client, db):
    h = admin(client)
    r = client.get("/admin/keys", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert [k["status"] for k in body["keys"]] == ["active"]
    assert body["keys"][0]["in_jwks"] is True
    assert body["schedule"]["rotation_days"] == 90
    assert body["schedule"]["next_lead_seconds"] == 1200
    assert body["schedule"]["next_rotation_at"]
    # В тестах фоновые задачи выключены — экран об этом предупреждает.
    assert any("BACKGROUND_TASKS" in w for w in body["warnings"])
    enc = db.query(SigningKey).one().private_key_enc
    assert enc not in r.text and "private" not in r.text


def test_manual_scheduled_rotation_is_idempotent(client, db):
    h = admin(client)
    old_kid = kid_of(h["authorization"][7:])
    r = client.post("/admin/keys/rotate", json={"mode": "scheduled"}, headers=h)
    assert r.status_code == 200
    statuses = {k["status"]: k for k in r.json()["keys"]}
    assert statuses["next"]["in_jwks"] is True and statuses["next"]["until"]
    assert r.json()["schedule"]["next_rotation_at"] == statuses["next"]["until"]
    # Повтор не создаёт второй ключ next, подписывает прежний.
    r2 = client.post("/admin/keys/rotate", json={"mode": "scheduled"}, headers=h)
    assert [k["kid"] for k in r2.json()["keys"]] == [k["kid"] for k in r.json()["keys"]]
    assert kid_of(login(client)[0]) == old_kid

    audit = db.query(AuditLog).filter_by(action="keys.next_published").one()
    assert audit.actor_name == "Администратор платформы"
    assert audit.object == f"signing_key/{statuses['next']['kid']}"


def test_immediate_rotation_activates_published_next(client, db):
    h = admin(client)
    nxt = next(
        k["kid"]
        for k in client.post("/admin/keys/rotate", json={"mode": "scheduled"}, headers=h).json()["keys"]
        if k["status"] == "next"
    )
    r = client.post("/admin/keys/rotate", json={"mode": "immediate"}, headers=h)
    assert db.query(Event).filter_by(type="platform.keys.rotated").one().data == {"kid": nxt, "revoked": []}
    by_status = {k["status"]: k["kid"] for k in r.json()["keys"]}
    assert by_status["active"] == nxt
    # Прежний ключ в JWKS: токен администратора, выданный до смены, действует.
    assert client.get("/admin/keys", headers=h).status_code == 200


def test_immediate_rotation_with_revoke_invalidates_old_tokens(client, db):
    h = admin(client)
    old_kid = kid_of(h["authorization"][7:])
    r = client.post("/admin/keys/rotate", json={"mode": "immediate", "revoke_previous": True}, headers=h)
    assert r.status_code == 200
    old = next(k for k in r.json()["keys"] if k["kid"] == old_kid)
    assert old["status"] == "revoked" and old["in_jwks"] is False
    assert old_kid not in jwks_kids(client)
    db.expire_all()
    assert db.get(SigningKey, old_kid).private_key_enc == ""
    # Токены, подписанные отозванным ключом, больше не принимаются; вход выдаёт новый.
    assert client.get("/admin/keys", headers=h).status_code == 401
    assert kid_of(login(client)[0]) != old_kid

    a = db.query(AuditLog).filter_by(action="keys.rotate_immediate").one()
    assert a.details["revoke_previous"] is True and a.details["previous"] == [old_kid]
    ev = db.query(Event).filter_by(type="platform.keys.rotated").one()
    new_kid = next(k["kid"] for k in r.json()["keys"] if k["status"] == "active")
    assert ev.data == {"kid": new_kid, "revoked": [old_kid]}


def test_revoke_requires_immediate_and_admin(client):
    h = admin(client)
    r = client.post("/admin/keys/rotate", json={"mode": "scheduled", "revoke_previous": True}, headers=h)
    assert r.status_code == 422
    client.post(
        "/admin/users",
        json={"username": "ivan", "password": "ivan-password-1", "display_name": "Иван"},
        headers=h,
    )
    token, _ = login(client, "ivan", "ivan-password-1")
    assert client.get("/admin/keys", headers=bearer(token)).status_code == 403
    assert client.post("/admin/keys/rotate", json={}, headers=bearer(token)).status_code == 403


def test_tick_creates_key_when_none_active(client, db):
    from app.security import keys

    for k in db.query(SigningKey).all():
        k.status = "revoked"
    db.commit()
    keys.tick(db)
    assert db.query(SigningKey).filter_by(status="active").count() == 1


def test_rotations_visible_in_audit_journal(client, db):
    from app.security import keys

    h = admin(client)
    client.post("/admin/keys/rotate", json={"mode": "scheduled"}, headers=h)
    nxt = db.query(SigningKey).filter_by(status="next").one()
    shift(db, nxt.kid, "created_at", 1200)
    keys.tick(db)
    r = client.get("/audit?action=keys.*", headers=h)
    assert r.status_code == 200, r.text
    rows = {x["action"]: x for x in r.json()}
    assert set(rows) == {"keys.next_published", "keys.activated"}
    assert rows["keys.next_published"]["actor_name"] == "Администратор платформы"
    assert rows["keys.activated"]["actor_name"] == "Платформа (плановая ротация)"
    assert all(x["product"] == "platform" and x["object"] == f"signing_key/{nxt.kid}" for x in rows.values())

"""Сервисные учётные записи и POST /auth/token (шаг 2.2)."""

from __future__ import annotations

import base64

import jwt
from sqlalchemy import select

from app.models import AuditLog, ServiceAccount
from tests.helpers import bearer, claims, login


def admin(client):
    token, _ = login(client)
    return bearer(token)


def create(client, h, **kw):
    body = {
        "client_id": "vm-to-scanner",
        "name": "Устранение → Сканер",
        "target_product": "scanner",
        "roles": ["operator", "host_credentials"],
        **kw,
    }
    return client.post("/admin/service-accounts", json=body, headers=h)


def token_req(client, cid="vm-to-scanner", secret="", grant="client_credentials"):
    return client.post("/auth/token", data={"grant_type": grant, "client_id": cid, "client_secret": secret})


def test_create_returns_secret_once_and_token_has_contract_claims(client, db):
    h = admin(client)
    r = create(client, h)
    assert r.status_code == 201, r.text
    secret = r.json()["client_secret"]
    assert secret.startswith("psk_")
    listed = client.get("/admin/service-accounts", headers=h).json()
    assert "client_secret" not in listed[0] and "secret_hash" not in listed[0]

    r = token_req(client, secret=secret)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert "set-cookie" not in r.headers  # без refresh-cookie
    body = r.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 900
    c = claims(body["access_token"])
    sa = db.scalar(select(ServiceAccount))
    assert c["sub"] == f"svc:{sa.id}"
    assert c["typ"] == "service"
    assert c["aud"] == ["scanner"]
    assert c["client_id"] == "vm-to-scanner"
    assert c["preferred_username"] == "svc:vm-to-scanner"
    assert c["products"] == {"scanner": ["host_credentials", "operator"]}
    assert c["projects"] == ["*"]
    assert jwt.get_unverified_header(body["access_token"])["kid"]

    # секрета нет ни в аудите, ни в ответах списка
    for row in db.scalars(select(AuditLog)):
        assert secret not in str(row.details)
    db.expire_all()
    assert db.get(ServiceAccount, sa.id).last_used_at is not None


def test_basic_auth_is_accepted(client):
    h = admin(client)
    secret = create(client, h).json()["client_secret"]
    basic = base64.b64encode(f"vm-to-scanner:{secret}".encode()).decode()
    r = client.post(
        "/auth/token", data={"grant_type": "client_credentials"}, headers={"authorization": f"Basic {basic}"}
    )
    assert r.status_code == 200, r.text


def test_wrong_secret_unknown_client_and_grant(client, db):
    h = admin(client)
    create(client, h)
    r = token_req(client, secret="psk_wrong")
    assert r.status_code == 401 and r.json()["error"] == "invalid_client"
    assert token_req(client, cid="nobody", secret="x").status_code == 401
    r = token_req(client, secret="x", grant="password")
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
    assert token_req(client, secret="").status_code == 400
    failures = db.scalars(
        select(AuditLog).where(AuditLog.action == "auth.service_token", AuditLog.result == "failure")
    ).all()
    assert len(failures) == 2


def test_service_token_not_accepted_by_platform_api(client):
    h = admin(client)
    secret = create(client, h).json()["client_secret"]
    token = token_req(client, secret=secret).json()["access_token"]
    assert client.get("/me", headers=bearer(token)).status_code == 401
    assert client.get("/admin/users", headers=bearer(token)).status_code == 401


def test_rotate_secret_invalidates_old(client):
    h = admin(client)
    r = create(client, h)
    old, sid = r.json()["client_secret"], r.json()["id"]
    new = client.post(f"/admin/service-accounts/{sid}/secret", headers=h).json()["client_secret"]
    assert new != old
    assert token_req(client, secret=old).status_code == 401
    assert token_req(client, secret=new).status_code == 200


def test_disable_and_delete(client):
    h = admin(client)
    r = create(client, h)
    secret, sid = r.json()["client_secret"], r.json()["id"]
    assert (
        client.patch(f"/admin/service-accounts/{sid}", json={"is_active": False}, headers=h).status_code
        == 200
    )
    assert token_req(client, secret=secret).status_code == 401
    assert client.delete(f"/admin/service-accounts/{sid}", headers=h).status_code == 204
    assert client.get("/admin/service-accounts", headers=h).json() == []


def test_validation(client):
    h = admin(client)
    assert create(client, h, roles=["superuser"]).status_code == 422
    assert create(client, h, target_product="grc").status_code == 422  # не установлен
    assert create(client, h, client_id="Bad Id").status_code == 422
    assert create(client, h, all_projects=False, projects=[]).status_code == 422
    assert create(client, h).status_code == 201
    assert create(client, h).status_code == 409


def test_project_scope_and_role_filter_by_manifest(client, db):
    h = admin(client)
    pid = client.post(
        "/admin/projects", json={"name": "Проект А", "client": "", "contract_ref": ""}, headers=h
    ).json()["id"]
    r = create(client, h, all_projects=False, projects=[pid], roles=["auditor"])
    assert r.status_code == 201, r.text
    secret = r.json()["client_secret"]
    c = claims(token_req(client, secret=secret).json()["access_token"])
    assert c["projects"] == [pid]
    assert c["products"] == {"scanner": ["auditor"]}

    # роль пропала из манифеста — в токен не попадает
    sa = db.scalar(select(ServiceAccount))
    sa.roles = ["auditor", "retired_role"]
    db.commit()
    c = claims(token_req(client, secret=secret).json()["access_token"])
    assert c["products"] == {"scanner": ["auditor"]}


def test_non_admin_cannot_manage(client):
    h = admin(client)
    client.post(
        "/admin/users",
        json={"username": "ivan", "password": "ivan-password-1", "display_name": "Иван"},
        headers=h,
    )
    token, _ = login(client, "ivan", "ivan-password-1")
    assert client.get("/admin/service-accounts", headers=bearer(token)).status_code == 403

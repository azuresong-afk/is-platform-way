"""Разделение обязанностей без обходов (шаг 5.8, docs/SECURITY.md, п. 6).

Администратор платформы не должен получать рабочие роли через запись, пароль которой знает:
пароль от администратора временный (токен без ролей до смены самим пользователем),
а действия, которые дают такой обход, помечены в журнале (`sod`) и отбираются фильтром.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog
from tests.helpers import bearer, change_password, claims, do_refresh, login, make_user, refresh_cookie
from tests.test_groups import _group
from tests.test_service_accounts import create as create_sa

ROLES = {"scanner": ["operator"]}


def _admin(client):
    return bearer(login(client)[0])


def _sod(db, action: str) -> list[bool]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.sod).where(AuditLog.action == action).order_by(AuditLog.id)))


# --- (а) временный пароль -----------------------------------------------------


def test_admin_set_password_is_temporary_token_has_no_roles_until_user_changes_it(client, db):
    h = _admin(client)
    u = make_user(client, h, "ivanov", password="first-password-1", activate=False)
    assert u["password_temporary"] is True
    assert client.put(f"/admin/users/{u['id']}/roles", json={"products": ROLES}, headers=h).status_code == 200

    r = client.post("/auth/login", json={"username": "ivanov", "password": "tmp-first-password-1"})
    assert r.status_code == 200 and r.json()["password_change_required"] is True
    temp_token, temp_cookie = r.json()["access_token"], refresh_cookie(r)
    c = claims(temp_token)
    assert c["products"] == {} and c["projects"] == [] and c["platform_admin"] is False
    assert c["password_change_required"] is True
    # refresh не возвращает роли, пока пароль временный
    assert claims(do_refresh(client, temp_cookie).json()["access_token"])["products"] == {}
    # API платформы закрыт, кроме профиля
    r = client.get("/products", headers=bearer(temp_token))
    assert r.status_code == 403 and r.json()["detail"] == "password_change_required"
    me = client.get("/me", headers=bearer(temp_token)).json()
    assert me["password_change_required"] is True and me["products"] == {}

    token, cookie = change_password(client, "ivanov", "tmp-first-password-1", "own-password-1")
    assert claims(token)["products"] == ROLES and "password_change_required" not in claims(token)
    assert client.get("/products", headers=bearer(token)).status_code == 200
    assert client.get(f"/admin/users/{u['id']}", headers=h).json()["password_temporary"] is False
    # прежние сессии закрыты, новая работает; старый пароль больше не подходит
    assert do_refresh(client, temp_cookie).status_code == 401
    assert do_refresh(client, cookie).status_code == 200
    r = client.post("/auth/login", json={"username": "ivanov", "password": "tmp-first-password-1"})
    assert r.status_code == 401


def test_admin_reset_of_working_user_makes_password_temporary_again(client, db):
    h = _admin(client)
    u = make_user(client, h, "ivanov")
    client.put(f"/admin/users/{u['id']}/roles", json={"products": ROLES}, headers=h)
    token, _ = login(client, "ivanov", "long-password-1")
    assert claims(token)["products"] == ROLES

    r = client.post(f"/admin/users/{u['id']}/password", json={"password": "admin-knows-it-1"}, headers=h)
    assert r.status_code == 204
    assert _sod(db, "user.password") == [True]
    # вход под записью с паролем от администратора ролей не даёт
    t2, _ = login(client, "ivanov", "admin-knows-it-1")
    assert claims(t2)["products"] == {}
    # уже выданный токен для API платформы перестаёт работать сразу (сверка с БД)
    assert client.get("/products", headers=bearer(token)).json()["detail"] == "password_change_required"


def test_new_platform_admin_with_temporary_password_has_no_admin_rights(client):
    h = _admin(client)
    make_user(client, h, "second", activate=False, is_platform_admin=True)
    t, _ = login(client, "second", "tmp-long-password-1")
    assert claims(t)["platform_admin"] is False
    assert client.get("/admin/users", headers=bearer(t)).status_code == 403
    t, _ = change_password(client, "second", "tmp-long-password-1", "second-own-password-1")
    assert claims(t)["platform_admin"] is True
    assert client.get("/admin/users", headers=bearer(t)).status_code == 200


def test_admin_cannot_reset_own_password_through_admin_api_but_can_change_it(client):
    token, _ = login(client)
    me = client.get("/me", headers=bearer(token)).json()
    r = client.post(
        f"/admin/users/{me['id']}/password", json={"password": "new-admin-pass-1"}, headers=bearer(token)
    )
    assert r.status_code == 403
    token, _ = change_password(client, "admin", "admin-password-1", "new-admin-pass-1")
    assert claims(token)["platform_admin"] is True


def test_change_password_checks(client, db):
    h = _admin(client)
    make_user(client, h, "ivanov", activate=False)
    t, _ = login(client, "ivanov", "tmp-long-password-1")

    def change(current, new):
        return client.post(
            "/auth/password", json={"current_password": current, "new_password": new}, headers=bearer(t)
        )

    assert change("tmp-long-password-1", "short").status_code == 422
    assert change("tmp-long-password-1", "tmp-long-password-1").status_code == 400
    assert (
        client.post("/auth/password", json={"current_password": "x", "new_password": "y" * 12}).status_code
        == 401
    )
    # неверный текущий пароль считается в блокировку, как при входе
    for _ in range(4):
        assert change("wrong-password", "new-password-123").status_code == 403
    r = change("wrong-password", "new-password-123")
    assert r.status_code == 403 and "заблокирована" in r.json()["detail"]
    # заблокированная запись не проходит и проверку токена
    assert change("tmp-long-password-1", "new-password-123").status_code == 401
    rows = db.scalars(select(AuditLog.result).where(AuditLog.action == "auth.password_change")).all()
    assert rows.count("failure") == 4 and rows.count("denied") >= 1


def test_password_change_from_admin_address_is_flagged(client, db):
    h = {**_admin(client), "x-real-ip": "10.0.0.5"}
    make_user(client, h, "same", activate=False)
    make_user(client, h, "other", activate=False)
    for name, ip in (("same", "10.0.0.5"), ("other", "10.0.0.77")):
        t, _ = login(client, name, "tmp-long-password-1")
        r = client.post(
            "/auth/password",
            json={"current_password": "tmp-long-password-1", "new_password": "own-password-123"},
            headers={**bearer(t), "x-real-ip": ip},
        )
        assert r.status_code == 200, r.text
    rows = db.scalars(
        select(AuditLog).where(AuditLog.action == "auth.password_change").order_by(AuditLog.id)
    ).all()
    assert [(r.object, r.sod, r.details["same_ip_as_admin"]) for r in rows] == [
        ("user/same", True, True),
        ("user/other", False, False),
    ]
    assert rows[0].details["was_temporary"] is True and rows[0].details["set_by"]


# --- (в) пометки в журнале ------------------------------------------------------


def test_roles_for_user_with_temporary_password_are_flagged(client, db):
    h = _admin(client)
    fresh = make_user(client, h, "fresh", activate=False)
    working = make_user(client, h, "working")
    client.put(f"/admin/users/{fresh['id']}/roles", json={"products": ROLES}, headers=h)
    client.put(f"/admin/users/{working['id']}/roles", json={"products": ROLES}, headers=h)
    client.put(f"/admin/users/{fresh['id']}/roles", json={"products": {"scanner": []}}, headers=h)
    assert _sod(db, "user.roles") == [True, False, False]


def test_team_with_roles_and_temporary_password_member_is_flagged(client, db):
    h = _admin(client)
    fresh = make_user(client, h, "fresh", activate=False)
    working = make_user(client, h, "working")
    g = _group(client, h)
    client.put(f"/admin/groups/{g['id']}/members", json={"ids": [working["id"]]}, headers=h)
    client.put(f"/admin/groups/{g['id']}/roles", json={"products": ROLES}, headers=h)
    r = client.put(f"/admin/groups/{g['id']}/members", json={"ids": [working["id"], fresh["id"]]}, headers=h)
    assert r.status_code == 200, r.text
    client.put(f"/admin/groups/{g['id']}/roles", json={"products": ROLES}, headers=h)
    assert _sod(db, "group.members") == [False, True]
    assert _sod(db, "group.roles") == [False, True]


def test_service_account_with_roles_is_flagged(client, db):
    h = _admin(client)
    sa = create_sa(client, h).json()
    client.patch(f"/admin/service-accounts/{sa['id']}", json={"name": "Другое имя"}, headers=h)
    client.post(f"/admin/service-accounts/{sa['id']}/secret", headers=h)
    client.patch(f"/admin/service-accounts/{sa['id']}", json={"roles": ["operator"]}, headers=h)
    client.patch(f"/admin/service-accounts/{sa['id']}", json={"is_active": False}, headers=h)
    client.post(f"/admin/service-accounts/{sa['id']}/secret", headers=h)
    assert _sod(db, "service_account.create") == [True]
    assert _sod(db, "service_account.update") == [False, True, False]
    assert _sod(db, "service_account.secret_rotate") == [True, False]


def test_audit_filter_and_export_show_sod(client, db):
    h = _admin(client)
    u = make_user(client, h, "ivanov")
    client.post(f"/admin/users/{u['id']}/password", json={"password": "admin-knows-it-1"}, headers=h)
    r = client.get("/audit", params={"sod": "true"}, headers=h)
    # в тестах у администратора и пользователя один адрес: смена временного пароля тоже помечена
    assert r.status_code == 200 and r.headers["X-Total-Count"] == "2"
    assert {x["action"] for x in r.json()} == {"user.password", "auth.password_change"}
    assert all(x["sod"] for x in r.json())
    assert all(not x["sod"] for x in client.get("/audit", params={"sod": "false"}, headers=h).json())
    csv = client.get("/audit/export", params={"sod": "true"}, headers=h).text
    assert csv.splitlines()[0].endswith(",sod")

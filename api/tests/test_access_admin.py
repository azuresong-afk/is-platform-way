from app.models import AuditLog
from tests.helpers import bearer, claims, do_refresh, login


def _admin(client):
    return bearer(login(client)[0])


def _mk_user(client, h, username="ivanov", **kw):
    body = {"username": username, "display_name": "Иванов И. И.", "password": "long-password-1", **kw}
    r = client.post("/admin/users", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_project(client, h, name="Аудит ООО «Ромашка»"):
    r = client.post(
        "/admin/projects",
        json={
            "name": name,
            "client": "ООО «Ромашка»",
            "contract_ref": "Д-17/2026",
            "period_from": "2026-11-01",
            "period_to": "2026-12-31",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_non_admin_cannot_administer(client):
    h = _admin(client)
    _mk_user(client, h)
    uh = bearer(login(client, "ivanov", "long-password-1")[0])
    assert client.get("/admin/users", headers=uh).status_code == 403
    assert client.post("/admin/projects", json={"name": "x"}, headers=uh).status_code == 403


def test_users_list_pagination_and_search(client):
    h = _admin(client)
    for i in range(3):
        _mk_user(client, h, f"user{i}")
    r = client.get("/admin/users?limit=2&offset=0", headers=h)
    assert r.headers["x-total-count"] == "4" and len(r.json()) == 2
    r = client.get("/admin/users?q=user1", headers=h)
    assert [u["username"] for u in r.json()] == ["user1"]
    assert (
        client.post(
            "/admin/users", json={"username": "USER1", "password": "long-password-1"}, headers=h
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/admin/users", json={"username": "x y", "password": "long-password-1"}, headers=h
        ).status_code
        == 422
    )
    assert (
        client.post("/admin/users", json={"username": "short", "password": "short"}, headers=h).status_code
        == 422
    )


def test_roles_validated_against_manifest(client):
    h = _admin(client)
    u = _mk_user(client, h)
    r = client.put(
        f"/admin/users/{u['id']}/roles", json={"products": {"scanner": ["operator", "cred_audit"]}}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["roles"] == {"scanner": ["cred_audit", "operator"]}
    r = client.put(f"/admin/users/{u['id']}/roles", json={"products": {"scanner": ["god"]}}, headers=h)
    assert r.status_code == 422
    # grc в тестовой установке нет.
    r = client.put(f"/admin/users/{u['id']}/roles", json={"products": {"grc": ["viewer"]}}, headers=h)
    assert r.status_code == 422
    # Пустой список снимает роли продукта.
    r = client.put(f"/admin/users/{u['id']}/roles", json={"products": {"scanner": []}}, headers=h)
    assert r.json()["roles"] == {}


def test_admin_cannot_grant_self(client, db):
    h = _admin(client)
    me = client.get("/me", headers=h).json()
    p = _mk_project(client, h)
    for method, url, body in [
        ("put", f"/admin/users/{me['id']}/roles", {"products": {"scanner": ["operator"]}}),
        ("put", f"/admin/users/{me['id']}/projects", {"all_projects": True}),
        ("patch", f"/admin/users/{me['id']}", {"is_active": False}),
        ("put", f"/admin/projects/{p['id']}/members", [{"user_id": me["id"]}]),
    ]:
        r = getattr(client, method)(url, json=body, headers=h)
        assert r.status_code == 403, (url, r.text)
        assert "Разделение обязанностей" in r.json()["detail"]
    # Через команду — тоже нельзя.
    g = client.post("/admin/groups", json={"name": "Пентест"}, headers=h).json()
    assert (
        client.put(
            f"/admin/groups/{g['id']}/roles", json={"products": {"scanner": ["operator"]}}, headers=h
        ).status_code
        == 200
    )
    r = client.put(f"/admin/groups/{g['id']}/members", json={"ids": [me["id"]]}, headers=h)
    assert r.status_code == 403
    # Свои имя и почту менять можно.
    assert (
        client.patch(f"/admin/users/{me['id']}", json={"display_name": "Админ"}, headers=h).status_code == 200
    )


def test_admin_in_group_cannot_extend_group(client):
    h = _admin(client)
    me = client.get("/me", headers=h).json()
    g = client.post("/admin/groups", json={"name": "Пустая"}, headers=h).json()
    assert (
        client.put(f"/admin/groups/{g['id']}/members", json={"ids": [me["id"]]}, headers=h).status_code == 200
    )
    r = client.put(f"/admin/groups/{g['id']}/roles", json={"products": {"vm": ["engineer"]}}, headers=h)
    assert r.status_code == 403


def test_group_roles_and_projects_flow_into_token(client):
    h = _admin(client)
    u = _mk_user(client, h)
    p = _mk_project(client, h)
    g = client.post("/admin/groups", json={"name": "Инженеры"}, headers=h).json()
    client.put(f"/admin/groups/{g['id']}/roles", json={"products": {"vm": ["engineer"]}}, headers=h)
    client.put(f"/admin/groups/{g['id']}/projects", json={"ids": [p["id"]]}, headers=h)
    client.put(f"/admin/groups/{g['id']}/members", json={"ids": [u["id"]]}, headers=h)
    client.put(f"/admin/users/{u['id']}/roles", json={"products": {"scanner": ["auditor"]}}, headers=h)
    token, _ = login(client, "ivanov", "long-password-1")
    c = claims(token)
    assert c["products"] == {"scanner": ["auditor"], "vm": ["engineer"]}
    assert c["projects"] == [p["id"]]


def test_role_revocation_applies_on_next_refresh(client):
    h = _admin(client)
    u = _mk_user(client, h)
    client.put(f"/admin/users/{u['id']}/roles", json={"products": {"scanner": ["operator"]}}, headers=h)
    token, cookie = login(client, "ivanov", "long-password-1")
    assert claims(token)["products"] == {"scanner": ["operator"]}
    client.put(f"/admin/users/{u['id']}/roles", json={"products": {"scanner": []}}, headers=h)
    r = do_refresh(client, cookie)
    assert r.status_code == 200 and claims(r.json()["access_token"])["products"] == {}


def test_deactivation_revokes_sessions(client):
    h = _admin(client)
    u = _mk_user(client, h)
    _, cookie = login(client, "ivanov", "long-password-1")
    assert client.patch(f"/admin/users/{u['id']}", json={"is_active": False}, headers=h).status_code == 200
    assert do_refresh(client, cookie).status_code == 401
    assert (
        client.post("/auth/login", json={"username": "ivanov", "password": "long-password-1"}).status_code
        == 401
    )


def test_unlock_and_password_reset(client, db):
    h = _admin(client)
    u = _mk_user(client, h)
    for _ in range(5):
        client.post("/auth/login", json={"username": "ivanov", "password": "bad"})
    assert client.get(f"/admin/users/{u['id']}", headers=h).json()["locked"] is True
    assert client.post(f"/admin/users/{u['id']}/unlock", headers=h).json()["locked"] is False
    _, cookie = login(client, "ivanov", "long-password-1")
    assert (
        client.post(
            f"/admin/users/{u['id']}/password", json={"password": "another-pass-2"}, headers=h
        ).status_code
        == 204
    )
    assert do_refresh(client, cookie).status_code == 401
    login(client, "ivanov", "another-pass-2")
    actions = {a.action for a in db.query(AuditLog).all()}
    assert {"user.create", "user.unlock", "user.password", "auth.login"} <= actions
    assert all("another-pass-2" not in str(a.details) for a in db.query(AuditLog).all())


def test_projects_visibility_and_archive(client):
    h = _admin(client)
    u = _mk_user(client, h)
    p1 = _mk_project(client, h, "Первый")
    p2 = _mk_project(client, h, "Второй")
    client.put(
        f"/admin/projects/{p1['id']}/members", json=[{"user_id": u["id"], "project_role": "lead"}], headers=h
    )
    uh = bearer(login(client, "ivanov", "long-password-1")[0])
    assert [p["name"] for p in client.get("/projects", headers=uh).json()] == ["Первый"]
    assert client.get(f"/projects/{p2['id']}", headers=uh).status_code == 403
    assert client.get(f"/projects/{p1['id']}", headers=uh).json()["contract_ref"] == "Д-17/2026"
    r = client.post(f"/admin/projects/{p1['id']}/archive", headers=h)
    assert r.json()["status"] == "archived" and r.json()["archived_at"]
    assert client.get("/projects?status=active", headers=uh).json() == []
    assert client.post(f"/admin/projects/{p1['id']}/restore", headers=h).json()["status"] == "active"
    members = client.get(f"/admin/projects/{p1['id']}/members", headers=h).json()
    assert members[0]["project_role"] == "lead"
    client.put(f"/admin/users/{u['id']}/projects", json={"all_projects": True}, headers=h)
    uh = bearer(login(client, "ivanov", "long-password-1")[0])
    assert client.get("/projects", headers=uh).headers["x-total-count"] == "2"


def test_project_period_validation(client):
    h = _admin(client)
    r = client.post(
        "/admin/projects",
        json={"name": "x", "period_from": "2026-12-01", "period_to": "2026-01-01"},
        headers=h,
    )
    assert r.status_code == 422

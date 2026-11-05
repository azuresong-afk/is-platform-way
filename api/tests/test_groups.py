"""Команды: роли и проекты команды в токене участника, разделение обязанностей (шаг 5.1)."""

import pytest

from tests.helpers import bearer, claims, do_refresh, login, refresh_cookie
from tests.test_access_admin import _mk_project, _mk_user


def _admin(client):
    return bearer(login(client)[0])


def _group(client, h, name="Пентест", **body):
    r = client.post("/admin/groups", json={"name": name, **body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_team_role_reaches_token_on_refresh_and_leaves_after_removal(client):
    h = _admin(client)
    u = _mk_user(client, h)
    p = _mk_project(client, h)
    g = _group(client, h)
    token, cookie = login(client, "ivanov", "long-password-1", platform=False)
    assert claims(token)["products"] == {}

    assert (
        client.put(
            f"/admin/groups/{g['id']}/roles", json={"products": {"vm": ["engineer"]}}, headers=h
        ).status_code
        == 200
    )
    assert (
        client.put(f"/admin/groups/{g['id']}/projects", json={"ids": [p["id"]]}, headers=h).status_code == 200
    )
    r = client.put(f"/admin/groups/{g['id']}/members", json={"ids": [u["id"]]}, headers=h)
    assert r.status_code == 200 and r.json()["members"] == [u["id"]]

    r = do_refresh(client, cookie)
    assert r.status_code == 200, r.text
    c = claims(r.json()["access_token"])
    assert c["products"] == {"vm": ["engineer"]}
    assert c["projects"] == [p["id"]]
    cookie = refresh_cookie(r) or cookie

    # Карточка пользователя: эффективная роль есть, своей нет, команда указана.
    card = client.get(f"/admin/users/{u['id']}", headers=h).json()
    assert card["roles"] == {"vm": ["engineer"]} and card["own_roles"] == {}
    assert card["groups"] == [g["id"]]

    assert client.put(f"/admin/groups/{g['id']}/members", json={"ids": []}, headers=h).status_code == 200
    r = do_refresh(client, cookie)
    assert r.status_code == 200, r.text
    c = claims(r.json()["access_token"])
    assert c["products"] == {} and c["projects"] == []


def test_deleting_team_removes_its_roles(client):
    h = _admin(client)
    u = _mk_user(client, h)
    g = _group(client, h)
    client.put(f"/admin/groups/{g['id']}/roles", json={"products": {"scanner": ["operator"]}}, headers=h)
    client.put(f"/admin/groups/{g['id']}/members", json={"ids": [u["id"]]}, headers=h)
    _, cookie = login(client, "ivanov", "long-password-1")
    assert client.delete(f"/admin/groups/{g['id']}", headers=h).status_code == 204
    r = do_refresh(client, cookie)
    assert claims(r.json()["access_token"])["products"] == {}
    assert client.get("/admin/groups", headers=h).json() == []


@pytest.mark.parametrize("grant", ["roles", "projects"])
def test_admin_cannot_join_team_that_grants_access(client, grant):
    h = _admin(client)
    me = client.get("/me", headers=h).json()
    g = _group(client, h)
    if grant == "roles":
        body = {"products": {"scanner": ["operator"]}}
    else:
        body = {"ids": [_mk_project(client, h)["id"]]}
    assert client.put(f"/admin/groups/{g['id']}/{grant}", json=body, headers=h).status_code == 200
    r = client.put(f"/admin/groups/{g['id']}/members", json={"ids": [me["id"]]}, headers=h)
    assert r.status_code == 403
    assert "Разделение обязанностей" in r.json()["detail"]
    assert client.get("/admin/groups", headers=h).json()[0]["members"] == []


def test_admin_member_cannot_grant_team_anything_but_others_can_stay(client):
    h = _admin(client)
    me = client.get("/me", headers=h).json()
    u = _mk_user(client, h)
    g = _group(client, h)
    assert (
        client.put(f"/admin/groups/{g['id']}/members", json={"ids": [me["id"]]}, headers=h).status_code == 200
    )
    r = client.put(f"/admin/groups/{g['id']}/roles", json={"products": {"vm": ["engineer"]}}, headers=h)
    assert r.status_code == 403
    p = _mk_project(client, h)
    assert (
        client.put(f"/admin/groups/{g['id']}/projects", json={"ids": [p["id"]]}, headers=h).status_code == 403
    )
    # Состав без новых вступлений самого администратора менять можно.
    r = client.put(f"/admin/groups/{g['id']}/members", json={"ids": [me["id"], u["id"]]}, headers=h)
    assert r.status_code == 200


def test_team_name_unique_and_validated(client):
    h = _admin(client)
    a = _group(client, h, "Пентест")
    _group(client, h, "Аудит")
    assert client.post("/admin/groups", json={"name": "Пентест"}, headers=h).status_code == 409
    r = client.patch(f"/admin/groups/{a['id']}", json={"name": "Аудит"}, headers=h)
    assert r.status_code == 409 and "уже есть" in r.json()["detail"]
    r = client.patch(
        f"/admin/groups/{a['id']}",
        json={"name": "Красная команда", "description": "Внешний пентест"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["description"] == "Внешний пентест"
    assert [g["name"] for g in client.get("/admin/groups", headers=h).json()] == ["Аудит", "Красная команда"]
    r = client.put(f"/admin/groups/{a['id']}/roles", json={"products": {"scanner": ["god"]}}, headers=h)
    assert r.status_code == 422


def test_non_admin_cannot_manage_teams(client):
    h = _admin(client)
    _mk_user(client, h)
    uh = bearer(login(client, "ivanov", "long-password-1")[0])
    assert client.get("/admin/groups", headers=uh).status_code == 403
    assert client.post("/admin/groups", json={"name": "x"}, headers=uh).status_code == 403

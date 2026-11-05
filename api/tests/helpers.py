"""Помощники для тестов API."""

from __future__ import annotations

from http.cookies import SimpleCookie

import jwt


def login(client, username="admin", password="admin-password-1"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"], refresh_cookie(r)


def refresh_cookie(response) -> str | None:
    for raw in response.headers.get_list("set-cookie"):
        c = SimpleCookie()
        c.load(raw)
        if "platform_refresh" in c:
            return c["platform_refresh"].value or None
    return None


def cookie_attrs(response) -> str:
    return next(h for h in response.headers.get_list("set-cookie") if h.startswith("platform_refresh="))


def do_refresh(client, cookie):
    client.cookies.clear()
    return client.post("/auth/refresh", headers={"cookie": f"platform_refresh={cookie}"})


def bearer(token: str) -> dict:
    return {"authorization": f"Bearer {token}"}


def claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def make_user(client, admin_headers, username, password="long-password-1", *, activate=True, **fields):
    """Пользователь через API администратора. Пароль от администратора временный (docs/SECURITY.md, п. 6),
    поэтому по умолчанию пользователь сразу сам меняет его на ``password``, как при первом входе."""
    temporary = f"tmp-{password}"
    body = {"username": username, "display_name": username, "password": temporary, **fields}
    r = client.post("/admin/users", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    if not activate:
        return r.json()
    change_password(client, username, temporary, password)
    return client.get(f"/admin/users/{r.json()['id']}", headers=admin_headers).json()


def change_password(client, username, current, new):
    token, _ = login(client, username, current)
    r = client.post(
        "/auth/password",
        json={"current_password": current, "new_password": new},
        headers=bearer(token),
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"], refresh_cookie(r)

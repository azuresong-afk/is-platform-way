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

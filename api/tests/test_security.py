"""Исправления обзора безопасности 5.4 (docs/SECURITY.md)."""

from __future__ import annotations

import pytest

from app import users
from app.builtin_manifests import BUILTIN_MANIFESTS
from app.main import create_app
from app.models import Product
from app.security.links import is_safe_path
from tests.helpers import bearer, do_refresh, login
from tests.test_events import envelope, post


@pytest.mark.parametrize(
    "path",
    ["/vm/tickets/125", "/scanner/runs?project=1#x", "/a/%09b"],
)
def test_safe_path_accepts_same_origin_paths(path):
    assert is_safe_path(path)


@pytest.mark.parametrize(
    "path",
    [
        None,
        "",
        "vm/x",
        "https://evil.example",
        "//evil.example",
        "/\\evil.example",
        "/\t/evil.example",
        "/\n/evil.example",
        "/\r/evil.example",
        "/ /evil.example",
        "/x\x00",
        "/x\x7f",
    ],
)
def test_safe_path_rejects_paths_leading_elsewhere(path):
    assert not is_safe_path(path)


def test_notify_link_with_tab_rejected(client):
    notify = {"users": ["x"], "title": "t", "link": "/\t/e.x"}
    env = envelope(type="vm.ticket.created", source="vm", notify=notify)
    r = post(client, env, product="vm", secret="vm-secret")
    assert r.status_code == 422 and "link" in r.text


def test_inactive_user_with_wrong_password_looks_like_bad_credentials(client, db):
    u = users.create_user(db, username="sidorov", password="long-password-1")
    u.is_active = False
    db.commit()
    assert users.check_login(db, "sidorov", "wrong")[0] == users.LoginResult.BAD_CREDENTIALS
    r = client.post("/auth/login", json={"username": "sidorov", "password": "wrong"})
    assert r.status_code == 401 and r.json()["detail"] == "Неверный логин или пароль"
    r = client.post("/auth/login", json={"username": "nobody", "password": "wrong"})
    assert r.json()["detail"] == "Неверный логин или пароль"
    # с верным паролем пользователь узнаёт, что запись отключена
    r = client.post("/auth/login", json={"username": "sidorov", "password": "long-password-1"})
    assert r.status_code == 401 and r.json()["detail"] == "Учётная запись отключена"


def test_token_responses_are_not_cached(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "admin-password-1"})
    assert r.headers["cache-control"] == "no-store"
    _, cookie = login(client)
    r = do_refresh(client, cookie)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    r = do_refresh(client, "garbage")
    assert r.status_code == 401 and r.headers["cache-control"] == "no-store"


def test_api_docs_disabled_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_api_docs_can_be_enabled(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_docs", True)
    app = create_app()
    assert any(getattr(r, "path", "") == "/openapi.json" for r in app.routes)


def test_manifest_urls_outside_product_are_dropped(client, db):
    prod = db.get(Product, "vm")
    prod.manifest = {
        **BUILTIN_MANIFESTS["vm"],
        "base_path": "javascript:alert(1)//",
        "search_url": "https://evil.example/collect",
        "summary_url": "/api/platform/admin/users",
        "health_url": "/api/vm/health/ready",
    }
    db.commit()
    h = bearer(login(client)[0])
    u = client.post("/admin/users", json={"username": "op", "password": "long-password-1"}, headers=h).json()
    client.put(f"/admin/users/{u['id']}/roles", json={"products": {"vm": ["viewer"]}}, headers=h)
    tab = client.get("/products", headers=bearer(login(client, "op", "long-password-1")[0])).json()[0]
    assert tab["base_path"] == "/vm/"
    assert "search_url" not in tab and "summary_url" not in tab
    assert tab["health_url"] == "/api/vm/health/ready"
    # в администрировании исходный манифест виден целиком — чтобы найти ошибку продукта
    admin = next(p for p in client.get("/admin/products", headers=h).json() if p["id"] == "vm")
    assert admin["manifest"]["search_url"] == "https://evil.example/collect"

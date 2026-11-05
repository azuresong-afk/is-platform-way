"""Отдельный токен оболочки для API платформы (контракт v1.1, п. 2.6; docs/SECURITY.md, п. 11)."""

from __future__ import annotations

import jwt
import pytest

from app.config import get_settings
from app.models import AuditLog
from tests.helpers import bearer, claims, do_refresh, login, platform_token, refresh_cookie

# Эндпоинты администрирования: токен из sessionStorage (aud — продукты) получает на них 401.
ADMIN_GETS = [
    "/admin/users",
    "/admin/groups",
    "/admin/projects",
    "/admin/products",
    "/admin/service-accounts",
    "/admin/keys",
    "/admin/events",
    "/admin/subscriptions",
    "/audit",
    "/audit/facets",
]


def _new_project(client, h) -> dict:
    r = client.post("/admin/projects", json={"name": "Проект А", "client": "ООО «А»"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _post_platform_token(client, cookie):
    client.cookies.clear()
    return client.post("/auth/platform-token", headers={"cookie": f"platform_refresh={cookie}"})


def test_platform_token_shape(client):
    _, cookie = login(client, platform=False)
    r = _post_platform_token(client, cookie)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 300
    c = claims(body["access_token"])
    assert c["aud"] == ["platform"] and c["typ"] == "user"
    assert c["exp"] - c["iat"] == 300
    assert c["platform_admin"] is True and c["preferred_username"] == "admin"
    # Ролей продуктов в токене оболочки нет: продукты его не принимают.
    assert "products" not in c and "projects" not in c
    # Cookie не ротируется и не ставится заново.
    assert refresh_cookie(r) is None


def test_product_token_has_no_platform_audience(client):
    token, _ = login(client, platform=False)
    assert "platform" not in claims(token)["aud"]
    r = do_refresh(client, login(client, platform=False)[1])
    assert "platform" not in claims(r.json()["access_token"])["aud"]


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_session_storage_token_gets_401_on_admin(client, path):
    product_token, cookie = login(client, platform=False)
    r = client.get(path, headers=bearer(product_token))
    assert r.status_code == 401 and r.json()["detail"] == "platform_token_required"
    assert r.headers["www-authenticate"] == "Bearer"
    assert client.get(path, headers=bearer(platform_token(client, cookie))).status_code == 200


def test_session_storage_token_cannot_write_admin(client):
    product_token, _ = login(client, platform=False)
    h = bearer(product_token)
    r = client.post("/admin/users", json={"username": "x1", "password": "long-password-1"}, headers=h)
    assert r.status_code == 401
    assert client.post("/admin/projects", json={"name": "x"}, headers=h).status_code == 401
    assert client.post("/admin/keys/rotate", headers=h).status_code == 401


def test_admin_override_needs_platform_token(client):
    """Чтение чужого проекта и его активов администратором — только с токеном оболочки."""
    product_token, cookie = login(client, platform=False)
    ph = bearer(platform_token(client, cookie))
    proj = _new_project(client, ph)
    h = bearer(product_token)
    assert client.get(f"/projects/{proj['id']}", headers=h).status_code == 403
    assert client.get(f"/projects/{proj['id']}/assets", headers=h).status_code == 403
    assert client.get(f"/projects/{proj['id']}", headers=ph).status_code == 200
    assert client.get(f"/projects/{proj['id']}/assets", headers=ph).status_code == 200


def test_session_storage_token_still_works_for_user_endpoints(client):
    """Продукты ходят в API платформы с токеном пользователя: профиль, вкладки, уведомления."""
    product_token, _ = login(client, platform=False)
    h = bearer(product_token)
    assert client.get("/me", headers=h).status_code == 200
    assert client.get("/products", headers=h).status_code == 200
    assert client.get("/projects", headers=h).status_code == 200
    assert client.get("/notifications", headers=h).status_code == 200


def test_platform_token_rejected_by_products(client):
    """Продукт проверяет свой id в aud: токен оболочки ему не подходит."""
    _, cookie = login(client, platform=False)
    token = platform_token(client, cookie)
    kid = jwt.get_unverified_header(token)["kid"]
    jwk = next(k for k in client.get("/.well-known/jwks.json").json()["keys"] if k["kid"] == kid)
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(token, jwt.PyJWK(jwk).key, algorithms=["EdDSA"], audience="scanner")


def test_non_admin_platform_token_gets_403(client):
    ph = bearer(login(client)[0])
    r = client.post("/admin/users", json={"username": "petrov", "password": "long-password-1"}, headers=ph)
    assert r.status_code == 201
    uh = bearer(login(client, "petrov", "long-password-1")[0])
    assert claims(uh["authorization"][7:])["aud"] == ["platform"]
    assert client.get("/admin/users", headers=uh).status_code == 403


def test_platform_token_keeps_cookie_usable(client):
    _, cookie = login(client, platform=False)
    for _ in range(3):
        assert _post_platform_token(client, cookie).status_code == 200
    r = do_refresh(client, cookie)
    assert r.status_code == 200
    # После ротации прежняя cookie в окне гонки ещё годится, новая — тоже.
    assert _post_platform_token(client, cookie).status_code == 200
    assert _post_platform_token(client, refresh_cookie(r)).status_code == 200


def test_platform_token_requires_valid_session(client):
    assert _post_platform_token(client, "").status_code == 401
    assert _post_platform_token(client, "garbage.value").status_code == 401
    _, cookie = login(client, platform=False)
    client.cookies.clear()
    client.post("/auth/logout", headers={"cookie": f"platform_refresh={cookie}"})
    r = _post_platform_token(client, cookie)
    assert r.status_code == 401 and r.json()["detail"] == "revoked"


def test_platform_token_reuse_revokes_family(client, db):
    s = get_settings()
    s.refresh_reuse_grace_seconds = -1
    try:
        _, cookie = login(client, platform=False)
        fresh = refresh_cookie(do_refresh(client, cookie))
        r = _post_platform_token(client, cookie)
        assert r.status_code == 401 and r.json()["detail"] == "reused"
        assert db.query(AuditLog).filter_by(action="auth.refresh_reuse").count() == 1
        # Семейство отозвано: свежая cookie тоже не годится.
        assert _post_platform_token(client, fresh).status_code == 401
    finally:
        s.refresh_reuse_grace_seconds = 10


def test_blocked_user_gets_no_platform_token(client):
    ph = bearer(login(client)[0])
    body = {"username": "sidorov", "password": "long-password-1"}
    u = client.post("/admin/users", json=body, headers=ph).json()
    _, cookie = login(client, "sidorov", "long-password-1", platform=False)
    assert client.patch(f"/admin/users/{u['id']}", json={"is_active": False}, headers=ph).status_code == 200
    assert _post_platform_token(client, cookie).status_code == 401

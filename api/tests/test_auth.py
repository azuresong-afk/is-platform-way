import jwt
import pytest

from app import users
from app.config import get_settings
from app.models import AuditLog, UserProductRole
from tests.helpers import bearer, claims, cookie_attrs, do_refresh, login, refresh_cookie


def test_login_issues_eddsa_token_verifiable_by_jwks(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "admin-password-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 900
    token = body["access_token"]
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "EdDSA" and header["kid"]
    jwks = client.get("/.well-known/jwks.json")
    assert "max-age=600" in jwks.headers["cache-control"]
    jwk = next(k for k in jwks.json()["keys"] if k["kid"] == header["kid"])
    assert jwk["kty"] == "OKP" and jwk["crv"] == "Ed25519" and "d" not in jwk
    data = jwt.decode(token, jwt.PyJWK(jwk).key, algorithms=["EdDSA"], audience="scanner")
    assert data["iss"] == "platform"
    assert data["exp"] - data["iat"] == 900
    # aud — все продукты установки + платформа (grc в тестах не установлен).
    assert data["aud"] == ["scanner", "vm", "platform"]
    assert data["preferred_username"] == "admin" and data["typ"] == "user"
    assert data["products"] == {} and data["projects"] == []
    attrs = cookie_attrs(r).lower()
    assert "httponly" in attrs and "samesite=strict" in attrs and "path=/api/platform/auth" in attrs


def test_cookie_secure_flag_in_production(client):
    s = get_settings()
    s.cookie_secure = True
    try:
        r = client.post("/auth/login", json={"username": "admin", "password": "admin-password-1"})
        assert "secure" in cookie_attrs(r).lower()
    finally:
        s.cookie_secure = False


def test_token_contains_roles_and_projects(client, db):
    u = users.create_user(db, username="op", password="pw-123456")
    db.add_all(
        [
            UserProductRole(user_id=u.id, product_id="scanner", role="operator"),
            UserProductRole(user_id=u.id, product_id="vm", role="engineer"),
            # Продукт не установлен — роль в токен не попадает.
            UserProductRole(user_id=u.id, product_id="grc", role="methodologist"),
        ]
    )
    u.all_projects = True
    db.commit()
    token, _ = login(client, "op", "pw-123456")
    c = claims(token)
    assert c["products"] == {"scanner": ["operator"], "vm": ["engineer"]}
    assert c["projects"] == ["*"]


def test_bad_password_401_and_audited(client, db):
    r = client.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Неверный логин или пароль"
    rows = db.query(AuditLog).filter_by(action="auth.login").all()
    assert [x.result for x in rows] == ["failure"]
    assert all("nope" not in str(x.details) for x in rows)


def test_me_requires_valid_token(client):
    assert client.get("/me").status_code == 401
    token, _ = login(client)
    r = client.get("/me", headers=bearer(token))
    assert r.status_code == 200 and r.json()["platform_admin"] is True
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert client.get("/me", headers=bearer(tampered)).status_code == 401


def test_refresh_rotates_cookie(client):
    _, c1 = login(client)
    r = do_refresh(client, c1)
    assert r.status_code == 200
    c2 = refresh_cookie(r)
    assert c2 and c2 != c1
    assert do_refresh(client, c2).status_code == 200


def test_refresh_reuse_within_grace_is_allowed(client):
    _, c1 = login(client)
    assert do_refresh(client, c1).status_code == 200
    # Вторая вкладка с тем же cookie в пределах окна гонки.
    assert do_refresh(client, c1).status_code == 200


def test_refresh_reuse_revokes_family(client, db):
    s = get_settings()
    s.refresh_reuse_grace_seconds = -1
    try:
        _, c1 = login(client)
        c2 = refresh_cookie(do_refresh(client, c1))
        r = do_refresh(client, c1)
        assert r.status_code == 401 and r.json()["detail"] == "reused"
        # Украденный и законный токены семейства больше не работают.
        assert do_refresh(client, c2).status_code == 401
        assert db.query(AuditLog).filter_by(action="auth.refresh_reuse").count() == 1
    finally:
        s.refresh_reuse_grace_seconds = 10


def test_refresh_garbage_cookie(client):
    assert do_refresh(client, "nonsense").status_code == 401
    assert do_refresh(client, "00000000-0000-0000-0000-000000000000.x").status_code == 401
    client.cookies.clear()
    assert client.post("/auth/refresh").status_code == 401


def test_logout_revokes_refresh(client):
    _, c1 = login(client)
    client.cookies.clear()
    r = client.post("/auth/logout", headers={"cookie": f"platform_refresh={c1}"})
    assert r.status_code == 204
    assert 'platform_refresh=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert do_refresh(client, c1).status_code == 401


@pytest.mark.parametrize("how", ["deactivate", "lock"])
def test_blocked_user_gets_no_new_tokens_immediately(client, db, how):
    u = users.create_user(db, username="victim", password="pw-123456")
    db.commit()
    token, cookie = login(client, "victim", "pw-123456")
    if how == "deactivate":
        u.is_active = False
    else:
        from datetime import timedelta

        from app.db import utcnow

        u.locked_until = utcnow() + timedelta(minutes=5)
    db.commit()
    r = do_refresh(client, cookie)
    assert r.status_code == 401 and r.json()["detail"] == "user_blocked"
    # API платформы не принимает и уже выданный токен.
    assert client.get("/me", headers=bearer(token)).status_code == 401


def test_key_rotation_keeps_old_tokens_valid(client, db):
    from app.security import keys

    old_token, _ = login(client)
    old_kid = jwt.get_unverified_header(old_token)["kid"]
    new = keys.rotate(db)
    assert new.kid != old_kid
    kids = [k["kid"] for k in client.get("/.well-known/jwks.json").json()["keys"]]
    assert old_kid in kids and new.kid in kids
    assert client.get("/me", headers=bearer(old_token)).status_code == 200
    new_token, _ = login(client)
    assert jwt.get_unverified_header(new_token)["kid"] == new.kid


def test_private_key_is_encrypted_at_rest(db, client):
    from app.models import SigningKey

    key = db.query(SigningKey).filter_by(status="active").one()
    assert key.private_key_enc.startswith("v1:")
    assert "d" not in key.public_jwk

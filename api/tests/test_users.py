import hashlib

from app import users
from app.models import User
from app.security import passwords


def scanner_style_hash(password: str, n: int = 2**14, r: int = 8, p: int = 1) -> str:
    """Хэш в формате «Сканера» с его (возможно более слабыми) параметрами."""
    salt = bytes(range(16))
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=64)
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def test_hash_roundtrip():
    h = passwords.hash_password("секрет-123")
    assert h.startswith("scrypt$32768$8$1$")
    assert passwords.verify_password("секрет-123", h)
    assert not passwords.verify_password("секрет-124", h)
    assert not passwords.needs_rehash(h)


def test_scanner_format_is_accepted_and_rehashed():
    old = scanner_style_hash("pass-from-scanner")
    assert passwords.verify_password("pass-from-scanner", old)
    assert passwords.needs_rehash(old)


def test_garbage_hash_rejected():
    assert not passwords.verify_password("x", "bcrypt$foo")
    assert not passwords.verify_password("x", "scrypt$3$8$1$00$00")
    assert not passwords.verify_password("x", None)


def test_bootstrap_admin_created(db):
    admin = users.get_by_username(db, "ADMIN")
    assert admin is not None and admin.is_platform_admin


def test_login_rehashes_scanner_password(db):
    u = users.create_user(db, username="Ivanov", password_hash=scanner_style_hash("p1"))
    db.commit()
    res, user = users.check_login(db, "ivanov", "p1")
    assert res == users.LoginResult.OK
    assert user.password_hash.startswith("scrypt$32768$")
    db.commit()
    assert users.check_login(db, "IVANOV", "p1")[0] == users.LoginResult.OK
    assert u.auth_source == "local"


def test_lockout_after_failures(db):
    users.create_user(db, username="petrov", password="right-one")
    db.commit()
    for _ in range(4):
        assert users.check_login(db, "petrov", "wrong")[0] == users.LoginResult.BAD_CREDENTIALS
    assert users.check_login(db, "petrov", "wrong")[0] == users.LoginResult.LOCKED
    # Даже верный пароль не пускает, пока действует блокировка.
    assert users.check_login(db, "petrov", "right-one")[0] == users.LoginResult.LOCKED
    user = db.query(User).filter_by(username="petrov").one()
    assert not users.can_receive_tokens(user)


def test_inactive_user(db):
    u = users.create_user(db, username="sidorov", password="pw")
    u.is_active = False
    db.commit()
    assert users.check_login(db, "sidorov", "pw")[0] == users.LoginResult.INACTIVE


def test_ldap_user_cannot_use_local_password(db):
    u = users.create_user(db, username="ldapuser", password="pw")
    u.auth_source = "ldap"
    db.commit()
    assert users.check_login(db, "ldapuser", "pw")[0] == users.LoginResult.BAD_CREDENTIALS


def test_health(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["db"] == "ok"

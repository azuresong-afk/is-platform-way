"""Пользователи: создание, проверка пароля с блокировкой после N неудачных попыток."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import aware, utcnow
from .models import User
from .security import passwords


class LoginResult(StrEnum):
    OK = "ok"
    BAD_CREDENTIALS = "bad_credentials"
    LOCKED = "locked"
    INACTIVE = "inactive"


def normalize_username(username: str) -> str:
    return username.strip().lower()


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalars(select(User).where(func.lower(User.username) == normalize_username(username))).first()


def create_user(
    db: Session,
    *,
    username: str,
    display_name: str = "",
    email: str | None = None,
    password: str | None = None,
    password_hash: str | None = None,
    is_platform_admin: bool = False,
) -> User:
    user = User(
        username=normalize_username(username),
        display_name=display_name or username,
        email=email,
        password_hash=password_hash or (passwords.hash_password(password) if password else None),
        is_platform_admin=is_platform_admin,
    )
    db.add(user)
    db.flush()
    return user


def is_locked(user: User) -> bool:
    return bool(user.locked_until and aware(user.locked_until) > utcnow())


def can_receive_tokens(user: User) -> bool:
    """Блокировка и отключение действуют сразу на выдачу новых токенов."""
    return user.is_active and not is_locked(user)


def check_login(db: Session, username: str, password: str) -> tuple[LoginResult, User | None]:
    """Проверяет логин и пароль, ведёт счётчик неудач. Коммит — на вызывающем."""
    settings = get_settings()
    user = get_by_username(db, username)
    if user is None or user.auth_source != "local":
        passwords.verify_password(password, None)
        return LoginResult.BAD_CREDENTIALS, user
    if not user.is_active:
        passwords.verify_password(password, None)
        return LoginResult.INACTIVE, user
    if is_locked(user):
        passwords.verify_password(password, None)
        return LoginResult.LOCKED, user
    if not passwords.verify_password(password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = utcnow() + timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
            return LoginResult.LOCKED, user
        return LoginResult.BAD_CREDENTIALS, user
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    return LoginResult.OK, user


def ensure_bootstrap_admin(db: Session) -> User | None:
    """Первый администратор из .env (только если пользователей ещё нет)."""
    s = get_settings()
    if not s.bootstrap_admin_username or not s.bootstrap_admin_password:
        return None
    if db.scalar(select(func.count()).select_from(User)):
        return None
    user = create_user(
        db,
        username=s.bootstrap_admin_username,
        display_name=s.bootstrap_admin_name,
        password=s.bootstrap_admin_password,
        is_platform_admin=True,
    )
    db.commit()
    return user

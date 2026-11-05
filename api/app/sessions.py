"""Refresh-токены: выдача, ротация, обнаружение повторного использования, отзыв.

Значение cookie: ``<id>.<секрет>``; в БД хранится только sha256 секрета.
Каждый вход открывает «семейство»; refresh выдаёт следующий токен того же семейства.
Повторное предъявление уже использованного токена (позже окна гонки) — признак кражи:
отзывается всё семейство.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .db import aware, utcnow
from .models import RefreshToken, User


class RefreshError(StrEnum):
    INVALID = "invalid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    REUSED = "reused"
    USER_BLOCKED = "user_blocked"


@dataclass
class Issued:
    cookie_value: str
    record: RefreshToken


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _issue(
    db: Session, user: User, family_id: uuid.UUID, family_expires_at, user_agent: str, ip: str
) -> Issued:
    s = get_settings()
    now = utcnow()
    secret = secrets.token_urlsafe(32)
    rec = RefreshToken(
        family_id=family_id,
        user_id=user.id,
        token_hash=_hash(secret),
        issued_at=now,
        expires_at=min(now + timedelta(hours=s.refresh_ttl_hours), family_expires_at),
        family_expires_at=family_expires_at,
        user_agent=user_agent[:300],
        ip=ip[:64],
    )
    db.add(rec)
    db.flush()
    return Issued(cookie_value=f"{rec.id}.{secret}", record=rec)


def start_session(db: Session, user: User, user_agent: str = "", ip: str = "") -> Issued:
    s = get_settings()
    return _issue(db, user, uuid.uuid4(), utcnow() + timedelta(days=s.refresh_max_days), user_agent, ip)


def revoke_family(db: Session, family_id: uuid.UUID, reason: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoke_reason=reason)
    )


def revoke_user(db: Session, user_id: uuid.UUID, reason: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoke_reason=reason)
    )


def find(db: Session, cookie_value: str | None) -> tuple[RefreshToken | None, bool]:
    """Ищет запись по значению cookie. Возвращает (запись, секрет верен)."""
    if not cookie_value or "." not in cookie_value:
        return None, False
    raw_id, secret = cookie_value.split(".", 1)
    try:
        rid = uuid.UUID(raw_id)
    except ValueError:
        return None, False
    rec = db.get(RefreshToken, rid)
    if rec is None:
        return None, False
    return rec, hmac.compare_digest(rec.token_hash, _hash(secret))


def check(
    db: Session, cookie_value: str | None
) -> tuple[User | None, RefreshToken | None, RefreshError | None]:
    """Проверка cookie без ротации (те же правила, что у rotate, включая отзыв семейства).

    Коммит — на вызывающем.
    """
    s = get_settings()
    rec, ok = find(db, cookie_value)
    if rec is None or not ok:
        return None, rec if ok else None, RefreshError.INVALID
    now = utcnow()
    if rec.revoked_at is not None:
        return None, rec, RefreshError.REVOKED
    if rec.used_at is not None:
        # Две вкладки обновились почти одновременно — это не кража.
        if now - aware(rec.used_at) > timedelta(seconds=s.refresh_reuse_grace_seconds):
            revoke_family(db, rec.family_id, "reuse_detected")
            return None, rec, RefreshError.REUSED
    if aware(rec.expires_at) <= now:
        return None, rec, RefreshError.EXPIRED
    user = db.get(User, rec.user_id)
    from .users import can_receive_tokens

    if user is None or not can_receive_tokens(user):
        revoke_family(db, rec.family_id, "user_blocked")
        return None, rec, RefreshError.USER_BLOCKED
    return user, rec, None


def rotate(
    db: Session, cookie_value: str | None, user_agent: str = "", ip: str = ""
) -> tuple[Issued | None, RefreshToken | None, RefreshError | None]:
    """Ротация. Коммит — на вызывающем (в т. ч. при ошибке: отзыв семейства надо сохранить)."""
    user, rec, err = check(db, cookie_value)
    if err is not None or user is None or rec is None:
        return None, rec, err
    if rec.used_at is None:
        rec.used_at = utcnow()
    issued = _issue(db, user, rec.family_id, aware(rec.family_expires_at), user_agent, ip)
    return issued, rec, None


def active_sessions(db: Session, user_id: uuid.UUID) -> list[RefreshToken]:
    now = utcnow()
    return [
        r
        for r in db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.used_at.is_(None),
            )
        )
        if aware(r.expires_at) > now
    ]

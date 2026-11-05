"""Ключи подписи Ed25519, JWKS и выдача/проверка JWT (контракт v1, п. 2; v1.1, п. 2.3)."""

from __future__ import annotations

import base64
import logging
import secrets
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import aware, utcnow
from ..models import SigningKey
from . import crypto

log = logging.getLogger(__name__)

_private_cache: dict[str, Ed25519PrivateKey] = {}

CLOCK_SKEW_SECONDS = 60


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _new_kid() -> str:
    return utcnow().strftime("%Y%m%d") + "-" + secrets.token_hex(4)


def generate_key(db: Session, status: str = "active") -> SigningKey:
    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    raw_pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    kid = _new_kid()
    key = SigningKey(
        kid=kid,
        private_key_enc=crypto.encrypt(raw_priv, aad=kid.encode()),
        public_jwk={
            "kty": "OKP",
            "crv": "Ed25519",
            "x": _b64url(raw_pub),
            "kid": kid,
            "alg": "EdDSA",
            "use": "sig",
        },
        status=status,
        activated_at=utcnow() if status == "active" else None,
    )
    db.add(key)
    db.flush()
    _private_cache[kid] = priv
    return key


def active_key(db: Session) -> SigningKey | None:
    return db.scalars(
        select(SigningKey).where(SigningKey.status == "active").order_by(SigningKey.activated_at.desc())
    ).first()


def ensure_active_key(db: Session) -> SigningKey:
    key = active_key(db)
    if key is None:
        key = generate_key(db, "active")
        db.commit()
    return key


SYSTEM_ACTOR = "Платформа (плановая ротация)"


def _audit(
    db: Session, action: str, key: SigningKey, actor: tuple[str | None, str, str] | None, **details
) -> None:
    # Импорт здесь: audit -> models, а keys импортируется очень рано (deps).
    from .. import audit

    sub, name, ip = actor or (None, SYSTEM_ACTOR, "")
    audit.record(
        db,
        action=action,
        actor_sub=sub,
        actor_name=name,
        object=f"signing_key/{key.kid}",
        ip=ip,
        details=details,
    )


def _publish_rotated(db: Session, key: SigningKey, revoked: list[str]) -> None:
    """platform.keys.rotated (контракт v1.1, п. 6.2): новый активный kid и отозванные kid.

    Продукт, получивший непустой revoked, сбрасывает кэш JWKS сразу.
    """
    from .. import events

    events.publish(
        db, "platform.keys.rotated", {"kid": key.kid, "revoked": revoked}, subject=f"key/{key.kid}"
    )


def next_key(db: Session) -> SigningKey | None:
    return db.scalars(
        select(SigningKey).where(SigningKey.status == "next").order_by(SigningKey.created_at)
    ).first()


def _activate(db: Session, key: SigningKey, now, *, revoke_previous: bool = False) -> list[SigningKey]:
    previous = list(db.scalars(select(SigningKey).where(SigningKey.status == "active")))
    for old in previous:
        old.status = "revoked" if revoke_previous else "retired"
        old.retired_at = now
    key.status = "active"
    key.activated_at = now
    return previous


def schedule_next(db: Session, actor: tuple[str | None, str, str] | None = None) -> SigningKey:
    """Плановая ротация: публикует ключ next в JWKS; подписывать он начнёт через key_next_lead_seconds.

    Если ключ next уже опубликован — возвращает его, второй не создаёт.
    """
    key = next_key(db)
    if key is None:
        key = generate_key(db, "next")
        _audit(db, "keys.next_published", key, actor, lead_seconds=get_settings().key_next_lead_seconds)
    db.commit()
    return key


def rotate(
    db: Session, actor: tuple[str | None, str, str] | None = None, *, revoke_previous: bool = False
) -> SigningKey:
    """Немедленная ротация: новый ключ активен сразу.

    Прежний остаётся в JWKS ещё jwks_retain_seconds, чтобы выданные токены доживали
    свой срок; при revoke_previous (компрометация) он сразу убирается из JWKS
    и подписанные им токены перестают проверяться.
    Продукты, не нашедшие kid в кэше, перечитывают JWKS сразу (контракт v1.1, п. 2.3),
    поэтому немедленная смена ключа их не ломает. Если ключ next уже опубликован,
    активируется он — его продукты, скорее всего, уже закэшировали.
    """
    key = next_key(db) or generate_key(db, "next")
    now = utcnow()
    previous = _activate(db, key, now, revoke_previous=revoke_previous)
    _audit(
        db,
        "keys.rotate_immediate",
        key,
        actor,
        previous=[k.kid for k in previous],
        revoke_previous=revoke_previous,
    )
    if revoke_previous:
        for old in previous:
            _wipe(old)
    _publish_rotated(db, key, [k.kid for k in previous] if revoke_previous else [])
    db.commit()
    return key


def _wipe(key: SigningKey) -> None:
    """Ключ больше никогда не подписывает: приватную часть не храним."""
    key.private_key_enc = ""
    _private_cache.pop(key.kid, None)


def rotation_due_at(db: Session) -> datetime | None:
    """Когда текущий активный ключ должен смениться по расписанию."""
    key = active_key(db)
    if key is None or key.activated_at is None:
        return None
    return aware(key.activated_at) + timedelta(days=get_settings().key_rotation_days)


def promote_at(key: SigningKey) -> datetime:
    return aware(key.created_at) + timedelta(seconds=get_settings().key_next_lead_seconds)


def tick(db: Session) -> None:
    """Шаг плановой ротации (фоновый поток, раз в key_rotation_check_seconds).

    1. За key_next_lead_seconds до срока публикует ключ next.
    2. Ключ next, пробывший в JWKS не меньше key_next_lead_seconds, становится активным —
       так продукты успевают перечитать JWKS до того, как им начнут подписывать.
    3. Стирает приватную часть ключей, которые ушли из JWKS.
    """
    settings = get_settings()
    now = utcnow()
    # В PostgreSQL блокирует строку активного ключа: два процесса API не создадут два next.
    active = db.scalars(
        select(SigningKey)
        .where(SigningKey.status == "active")
        .order_by(SigningKey.activated_at.desc())
        .with_for_update()
    ).first()
    if active is None:
        ensure_active_key(db)
        return
    nxt = next_key(db)
    due = rotation_due_at(db)
    if nxt is None and due is not None and due - timedelta(seconds=settings.key_next_lead_seconds) <= now:
        nxt = generate_key(db, "next")
        _audit(db, "keys.next_published", nxt, None, lead_seconds=settings.key_next_lead_seconds)
    if nxt is not None and promote_at(nxt) <= now:
        previous = _activate(db, nxt, now)
        _audit(db, "keys.activated", nxt, None, previous=[k.kid for k in previous])
        _publish_rotated(db, nxt, [])
    retain = timedelta(seconds=settings.jwks_retain_seconds)
    for old in db.scalars(select(SigningKey).where(SigningKey.status.in_(("retired", "revoked")))):
        if old.private_key_enc and (
            old.status == "revoked" or (old.retired_at and aware(old.retired_at) + retain <= now)
        ):
            _wipe(old)
    db.commit()


def in_jwks(key: SigningKey, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if key.status in ("active", "next"):
        return True
    retain = timedelta(seconds=get_settings().jwks_retain_seconds)
    return key.status == "retired" and key.retired_at is not None and aware(key.retired_at) + retain > now


def jwks(db: Session) -> dict[str, Any]:
    now = utcnow()
    return {
        "keys": [
            k.public_jwk
            for k in db.scalars(select(SigningKey).order_by(SigningKey.created_at))
            if in_jwks(k, now)
        ]
    }


class RotationScheduler(threading.Thread):
    def __init__(self, interval: int) -> None:
        super().__init__(name="key-rotation", daemon=True)
        self.interval = interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        from ..db import session_scope

        while not self.stop_event.is_set():
            with session_scope() as db:
                try:
                    tick(db)
                except Exception:  # noqa: BLE001 - фоновая задача не должна падать
                    log.exception("Ошибка плановой ротации ключей подписи")
                    db.rollback()
            self.stop_event.wait(self.interval)


def _private(key: SigningKey) -> Ed25519PrivateKey:
    priv = _private_cache.get(key.kid)
    if priv is None:
        raw = crypto.decrypt(key.private_key_enc, aad=key.kid.encode())
        priv = Ed25519PrivateKey.from_private_bytes(raw)
        _private_cache[key.kid] = priv
    return priv


def sign(db: Session, claims: dict[str, Any], ttl_seconds: int | None = None) -> str:
    settings = get_settings()
    key = ensure_active_key(db)
    now = int(utcnow().timestamp())
    payload = {
        "iss": settings.issuer,
        "iat": now,
        "exp": now + (ttl_seconds or settings.access_ttl_seconds),
        "jti": str(uuid.uuid4()),
        **claims,
    }
    return jwt.encode(payload, _private(key), algorithm="EdDSA", headers={"kid": key.kid, "typ": "JWT"})


def verify(db: Session, token: str, audience: str | list[str] = "platform") -> dict[str, Any]:
    """Проверка токена, выданного платформой (aud — хоть одно из audience).

    Бросает jwt.InvalidTokenError.
    """
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "EdDSA":
        raise jwt.InvalidAlgorithmError("ожидается EdDSA")
    kid = header.get("kid")
    jwk = next((k for k in jwks(db)["keys"] if k["kid"] == kid), None)
    if jwk is None:
        # InvalidKeyError не наследует InvalidTokenError: вызывающие ловят InvalidTokenError.
        raise jwt.InvalidTokenError("неизвестный kid")
    pub = jwt.PyJWK(jwk).key
    return jwt.decode(
        token,
        pub,
        algorithms=["EdDSA"],
        audience=audience,
        issuer=get_settings().issuer,
        leeway=CLOCK_SKEW_SECONDS,
        options={"require": ["exp", "iat", "sub", "aud", "iss", "jti"]},
    )

"""Ключи подписи Ed25519, JWKS и выдача/проверка JWT (контракт v1, п. 2; v1.1, п. 2.3)."""

from __future__ import annotations

import base64
import secrets
import uuid
from datetime import timedelta
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


def rotate(db: Session) -> SigningKey:
    """Немедленная ротация: новый ключ активен, прежний остаётся в JWKS ещё jwks_retain_seconds.

    Продукты, не нашедшие kid в кэше, перечитывают JWKS сразу (контракт v1.1, п. 2.3),
    поэтому немедленная смена ключа не ломает их.
    """
    now = utcnow()
    for old in db.scalars(select(SigningKey).where(SigningKey.status == "active")):
        old.status = "retired"
        old.retired_at = now
    nxt = db.scalars(select(SigningKey).where(SigningKey.status == "next")).first()
    if nxt is not None:
        nxt.status = "active"
        nxt.activated_at = now
        key = nxt
    else:
        key = generate_key(db, "active")
    db.commit()
    return key


def jwks(db: Session) -> dict[str, Any]:
    retain = timedelta(seconds=get_settings().jwks_retain_seconds)
    now = utcnow()
    out = []
    for key in db.scalars(select(SigningKey).order_by(SigningKey.created_at)):
        if key.status in ("active", "next") or (
            key.status == "retired" and key.retired_at and aware(key.retired_at) + retain > now
        ):
            out.append(key.public_jwk)
    return {"keys": out}


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


def verify(db: Session, token: str, audience: str = "platform") -> dict[str, Any]:
    """Проверка токена, выданного платформой. Бросает jwt.InvalidTokenError."""
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "EdDSA":
        raise jwt.InvalidAlgorithmError("ожидается EdDSA")
    kid = header.get("kid")
    jwk = next((k for k in jwks(db)["keys"] if k["kid"] == kid), None)
    if jwk is None:
        raise jwt.InvalidKeyError("неизвестный kid")
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

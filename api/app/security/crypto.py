"""Шифрование секретов в БД: AES-GCM ключом PLATFORM_SECRET_KEY."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import get_settings

_PREFIX = "v1:"


def encrypt(plaintext: bytes, aad: bytes = b"") -> str:
    key = get_settings().secret_key_bytes()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad or None)
    return _PREFIX + base64.b64encode(nonce + ct).decode()


def decrypt(token: str, aad: bytes = b"") -> bytes:
    if not token.startswith(_PREFIX):
        raise ValueError("неизвестный формат шифртекста")
    raw = base64.b64decode(token[len(_PREFIX) :])
    key = get_settings().secret_key_bytes()
    return AESGCM(key).decrypt(raw[:12], raw[12:], aad or None)

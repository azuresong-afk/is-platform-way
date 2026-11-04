"""Пароли: scrypt.

Формат хэша совпадает со «Сканером»: ``scrypt$N$r$p$salt_hex$dk_hex``. Поэтому
пароли пользователей, перенесённых из «Сканера», проверяются без изменений;
если параметры хэша слабее текущих, при входе хэш пересчитывается.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

N = 2**15
R = 8
P = 1
DKLEN = 32
SALT_BYTES = 16


def _maxmem(n: int, r: int, p: int) -> int:
    # scrypt требует ~128*N*r*p байт; берём с запасом.
    return 128 * n * r * (p + 2) + 1024 * 1024


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=DKLEN, maxmem=_maxmem(N, R, P))
    return f"scrypt${N}${R}${P}${salt.hex()}${dk.hex()}"


def _parse(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, dk = bytes.fromhex(parts[4]), bytes.fromhex(parts[5])
    except ValueError:
        return None
    if n < 2 or n & (n - 1) or r < 1 or p < 1 or not dk or n > 2**20:
        return None
    return n, r, p, salt, dk


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # Выравниваем время ответа для несуществующих пользователей.
        hashlib.scrypt(b"x", salt=b"0" * SALT_BYTES, n=N, r=R, p=P, dklen=DKLEN, maxmem=_maxmem(N, R, P))
        return False
    parsed = _parse(stored)
    if parsed is None:
        return False
    n, r, p, salt, dk = parsed
    got = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=len(dk), maxmem=_maxmem(n, r, p))
    return hmac.compare_digest(got, dk)


def needs_rehash(stored: str | None) -> bool:
    parsed = _parse(stored or "")
    if parsed is None:
        return True
    n, r, p, salt, dk = parsed
    return n < N or r < R or p < P or len(dk) < DKLEN or len(salt) < SALT_BYTES

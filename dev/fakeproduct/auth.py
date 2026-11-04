"""Проверка JWT платформы на стороне продукта — эталон для продуктов (контракт v1, п. 2; v1.1, п. 2).

- подпись EdDSA по JWKS платформы, кэш 10 минут;
- неизвестный kid — немедленное перечитывание JWKS, но не чаще раза в 30 с;
- exp/iat/iss/aud (свой id), сдвиг часов 60 с;
- нет своих ролей — 403 no_product_roles; нет доступа к проекту — 403 no_project_access.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import httpx
import jwt
from fastapi import HTTPException, Request, status

JWKS_TTL = 600
JWKS_MIN_REFETCH = 30
LEEWAY = 60


class JwksCache:
    def __init__(self, url: str, fetch=None) -> None:
        self.url = url
        self._fetch = fetch or self._http_fetch
        self._keys: dict[str, dict] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _http_fetch(self) -> dict:
        r = httpx.get(self.url, timeout=5.0)
        r.raise_for_status()
        return r.json()

    def _refresh(self) -> None:
        data = self._fetch()
        self._keys = {k["kid"]: k for k in data.get("keys", []) if k.get("kid")}
        self._fetched_at = time.monotonic()

    def get(self, kid: str) -> dict | None:
        with self._lock:
            age = time.monotonic() - self._fetched_at
            if not self._keys or age > JWKS_TTL or (kid not in self._keys and age > JWKS_MIN_REFETCH):
                try:
                    self._refresh()
                except (httpx.HTTPError, ValueError):
                    pass
            return self._keys.get(kid)


@dataclass
class Caller:
    sub: str
    username: str
    name: str
    roles: list[str]
    projects: list[str]
    typ: str = "user"
    claims: dict = field(default_factory=dict)

    def can_project(self, project_id: str | None) -> bool:
        return "*" in self.projects or (project_id is not None and project_id in self.projects)


def _unauth(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def verify_request(request: Request, product_id: str, jwks: JwksCache, issuer: str = "platform") -> Caller:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise _unauth("not_authenticated")
    token = auth[7:].strip()
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "EdDSA":
            raise _unauth("invalid_token")
        jwk = jwks.get(header.get("kid", ""))
        if jwk is None:
            raise _unauth("invalid_token")
        claims = jwt.decode(
            token,
            jwt.PyJWK(jwk).key,
            algorithms=["EdDSA"],
            audience=product_id,
            issuer=issuer,
            leeway=LEEWAY,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.InvalidTokenError as exc:
        raise _unauth("invalid_token") from exc
    roles = list((claims.get("products") or {}).get(product_id) or [])
    if not roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="no_product_roles")
    return Caller(
        sub=claims["sub"],
        username=claims.get("preferred_username", ""),
        name=claims.get("name", ""),
        roles=roles,
        projects=list(claims.get("projects") or []),
        typ=claims.get("typ", "user"),
        claims=claims,
    )


def require_project(caller: Caller, project_id: str | None) -> None:
    if not project_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="project_required")
    if not caller.can_project(project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="no_project_access")

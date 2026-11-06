"""Проверка JWT платформы на стороне продукта — эталон для продуктов (контракт v1, п. 2; v1.1, п. 2).

- подпись EdDSA по JWKS платформы, кэш 10 минут;
- неизвестный kid — немедленное перечитывание JWKS, но не чаще раза в 30 с;
- exp/iat/iss/aud (свой id), сдвиг часов 60 с;
- заблокированный пользователь (событие platform.user.blocked) — 401 user_blocked сразу, а не через 15 минут;
- нет своих ролей — 403 no_product_roles; нет доступа к проекту — 403 no_project_access.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx
import jwt
from fastapi import HTTPException, Request, status

JWKS_TTL = 600
JWKS_MIN_REFETCH = 30
LEEWAY = 60
# Если в событии нет hold_until: TTL access-токена платформы по умолчанию (15 мин) + допуск часов.
BLOCK_HOLD_DEFAULT = 900 + LEEWAY


class JwksCache:
    def __init__(self, url: str, fetch=None) -> None:
        self.url = url
        self._fetch = fetch or self._http_fetch
        self._keys: dict[str, dict] = {}
        self._fetched_at = 0.0
        self._revoked: set[str] = set()
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
            return None if kid in self._revoked else self._keys.get(kid)

    def rotated(self, kid: str, revoked: list[str]) -> None:
        """Событие platform.keys.rotated (контракт v1.1, п. 6.2): отозванные kid больше не принимать,
        а если новый ключ ещё не в кэше — перечитать JWKS сейчас, без ограничения «не чаще раза в 30 с»."""
        with self._lock:
            self._revoked.update(revoked)
            for r in revoked:
                self._keys.pop(r, None)
            if revoked or kid not in self._keys:
                # Не 0.0: time.monotonic() отсчитывается от загрузки машины, и на свежей машине (раннер CI)
                # возраст «с нуля» меньше 30 с — перечитывания бы не было.
                self._fetched_at = float("-inf")


def _epoch(value) -> float | None:
    """Время из события: ISO 8601 с часовым поясом (или число секунд). Иначе — None."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.timestamp() if dt.tzinfo else None


class BlockedUsers:
    """Список заблокированных пользователей по событию platform.user.blocked (контракт v1.1, п. 6.5).

    Токен с sub из списка и iat <= blocked_at отвергается (401 user_blocked). Токены, выданные позже
    (пользователя разблокировали, и он вошёл снова), проходят. Запись не нужна после hold_until:
    к этому времени все токены, выданные до блокировки, истекли с учётом допуска часов.

    Список в памяти процесса: при перезапуске он пуст, и до 15 минут действует прежнее правило контракта.
    Продукту с несколькими экземплярами API нужен общий список (БД, Redis): платформа доставляет
    событие один раз на продукт, а не каждому экземпляру.
    """

    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._items: dict[str, tuple[int, float]] = {}  # sub -> (blocked_at, hold_until)
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        for sub in [s for s, (_, until) in self._items.items() if until < now]:
            del self._items[sub]

    def block(self, sub: str, blocked_at, hold_until=None) -> None:
        at = _epoch(blocked_at)
        if not sub or at is None:
            return
        at_s = math.floor(at)  # iat в токене — целые секунды
        until = _epoch(hold_until)
        until = until if until is not None else at_s + BLOCK_HOLD_DEFAULT
        with self._lock:
            prev = self._items.get(sub)
            # Повторная или запоздавшая доставка старого события не сдвигает момент назад.
            if prev is None or at_s > prev[0]:
                self._items[sub] = (at_s, max(until, prev[1]) if prev else until)
            self._purge(self._clock())

    def event(self, data: dict, envelope_time=None) -> None:
        """data события; без blocked_at — время конверта (продукт не должен падать на старом формате)."""
        at = data.get("blocked_at") or envelope_time
        self.block(str(data.get("sub") or ""), at, data.get("hold_until"))

    def is_blocked(self, sub: str, iat) -> bool:
        with self._lock:
            self._purge(self._clock())
            item = self._items.get(sub)
        if item is None:
            return False
        return not isinstance(iat, int | float) or iat <= item[0]

    def __len__(self) -> int:
        with self._lock:
            self._purge(self._clock())
            return len(self._items)


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


def verify_request(
    request: Request,
    product_id: str,
    jwks: JwksCache,
    issuer: str = "platform",
    blocked: BlockedUsers | None = None,
) -> Caller:
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
    # После подписи и сроков, до ролей: заблокированный получает 401 и в продукте, где ролей нет.
    if blocked is not None and blocked.is_blocked(str(claims["sub"]), claims.get("iat")):
        raise _unauth("user_blocked")
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

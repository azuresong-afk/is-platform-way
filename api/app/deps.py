"""Зависимости FastAPI: текущий пользователь по Bearer-токену, проверка администратора."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User
from .security import keys
from .users import can_receive_tokens


@dataclass
class Principal:
    user: User
    claims: dict

    @property
    def sub(self) -> str:
        return str(self.user.id)

    @property
    def name(self) -> str:
        return self.user.display_name or self.user.username

    @property
    def platform_token(self) -> bool:
        """Токен оболочки: aud — ровно ["platform"] (docs/SECURITY.md, п. 11)."""
        return is_platform_audience(self.claims.get("aud"))

    @property
    def admin(self) -> bool:
        """Права администратора платформы действуют только с токеном оболочки.

        Токен из sessionStorage (aud — продукты) доходит до бэкендов продуктов, поэтому
        администрирование и чтение чужих проектов по нему недоступны даже администратору.
        """
        return self.user.is_platform_admin and self.platform_token


PLATFORM_AUDIENCE = "platform"


def is_platform_audience(aud: object) -> bool:
    return aud == PLATFORM_AUDIENCE or aud == [PLATFORM_AUDIENCE]


def client_ip(request: Request) -> str:
    # Шлюз передаёт адрес клиента в X-Real-IP; напрямую API наружу не публикуется.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "")


def _unauthorized(detail: str = "not_authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _principal(request: Request, db: Session) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise _unauthorized()
    try:
        # Токен пользователя для продуктов (aud — продукты установки) и токен оболочки (aud=["platform"]).
        audience = [*get_settings().product_ids(), PLATFORM_AUDIENCE]
        claims = keys.verify(db, auth[7:].strip(), audience=audience)
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("invalid_token") from exc
    if claims.get("typ", "user") != "user":
        raise _unauthorized("invalid_token")
    try:
        user = db.get(User, uuid.UUID(claims["sub"]))
    except (ValueError, KeyError) as exc:
        raise _unauthorized("invalid_token") from exc
    # API самой платформы сверяется с БД на каждый запрос: блокировка действует сразу.
    if user is None or not can_receive_tokens(user):
        raise _unauthorized("user_blocked")
    return Principal(user=user, claims=claims)


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    p = _principal(request, db)
    # Временный пароль (задан администратором): до смены доступны только /me и /auth/password
    # (docs/SECURITY.md, п. 6). Сверка с БД: сброс пароля действует и на уже выданный токен.
    if p.user.password_temporary:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="password_change_required")
    return p


def principal_allow_temporary(request: Request, db: Session = Depends(get_db)) -> Principal:
    """Как current_principal, но пускает с временным паролем: профиль и смена пароля."""
    return _principal(request, db)


def require_admin(p: Principal = Depends(current_principal)) -> Principal:
    # 401, а не 403: оболочка в ответ берёт новый токен платформы (POST /auth/platform-token).
    if not p.platform_token:
        raise _unauthorized("platform_token_required")
    if not p.user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="platform_admin_required")
    return p

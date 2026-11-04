"""Зависимости FastAPI: текущий пользователь по Bearer-токену, проверка администратора."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

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


def client_ip(request: Request) -> str:
    # Шлюз передаёт адрес клиента в X-Real-IP; напрямую API наружу не публикуется.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "")


def _unauthorized(detail: str = "not_authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise _unauthorized()
    try:
        claims = keys.verify(db, auth[7:].strip(), audience="platform")
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


def require_admin(p: Principal = Depends(current_principal)) -> Principal:
    if not p.user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="platform_admin_required")
    return p

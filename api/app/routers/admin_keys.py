"""Администрирование: ключи подписи JWT и их ротация (план, шаг 3.3; контракт v1.1, п. 2.3).

Приватные ключи не покидают API: в ответах только kid, статус, сроки и открытая часть.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import aware, get_db, utcnow
from ..deps import Principal, client_ip, require_admin
from ..models import SigningKey
from ..security import keys

router = APIRouter(prefix="/admin/keys", tags=["admin: signing keys"])

# Продукты кэшируют JWKS на 10 минут (контракт v1, п. 2.1).
PRODUCT_JWKS_CACHE_SECONDS = 600


class KeyOut(BaseModel):
    kid: str
    status: Literal["next", "active", "retired", "revoked"]
    alg: str
    crv: str
    created_at: str
    activated_at: str | None
    retired_at: str | None
    in_jwks: bool
    # Для next — когда станет активным; для retired — до какого момента остаётся в JWKS.
    until: str | None


class Schedule(BaseModel):
    rotation_days: int
    next_lead_seconds: int
    jwks_retain_seconds: int
    access_ttl_seconds: int
    next_rotation_at: str | None
    scheduler_enabled: bool


class KeysOut(BaseModel):
    keys: list[KeyOut]
    schedule: Schedule
    warnings: list[str]


class RotateIn(BaseModel):
    # scheduled — опубликовать next, подписывать он начнёт через next_lead_seconds;
    # immediate — сменить сразу (например, при подозрении на утечку).
    mode: Literal["scheduled", "immediate"] = "scheduled"
    revoke_previous: bool = False


def _iso(dt) -> str | None:
    return aware(dt).isoformat() if dt else None


def _state(db: Session) -> dict:
    settings = get_settings()
    now = utcnow()
    retain = settings.jwks_retain_seconds
    out = []
    order = {"next": 0, "active": 1, "retired": 2, "revoked": 3}
    rows = sorted(
        db.scalars(select(SigningKey)),
        key=lambda k: (order.get(k.status, 9), -aware(k.created_at).timestamp()),
    )
    for k in rows:
        until = None
        if k.status == "next":
            until = keys.promote_at(k).isoformat()
        elif k.status == "retired" and k.retired_at:
            until = (aware(k.retired_at) + timedelta(seconds=retain)).isoformat()
        out.append(
            KeyOut(
                kid=k.kid,
                status=k.status,
                alg=k.public_jwk.get("alg", "EdDSA"),
                crv=k.public_jwk.get("crv", "Ed25519"),
                created_at=_iso(k.created_at),
                activated_at=_iso(k.activated_at),
                retired_at=_iso(k.retired_at),
                in_jwks=keys.in_jwks(k, now),
                until=until,
            )
        )
    due = keys.rotation_due_at(db)
    nxt = keys.next_key(db)
    next_rotation_at = keys.promote_at(nxt) if nxt else due
    warnings = []
    if retain < settings.access_ttl_seconds:
        warnings.append(
            f"JWKS_RETAIN_SECONDS ({retain} с) меньше срока access-токена ({settings.access_ttl_seconds} с): "
            "после смены ключа часть выданных токенов перестанет проверяться раньше срока."
        )
    if settings.key_next_lead_seconds < PRODUCT_JWKS_CACHE_SECONDS:
        warnings.append(
            f"KEY_NEXT_LEAD_SECONDS ({settings.key_next_lead_seconds} с) меньше кэша JWKS в продуктах "
            f"({PRODUCT_JWKS_CACHE_SECONDS} с): продукты будут перечитывать JWKS по неизвестному kid."
        )
    if not settings.background_tasks:
        warnings.append("Фоновые задачи выключены (BACKGROUND_TASKS=false): плановая ротация не выполняется.")
    return KeysOut(
        keys=out,
        schedule=Schedule(
            rotation_days=settings.key_rotation_days,
            next_lead_seconds=settings.key_next_lead_seconds,
            jwks_retain_seconds=retain,
            access_ttl_seconds=settings.access_ttl_seconds,
            next_rotation_at=_iso(next_rotation_at),
            scheduler_enabled=settings.background_tasks,
        ),
        warnings=warnings,
    ).model_dump(mode="json")


@router.get("", response_model=KeysOut)
def list_keys(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return _state(db)


@router.post("/rotate", response_model=KeysOut)
def rotate(
    body: RotateIn, request: Request, p: Principal = Depends(require_admin), db: Session = Depends(get_db)
):
    if body.revoke_previous and body.mode != "immediate":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Отозвать прежний ключ можно только при немедленной смене",
        )
    actor = (p.sub, p.name, client_ip(request))
    if body.mode == "scheduled":
        keys.schedule_next(db, actor)
    else:
        keys.rotate(db, actor, revoke_previous=body.revoke_previous)
    return _state(db)

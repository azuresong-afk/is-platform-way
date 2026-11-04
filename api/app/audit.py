"""Сводный журнал аудита: собственные действия платформы и события `audit.recorded` продуктов.

Одна таблица `audit_log` (append-only, триггер в миграции 0001) для всех источников:
поле `product` — `platform` для действий платформы, иначе id продукта-отправителя
из конверта события. Списка продуктов здесь нет: журнал принимает запись от любого
продукта, которому установка выдала секрет событий.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from . import events
from .models import AuditLog, Event

PLATFORM = "platform"
RESULTS = ("success", "failure", "denied")


def record(
    db: Session,
    *,
    action: str,
    actor_sub: str | None,
    actor_name: str = "",
    object: str = "",
    result: str = "success",
    ip: str = "",
    project_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Добавляет запись о действии платформы; коммит — на стороне вызывающего.

    Секреты (пароли, ключи) в details не передавать.
    """
    db.add(
        AuditLog(
            product=PLATFORM,
            actor_sub=actor_sub,
            actor_name=actor_name,
            action=action,
            object=object,
            result=result,
            ip=ip,
            project_id=project_id,
            details=details or {},
        )
    )


# --- приём audit.recorded от продуктов (контракт v1.1, п. 6.2) ------------------


class _Actor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str | None = None
    name: str = ""

    @field_validator("sub", mode="before")
    @classmethod
    def _sub(cls, v: Any) -> str | None:
        return None if v in (None, "") else str(v)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        return "" if v is None else str(v)


class AuditRecord(BaseModel):
    """`data` события audit.recorded. Лишние поля игнорируются, длинные строки обрезаются."""

    model_config = ConfigDict(extra="ignore")

    time: datetime | None = None
    actor: _Actor = Field(default_factory=_Actor)
    action: str = Field(min_length=1)
    object: str = ""
    result: Literal["success", "failure", "denied"] = "success"
    ip: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("object", "ip", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @field_validator("details", mode="before")
    @classmethod
    def _details(cls, v: Any) -> dict:
        return {} if v is None else v

    @field_validator("time")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("time с часовым поясом (UTC)")
        return v


def _cut(value: str, size: int) -> str:
    return value if len(value) <= size else value[: size - 1] + "…"


@events.on("audit.recorded")
def ingest(db: Session, event: Event) -> None:
    """Запись продукта → строка сводного журнала. Идемпотентно: event_id уникален,
    а повтор события отсекает шина ещё до вызова обработчика."""
    try:
        rec = AuditRecord.model_validate(event.data or {})
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
        raise events.Rejected(f"data audit.recorded: {errors}") from exc
    db.add(
        AuditLog(
            time=(rec.time or event.time).astimezone(UTC),
            product=event.source,
            actor_sub=_cut(rec.actor.sub, 100) if rec.actor.sub else None,
            actor_name=_cut(rec.actor.name, 200),
            action=_cut(rec.action, 100),
            object=_cut(rec.object, 300),
            result=rec.result,
            ip=_cut(rec.ip, 64),
            project_id=event.project_id,
            details=rec.details,
            event_id=event.id,
        )
    )


# --- выборка -------------------------------------------------------------------


class Filters(BaseModel):
    """Фильтры журнала. `action` — точное значение или префикс `auth.*`;
    `actor` — sub целиком или часть имени; `date_from` включительно, `date_to` — нет."""

    product: str | None = None
    actor: str | None = None
    project: uuid.UUID | None = None
    action: str | None = None
    result: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def query(f: Filters) -> Select:
    stmt = select(AuditLog)
    if f.product:
        stmt = stmt.where(AuditLog.product == f.product)
    if f.actor:
        stmt = stmt.where(
            or_(
                AuditLog.actor_sub == f.actor, AuditLog.actor_name.ilike(f"%{_escape(f.actor)}%", escape="\\")
            )
        )
    if f.project:
        stmt = stmt.where(AuditLog.project_id == f.project)
    if f.action:
        if f.action.endswith(".*"):
            stmt = stmt.where(AuditLog.action.like(f"{_escape(f.action[:-1])}%", escape="\\"))
        else:
            stmt = stmt.where(AuditLog.action == f.action)
    if f.result:
        stmt = stmt.where(AuditLog.result == f.result)
    if f.date_from:
        stmt = stmt.where(AuditLog.time >= f.date_from)
    if f.date_to:
        stmt = stmt.where(AuditLog.time < f.date_to)
    return stmt.order_by(AuditLog.time.desc(), AuditLog.id.desc())

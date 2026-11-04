"""Запись собственных действий платформы в сводный журнал аудита."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


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
    """Добавляет запись; коммит — на стороне вызывающего.

    Секреты (пароли, ключи) в details не передавать.
    """
    db.add(
        AuditLog(
            product="platform",
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

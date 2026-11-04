"""Серверная пагинация: limit/offset, всего — заголовок X-Total-Count."""

from __future__ import annotations

from typing import Any

from fastapi import Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class Page:
    def __init__(
        self,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> None:
        self.limit = limit
        self.offset = offset

    def apply(self, db: Session, stmt: Select, response: Response) -> list[Any]:
        total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        response.headers["X-Total-Count"] = str(total)
        return list(db.scalars(stmt.limit(self.limit).offset(self.offset)))

"""Сводный журнал аудита: просмотр с фильтрами и выгрузка CSV/JSON (только администратор)."""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import aware, get_db, session_scope
from ..deps import Principal, client_ip, require_admin
from ..models import AuditLog, Product, Project
from ..pagination import Page

router = APIRouter(tags=["audit"])

EXPORT_MAX = 100_000
FACETS_MAX = 1000
PLATFORM_TITLE = "Платформа"


class AuditOut(BaseModel):
    id: int
    time: datetime
    product: str
    product_title: str
    actor_sub: str | None
    actor_name: str
    action: str
    object: str
    project_id: uuid.UUID | None
    project_name: str | None
    result: str
    ip: str
    details: dict[str, Any]
    event_id: uuid.UUID | None
    sod: bool


class Facet(BaseModel):
    id: str
    title: str


class Facets(BaseModel):
    products: list[Facet]
    projects: list[Facet]
    actions: list[str]


def filters(
    product: str | None = Query(None, max_length=20),
    actor: str | None = Query(None, max_length=200, description="sub целиком или часть имени"),
    project: uuid.UUID | None = None,
    action: str | None = Query(None, max_length=100, description="точное значение или префикс вида auth.*"),
    result: Literal["success", "failure", "denied"] | None = None,
    date_from: datetime | None = Query(None, alias="from", description="включительно"),
    date_to: datetime | None = Query(None, alias="to", description="не включительно"),
    sod: bool | None = Query(None, description="true — только действия в обход разделения обязанностей"),
) -> audit.Filters:
    return audit.Filters(
        product=product or None,
        actor=(actor or "").strip() or None,
        project=project,
        action=action or None,
        result=result,
        date_from=_utc(date_from),
        date_to=_utc(date_to),
        sod=sod,
    )


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _titles(db: Session) -> dict[str, str]:
    out = {p.id: p.title for p in db.scalars(select(Product))}
    out[audit.PLATFORM] = PLATFORM_TITLE
    return out


def _project_names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(ids))).all())


def _out(a: AuditLog, titles: dict[str, str], names: dict[uuid.UUID, str]) -> AuditOut:
    return AuditOut(
        id=a.id,
        time=aware(a.time),
        product=a.product,
        product_title=titles.get(a.product, a.product),
        actor_sub=a.actor_sub,
        actor_name=a.actor_name,
        action=a.action,
        object=a.object,
        project_id=a.project_id,
        project_name=names.get(a.project_id) if a.project_id else None,
        result=a.result,
        ip=a.ip,
        details=a.details or {},
        event_id=a.event_id,
        sod=bool(a.sod),
    )


@router.get("/audit", response_model=list[AuditOut])
def list_audit(
    response: Response,
    f: audit.Filters = Depends(filters),
    page: Page = Depends(),
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items = page.apply(db, audit.query(f), response)
    names = _project_names(db, {a.project_id for a in items if a.project_id})
    titles = _titles(db)
    return [_out(a, titles, names) for a in items]


@router.get("/audit/facets", response_model=Facets)
def facets(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Значения для фильтров — только те, что есть в журнале: список продуктов не зашит."""
    titles = _titles(db)
    products = sorted(db.scalars(select(AuditLog.product).distinct()))
    # платформа первой, продукты — по названию
    products.sort(key=lambda p: (p != audit.PLATFORM, titles.get(p, p).lower()))
    project_ids = set(
        db.scalars(
            select(AuditLog.project_id).where(AuditLog.project_id.is_not(None)).distinct().limit(FACETS_MAX)
        )
    )
    names = _project_names(db, project_ids)
    projects = sorted(
        (Facet(id=str(pid), title=names.get(pid, str(pid))) for pid in project_ids),
        key=lambda x: x.title.lower(),
    )
    actions = list(db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action).limit(FACETS_MAX)))
    return Facets(
        products=[Facet(id=p, title=titles.get(p, p)) for p in products], projects=projects, actions=actions
    )


# --- выгрузка ------------------------------------------------------------------

COLUMNS = (
    "id",
    "time",
    "product",
    "actor_sub",
    "actor_name",
    "action",
    "object",
    "project_id",
    "project_name",
    "result",
    "ip",
    "details",
    "event_id",
    "sod",
)


def _row(o: AuditOut) -> dict[str, Any]:
    d = o.model_dump(mode="json")
    d.pop("product_title")
    return d


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = str(value)
    # защита от формул при открытии в Excel/LibreOffice: данные продуктов — недоверенные
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text


def _stream(f: audit.Filters, fmt: str) -> Iterator[str]:
    db = session_scope()
    try:
        titles = _titles(db)
        result = db.scalars(audit.query(f).limit(EXPORT_MAX).execution_options(yield_per=1000))
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\r\n")
            buf.write("﻿")  # BOM: Excel открывает UTF-8 с кириллицей без порчи
            w.writerow(COLUMNS)
            yield buf.getvalue()
            for chunk in result.partitions():
                buf.seek(0)
                buf.truncate()
                names = _project_names(db, {a.project_id for a in chunk if a.project_id})
                for a in chunk:
                    row = _row(_out(a, titles, names))
                    w.writerow([_cell(row[c]) for c in COLUMNS])
                yield buf.getvalue()
        else:
            yield "["
            first = True
            for chunk in result.partitions():
                names = _project_names(db, {a.project_id for a in chunk if a.project_id})
                parts = []
                for a in chunk:
                    parts.append(
                        ("" if first else ",")
                        + "\n"
                        + json.dumps(_row(_out(a, titles, names)), ensure_ascii=False)
                    )
                    first = False
                yield "".join(parts)
            yield "\n]\n"
    finally:
        db.close()


@router.get("/audit/export")
def export(
    request: Request,
    format: Literal["csv", "json"] = "csv",
    f: audit.Filters = Depends(filters),
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(audit.query(f).order_by(None).subquery())) or 0
    if total > EXPORT_MAX:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Записей {total}, выгрузка — не больше {EXPORT_MAX}. Сузьте фильтр, например по периоду.",
        )
    # выгрузка журнала — тоже действие, которое должно остаться в журнале
    audit.record(
        db,
        action="audit.export",
        actor_sub=p.sub,
        actor_name=p.name,
        object="audit_log",
        ip=client_ip(request),
        details={"format": format, "rows": total, "filters": f.model_dump(mode="json", exclude_none=True)},
    )
    db.commit()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    media = "text/csv; charset=utf-8" if format == "csv" else "application/json; charset=utf-8"
    return StreamingResponse(
        _stream(f, format),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="audit-{stamp}.{format}"',
            "X-Total-Count": str(total),
            "Cache-Control": "no-store",
        },
    )

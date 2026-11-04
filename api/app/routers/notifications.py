"""Центр уведомлений: список, счётчик непрочитанных, отметка прочитанным.

Только свои уведомления текущего пользователя (Bearer платформы). Вызывается из
оболочки и из интерфейса любого продукта (колокольчик в строке вкладок @platform/ui).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import notifications  # noqa: F401 — регистрирует обработчик событий
from ..db import aware, get_db, utcnow
from ..deps import Principal, current_principal
from ..models import Notification, Product
from ..pagination import Page

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    product: str
    product_title: str
    event_type: str
    project_id: uuid.UUID | None
    title: str
    link: str | None
    created_at: str
    read_at: str | None


class UnreadOut(BaseModel):
    unread: int


class ReadAllIn(BaseModel):
    product: str | None = None


class ReadAllOut(BaseModel):
    updated: int


def _titles(db: Session) -> dict[str, str]:
    titles = {p.id: p.title for p in db.scalars(select(Product))}
    titles.setdefault("platform", "Платформа")
    return titles


def _out(n: Notification, titles: dict[str, str]) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        product=n.product,
        product_title=titles.get(n.product, n.product),
        event_type=n.event_type,
        project_id=n.project_id,
        title=n.title,
        link=n.link,
        created_at=aware(n.created_at).isoformat(),
        read_at=aware(n.read_at).isoformat() if n.read_at else None,
    )


def _unread(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    response: Response,
    unread: bool = Query(False, description="только непрочитанные"),
    product: str | None = Query(None, max_length=20),
    project: uuid.UUID | None = Query(None),
    page: Page = Depends(),
    p: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    """Свои уведомления, новые сверху. Всего — X-Total-Count, непрочитанных — X-Unread-Count."""
    stmt = select(Notification).where(Notification.user_id == p.user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    if product:
        stmt = stmt.where(Notification.product == product)
    if project:
        stmt = stmt.where(Notification.project_id == project)
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
    items = page.apply(db, stmt, response)
    response.headers["X-Unread-Count"] = str(_unread(db, p.user.id))
    titles = _titles(db)
    return [_out(n, titles) for n in items]


@router.get("/unread-count", response_model=UnreadOut)
def unread_count(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    """Счётчик для колокольчика; дешёвый запрос для фонового опроса."""
    return UnreadOut(unread=_unread(db, p.user.id))


def _own(db: Session, p: Principal, notification_id: uuid.UUID) -> Notification:
    n = db.get(Notification, notification_id)
    # чужое уведомление неотличимо от несуществующего
    if n is None or n.user_id != p.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    return n


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    n = _own(db, p, notification_id)
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return _out(n, _titles(db))


@router.post("/{notification_id}/unread", response_model=NotificationOut)
def mark_unread(
    notification_id: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    n = _own(db, p, notification_id)
    if n.read_at is not None:
        n.read_at = None
        db.commit()
    return _out(n, _titles(db))


@router.post("/read-all", response_model=ReadAllOut)
def mark_all_read(
    body: ReadAllIn | None = None, p: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    """Отметить прочитанными все свои (или только одного продукта)."""
    stmt = (
        update(Notification)
        .where(Notification.user_id == p.user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    if body and body.product:
        stmt = stmt.where(Notification.product == body.product)
    updated = db.execute(stmt).rowcount or 0
    db.commit()
    return ReadAllOut(updated=updated)

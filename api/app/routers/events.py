"""Шина событий: приём от продуктов (HMAC) и администрирование доставки."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, events
from ..db import aware, get_db
from ..deps import Principal, client_ip, require_admin
from ..models import Delivery, Event, Subscription
from ..pagination import Page

router = APIRouter(tags=["events"])

MAX_BODY = 5 * 1024 * 1024


@router.post(
    "/events",
    status_code=202,
    responses={
        200: {"description": "Дубликат — уже принято"},
        207: {"description": "Пачка: статус по каждому id"},
        401: {"description": "Подпись"},
        422: {"description": "Конверт не по схеме"},
    },
)
async def receive(request: Request, db: Session = Depends(get_db)):
    """Приём событий от продуктов (контракт v1.1, п. 6.1)."""
    product_id = request.headers.get("x-platform-product", "")
    body = await request.body()
    if len(body) > MAX_BODY:
        return JSONResponse({"detail": "too_large"}, status_code=413)
    if not events.check_signature(product_id, body, request.headers.get("x-signature", "")):
        audit.record(
            db,
            action="event.receive",
            actor_sub=None,
            actor_name=f"product:{product_id[:20]}",
            result="denied",
            ip=client_ip(request),
            details={"reason": "bad_signature"},
        )
        db.commit()
        return JSONResponse({"detail": "bad_signature"}, status_code=401)
    try:
        payload = json.loads(body)
    except ValueError:
        return JSONResponse({"detail": "invalid_json"}, status_code=422)

    if isinstance(payload, list):
        if not payload or len(payload) > events.MAX_BATCH:
            return JSONResponse({"detail": f"batch: от 1 до {events.MAX_BATCH} событий"}, status_code=422)
        results = []
        for raw in payload:
            code, out = events.accept_one(db, product_id, raw)
            rid = raw.get("id") if isinstance(raw, dict) else None
            results.append(
                {"id": out.get("id", rid), "status": code, **{k: v for k, v in out.items() if k != "id"}}
            )
        db.commit()
        events.wake_dispatcher()
        return JSONResponse({"results": results}, status_code=207)

    header_id = request.headers.get("x-event-id")
    if header_id and isinstance(payload, dict) and str(payload.get("id")) != header_id:
        return JSONResponse({"detail": "event_id_mismatch"}, status_code=422)
    code, out = events.accept_one(db, product_id, payload)
    if code == 422:
        db.rollback()
        return JSONResponse(out, status_code=422)
    db.commit()
    if code == 202:
        events.wake_dispatcher()
    return JSONResponse(out, status_code=code)


# --- администрирование ------------------------------------------------------


class DeliveryOut(BaseModel):
    id: uuid.UUID
    subscription_id: uuid.UUID
    product_id: str
    status: str
    attempts: int
    next_attempt_at: str | None
    last_error: str | None
    last_status_code: int | None
    delivered_at: str | None


class EventOut(BaseModel):
    id: uuid.UUID
    type: str
    source: str
    time: str
    received_at: str
    project_id: uuid.UUID | None
    subject: str
    # ok | pending | failed | dead | none — худший статус доставок
    delivery: str
    deliveries_total: int


class EventDetail(EventOut):
    data: dict
    notify: dict | None
    deliveries: list[DeliveryOut]


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    product_id: str
    webhook_path: str
    types: list[str]
    is_active: bool
    pending: int
    dead: int


class SubscriptionPatch(BaseModel):
    is_active: bool


class RedeliverIn(BaseModel):
    subscription_id: uuid.UUID | None = None


SEVERITY = {"dead": 4, "failed": 3, "pending": 2, "ok": 1}


def _iso(dt: datetime | None) -> str | None:
    return aware(dt).isoformat() if dt else None


def _delivery_out(d: Delivery, product: str) -> DeliveryOut:
    return DeliveryOut(
        id=d.id,
        subscription_id=d.subscription_id,
        product_id=product,
        status=d.status,
        attempts=d.attempts,
        next_attempt_at=_iso(d.next_attempt_at),
        last_error=d.last_error,
        last_status_code=d.last_status_code,
        delivered_at=_iso(d.delivered_at),
    )


def _event_out(e: Event, statuses: list[str]) -> dict:
    worst = max(statuses, key=lambda s: SEVERITY.get(s, 0)) if statuses else "none"
    return EventOut(
        id=e.id,
        type=e.type,
        source=e.source,
        time=_iso(e.time) or "",
        received_at=_iso(e.received_at) or "",
        project_id=e.project_id,
        subject=e.subject,
        delivery=worst,
        deliveries_total=len(statuses),
    ).model_dump(mode="json")


@router.get("/admin/events", response_model=list[EventOut])
def list_events(
    response: Response,
    type: str | None = Query(None, max_length=100),
    source: str | None = Query(None, max_length=20),
    project_id: uuid.UUID | None = None,
    delivery: str | None = Query(None, pattern="^(problems|pending|failed|dead|ok)$"),
    page: Page = Depends(),
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(Event)
    if type:
        stmt = stmt.where(Event.type.startswith(type.removesuffix("*")))
    if source:
        stmt = stmt.where(Event.source == source)
    if project_id:
        stmt = stmt.where(Event.project_id == project_id)
    if delivery:
        wanted = ("failed", "dead") if delivery == "problems" else (delivery,)
        stmt = stmt.where(Event.id.in_(select(Delivery.event_id).where(Delivery.status.in_(wanted))))
    rows = page.apply(db, stmt.order_by(Event.received_at.desc()), response)
    statuses: dict[uuid.UUID, list[str]] = {}
    if rows:
        for eid, st in db.execute(
            select(Delivery.event_id, Delivery.status).where(Delivery.event_id.in_([e.id for e in rows]))
        ):
            statuses.setdefault(eid, []).append(st)
    return [_event_out(e, statuses.get(e.id, [])) for e in rows]


@router.get("/admin/events/{event_id}", response_model=EventDetail)
def get_event(event_id: uuid.UUID, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    e = db.get(Event, event_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Событие не найдено")
    rows = db.execute(
        select(Delivery, Subscription.product_id)
        .join(Subscription, Subscription.id == Delivery.subscription_id)
        .where(Delivery.event_id == e.id)
        .order_by(Subscription.product_id)
    ).all()
    base = _event_out(e, [d.status for d, _ in rows])
    return {
        **base,
        "data": e.data,
        "notify": e.notify,
        "deliveries": [_delivery_out(d, pid).model_dump(mode="json") for d, pid in rows],
    }


@router.post("/admin/events/{event_id}/redeliver", response_model=EventDetail)
def redeliver(
    event_id: uuid.UUID,
    request: Request,
    body: RedeliverIn | None = None,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    e = db.get(Event, event_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Событие не найдено")
    sid = body.subscription_id if body else None
    n = events.redeliver(db, e.id, sid)
    if n == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="У события нет доставок")
    audit.record(
        db,
        action="event.redeliver",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"event/{e.id}",
        project_id=e.project_id,
        ip=client_ip(request),
        details={"type": e.type, "deliveries": n},
    )
    db.commit()
    events.wake_dispatcher()
    return get_event(e.id, p, db)


def _subscription_out(db: Session, s: Subscription) -> SubscriptionOut:
    counts = dict(
        db.execute(
            select(Delivery.status, func.count())
            .where(Delivery.subscription_id == s.id, Delivery.status.in_(("pending", "failed", "dead")))
            .group_by(Delivery.status)
        ).all()
    )
    return SubscriptionOut(
        id=s.id,
        product_id=s.product_id,
        webhook_path=s.webhook_path,
        types=list(s.types or []),
        is_active=s.is_active,
        pending=counts.get("pending", 0) + counts.get("failed", 0),
        dead=counts.get("dead", 0),
    )


@router.get("/admin/subscriptions", response_model=list[SubscriptionOut])
def list_subscriptions(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return [
        _subscription_out(db, s) for s in db.scalars(select(Subscription).order_by(Subscription.product_id))
    ]


@router.patch("/admin/subscriptions/{sid}", response_model=SubscriptionOut)
def patch_subscription(
    sid: uuid.UUID,
    body: SubscriptionPatch,
    request: Request,
    p: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    s = db.get(Subscription, sid)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Подписка не найдена")
    s.is_active = body.is_active
    audit.record(
        db,
        action="subscription.update",
        actor_sub=p.sub,
        actor_name=p.name,
        object=f"subscription/{s.product_id}",
        ip=client_ip(request),
        details={"is_active": body.is_active},
    )
    db.commit()
    return _subscription_out(db, s)

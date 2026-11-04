"""Шина событий (контракт v1.1, п. 6): приём, подписки, доставка с повторами.

Ничего не знает о конкретных продуктах: источник — любой продукт установки с
секретом событий, подписки — из манифестов (events.webhook, events.subscribe).

Расширение для следующих шагов (реестр активов, сводный аудит, уведомления):
обработчик регистрируется через `on("audit.recorded")(func)` / `on("scanner.asset.*")`
и вызывается при приёме события в той же транзакции. Исключение в обработчике
отменяет приём (продукт получит 5xx и повторит доставку); `Rejected` — отказ по
содержимому: продукт получит 422 и повторять не будет.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import aware, session_scope, utcnow
from .models import Delivery, Event, Product, Subscription

log = logging.getLogger(__name__)

PLATFORM = "platform"
MAX_BATCH = 100
# Повторы после неудачной попытки: 1, 5, 15, 60 минут; после последней — dead.
RETRY_MINUTES = (1, 5, 15, 60)
TYPE_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")

Handler = Callable[[Session, Event], None]


class Rejected(ValueError):
    """Обработчик отвергает событие по содержимому: приём отменяется, ответ 422."""


_handlers: list[tuple[str, Handler]] = []


def on(pattern: str) -> Callable[[Handler], Handler]:
    """Регистрирует обработчик принятых событий; шаблон как в events.subscribe."""

    def deco(func: Handler) -> Handler:
        _handlers.append((pattern, func))
        return func

    return deco


def matches(pattern: str, event_type: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


# --- конверт ------------------------------------------------------------------


class Notify(BaseModel):
    users: list[str] = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    link: str | None = Field(default=None, max_length=500)

    @field_validator("link")
    @classmethod
    def _relative(cls, v: str | None) -> str | None:
        # только относительный путь того же origin (контракт v1.1, п. 6.3)
        if v is not None and (not v.startswith("/") or v.startswith("//") or "\\" in v):
            raise ValueError("link должен быть относительным путём")
        return v


class Envelope(BaseModel):
    id: uuid.UUID
    type: str = Field(max_length=100)
    source: str = Field(max_length=20)
    time: datetime
    project_id: uuid.UUID | None = None
    subject: str = Field(default="", max_length=300)
    data: dict[str, Any] = Field(default_factory=dict)
    notify: Notify | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if not TYPE_RE.match(v):
            raise ValueError("type вида <product>.<object>.<action>")
        return v

    @field_validator("time")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("time с часовым поясом (UTC)")
        return v

    @model_validator(mode="after")
    def _type_of_source(self) -> Envelope:
        if self.type != "audit.recorded" and not self.type.startswith(f"{self.source}."):
            raise ValueError("type должен начинаться с <source>.")
        return self


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def product_secret(product_id: str) -> str | None:
    for p in get_settings().products():
        if p.id == product_id:
            return p.events_secret or None
    return None


def check_signature(product_id: str, body: bytes, signature: str) -> bool:
    secret = product_secret(product_id)
    if not secret:
        return False
    return hmac.compare_digest(sign(secret, body), signature or "")


# --- приём --------------------------------------------------------------------


def _schedule(db: Session, event: Event) -> int:
    count = 0
    subs = db.scalars(select(Subscription).where(Subscription.is_active.is_(True)))
    enabled = {p.id for p in db.scalars(select(Product).where(Product.enabled.is_(True)))}
    for sub in subs:
        # себе продукт событие не получает; выключенному продукту — тоже
        if sub.product_id == event.source or sub.product_id not in enabled or not sub.webhook_path:
            continue
        if any(matches(t, event.type) for t in sub.types or []):
            db.add(Delivery(event_id=event.id, subscription_id=sub.id, next_attempt_at=utcnow()))
            count += 1
    return count


def store(db: Session, env: Envelope) -> bool:
    """Сохраняет событие, планирует доставку, вызывает обработчики. False — дубликат.

    Коммит — на стороне вызывающего.
    """
    if db.get(Event, env.id) is not None:
        return False
    event = Event(
        id=env.id,
        type=env.type,
        source=env.source,
        time=env.time,
        project_id=env.project_id,
        subject=env.subject,
        data=env.data,
        notify=env.notify.model_dump() if env.notify else None,
    )
    db.add(event)
    db.flush()
    _schedule(db, event)
    for pattern, handler in _handlers:
        if matches(pattern, event.type):
            handler(db, event)
    return True


def accept_one(db: Session, product_id: str, raw: Any) -> tuple[int, dict]:
    """Принимает один конверт; возвращает (HTTP-статус, тело ответа) по контракту п. 6.1."""
    try:
        env = Envelope.model_validate(raw)
    except ValidationError as exc:
        return 422, {"detail": "invalid_envelope", "errors": _errors(exc)}
    if env.source != product_id:
        return 422, {"detail": "source_mismatch"}
    try:
        with db.begin_nested():
            created = store(db, env)
    except Rejected as exc:
        return 422, {"id": str(env.id), "detail": "rejected", "errors": [str(exc)]}
    except IntegrityError:
        created = False  # параллельный приём того же id
    if not created:
        return 200, {"id": str(env.id), "duplicate": True}
    return 202, {"id": str(env.id), "accepted": True}


def _errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]]


def publish(
    db: Session,
    event_type: str,
    data: dict,
    *,
    project_id: uuid.UUID | None = None,
    subject: str = "",
    notify: dict | None = None,
) -> None:
    """Собственное событие платформы (platform.*). Коммит — на стороне вызывающего.

    notify — как в конверте продукта: {"users": [sub, …], "title": "…", "link": "/…"}.
    """
    store(
        db,
        Envelope(
            id=uuid.uuid4(),
            type=event_type,
            source=PLATFORM,
            time=utcnow(),
            project_id=project_id,
            subject=subject,
            data=data,
            notify=Notify.model_validate(notify) if notify else None,
        ),
    )
    wake_dispatcher()


# --- подписки -----------------------------------------------------------------


def _valid_pattern(t: str) -> bool:
    if t == "*" or TYPE_RE.match(t):
        return True
    return t.endswith(".*") and re.match(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$", t[:-2]) is not None


def sync_subscription(db: Session, prod: Product) -> None:
    """Подписка продукта из манифеста. Флаг is_active не трогается — его меняет администратор."""
    ev = (prod.manifest or {}).get("events") or {}
    webhook = ev.get("webhook") if isinstance(ev.get("webhook"), str) else ""
    types = [t for t in ev.get("subscribe") or [] if isinstance(t, str) and _valid_pattern(t)]
    if webhook and not webhook.startswith("/"):
        webhook = ""
    sub = db.scalar(select(Subscription).where(Subscription.product_id == prod.id))
    if sub is None:
        if not webhook:
            return
        sub = Subscription(product_id=prod.id, webhook_path=webhook, types=types)
        db.add(sub)
        return
    if sub.webhook_path != webhook or list(sub.types or []) != types:
        sub.webhook_path = webhook
        sub.types = types


# --- доставка -----------------------------------------------------------------


def _next_retry(attempts: int) -> datetime | None:
    if attempts > len(RETRY_MINUTES):
        return None
    return utcnow() + timedelta(minutes=RETRY_MINUTES[attempts - 1])


def deliver(db: Session, d: Delivery, client: httpx.Client) -> None:
    """Одна попытка доставки. Коммит — на стороне вызывающего."""
    event = db.get(Event, d.event_id)
    sub = db.get(Subscription, d.subscription_id)
    prod = db.get(Product, sub.product_id) if sub else None
    d.attempts += 1
    error: str | None = None
    code: int | None = None
    secret = product_secret(sub.product_id) if sub else None
    if event is None or sub is None or prod is None or not prod.enabled or not prod.internal_url:
        error = "продукт не подключён"
    elif not secret:
        error = "у продукта не задан секрет событий"
    else:
        body = json.dumps(envelope_of(event), ensure_ascii=False, separators=(",", ":")).encode()
        try:
            r = client.post(
                prod.internal_url + sub.webhook_path,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Platform-Product": PLATFORM,
                    "X-Event-Id": str(event.id),
                    "X-Signature": sign(secret, body),
                },
            )
            code = r.status_code
            if not 200 <= code < 300:
                error = f"HTTP {code}: {r.text[:200]}"
        except httpx.HTTPError as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
    d.last_status_code = code
    if error is None:
        d.status = "ok"
        d.delivered_at = utcnow()
        d.next_attempt_at = None
        d.last_error = None
        return
    d.last_error = error
    nxt = _next_retry(d.attempts)
    d.status = "failed" if nxt else "dead"
    d.next_attempt_at = nxt


def envelope_of(event: Event) -> dict:
    out = {
        "id": str(event.id),
        "type": event.type,
        "source": event.source,
        "time": aware(event.time).astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "project_id": str(event.project_id) if event.project_id else None,
        "subject": event.subject,
        "data": event.data,
    }
    if event.notify:
        out["notify"] = event.notify
    return out


def due(db: Session, limit: int = 50) -> list[Delivery]:
    q = (
        select(Delivery)
        .where(Delivery.status.in_(("pending", "failed")), Delivery.next_attempt_at <= utcnow())
        .order_by(Delivery.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(db.scalars(q))


def run_due(client: httpx.Client | None = None, limit: int = 50) -> int:
    """Доставляет всё, чему пришёл срок. Возвращает число попыток."""
    own = client is None
    client = client or httpx.Client(timeout=10.0)
    done = 0
    try:
        with session_scope() as db:
            for d in due(db, limit):
                try:
                    deliver(db, d, client)
                except Exception as exc:  # noqa: BLE001 - одна доставка не должна ронять очередь
                    log.exception("Ошибка доставки %s", d.id)
                    d.last_error = f"внутренняя ошибка: {type(exc).__name__}"
                    nxt = _next_retry(d.attempts)
                    d.status, d.next_attempt_at = ("failed", nxt) if nxt else ("dead", None)
                done += 1
            db.commit()
    finally:
        if own:
            client.close()
    return done


def redeliver(db: Session, event_id: uuid.UUID, subscription_id: uuid.UUID | None = None) -> int:
    """Ручная повторная отправка: доставки снова в очередь с полным циклом повторов."""
    q = select(Delivery).where(Delivery.event_id == event_id)
    if subscription_id:
        q = q.where(Delivery.subscription_id == subscription_id)
    items = list(db.scalars(q))
    for d in items:
        d.status = "pending"
        d.attempts = 0
        d.next_attempt_at = utcnow()
        d.last_error = None
    return len(items)


_wake = threading.Event()


def wake_dispatcher() -> None:
    _wake.set()


class Dispatcher(threading.Thread):
    """Фоновая доставка. Состояние — в БД, поэтому рестарт не теряет очередь."""

    def __init__(self, interval: float = 5.0) -> None:
        super().__init__(name="event-dispatcher", daemon=True)
        self.interval = interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                while run_due() and not self.stop_event.is_set():
                    pass
            except Exception:  # noqa: BLE001 - фоновый цикл не должен падать
                log.exception("Ошибка цикла доставки событий")
            _wake.wait(self.interval)
            _wake.clear()

    def stop(self) -> None:
        self.stop_event.set()
        _wake.set()

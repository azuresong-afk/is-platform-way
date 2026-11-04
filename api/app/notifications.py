"""Центр уведомлений (шаг 3.2): уведомления адресатам из поля `notify` событий.

Ничего не знает о конкретных продуктах и типах событий: любой продукт установки
(и сама платформа через events.publish(..., notify=...)) кладёт уведомление,
указав в конверте `notify.users` — sub адресатов (id пользователя платформы).
Платформа не угадывает адресатов по типу события (roadmap, раздел 6).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events
from .models import Event, Notification, User

log = logging.getLogger(__name__)


def _subs(raw: list) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for s in raw:
        try:
            u = uuid.UUID(str(s))
        except ValueError:
            continue
        if u not in out:
            out.append(u)
    return out


@events.on("*")
def from_event(db: Session, event: Event) -> int:
    """Кладёт уведомление каждому существующему адресату. Неизвестные sub пропускаются."""
    notify = event.notify
    if not notify:
        return 0
    wanted = _subs(notify.get("users") or [])
    if not wanted:
        return 0
    known = set(db.scalars(select(User.id).where(User.id.in_(wanted))))
    skipped = len(wanted) - len(known)
    if skipped:
        log.info("событие %s: %d адресат(ов) notify не найдено", event.id, skipped)
    for user_id in wanted:
        if user_id not in known:
            continue
        db.add(
            Notification(
                user_id=user_id,
                event_id=event.id,
                product=event.source,
                event_type=event.type,
                project_id=event.project_id,
                title=notify["title"],
                link=notify.get("link"),
                created_at=event.received_at,
            )
        )
    return len(known)

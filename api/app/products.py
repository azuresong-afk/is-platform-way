"""Реестр продуктов: какие продукты есть в установке, их манифесты и состояние.

Продукт есть в установке, если его id указан в PLATFORM_PRODUCTS и задан <ID>_API_UPSTREAM.
Пока платформа не получила настоящий манифест (продукт ещё не поднялся), используется
встроенный манифест известного продукта или минимальная заглушка (placeholder_manifest).
В этом модуле нет списков продуктов: всё берётся из окружения и манифестов.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .builtin_manifests import BUILTIN_MANIFESTS
from .config import get_settings
from .db import session_scope, utcnow
from .models import Product

log = logging.getLogger(__name__)


def placeholder_manifest(pid: str) -> dict[str, Any]:
    """Манифест до первого ответа продукта: встроенный, если он есть, иначе минимальный."""
    builtin = BUILTIN_MANIFESTS.get(pid)
    if builtin is not None:
        return dict(builtin)
    return {
        "id": pid,
        "title": pid,
        "subtitle": "",
        "icon": "box",
        "base_path": f"/{pid}/",
        "api_base": f"/api/{pid}/",
        "version": "",
        # Ролей нет, пока продукт не отдал манифест: выдать их заранее нельзя.
        "roles": {},
        "admin_roles": [],
        "nav": [],
        "search_url": f"/api/{pid}/search",
        "health_url": f"/api/{pid}/health/ready",
        "summary_url": f"/api/{pid}/summary",
    }


def sync_from_settings(db: Session) -> None:
    """Приводит таблицу products к переменным окружения."""
    configured = {p.id: p for p in get_settings().products()}
    existing = {p.id: p for p in db.scalars(select(Product))}
    for pid, cfg in configured.items():
        prod = existing.get(pid)
        if prod is None:
            manifest = placeholder_manifest(pid)
            prod = Product(id=pid, title=manifest["title"], manifest=manifest)
            db.add(prod)
        prod.internal_url = cfg.api_upstream
        prod.enabled = True
    for pid, prod in existing.items():
        if pid not in configured:
            prod.enabled = False
    db.commit()


def order_key(prod: Product, positions: dict[str, int]) -> tuple[float, int, str]:
    """Порядок вкладок: число "order" из манифеста, иначе место id в PLATFORM_PRODUCTS."""
    pos = positions.get(prod.id, len(positions))
    order = (prod.manifest or {}).get("order")
    if isinstance(order, bool) or not isinstance(order, int | float):
        order = pos
    return (float(order), pos, prod.id)


def product_positions() -> dict[str, int]:
    return {p.id: p.position for p in get_settings().products()}


def enabled_products(db: Session) -> list[Product]:
    items = list(db.scalars(select(Product).where(Product.enabled.is_(True))))
    positions = product_positions()
    return sorted(items, key=lambda p: order_key(p, positions))


def enabled_ids(db: Session) -> list[str]:
    return [p.id for p in enabled_products(db)]


def product_roles(db: Session, product_id: str) -> dict[str, str]:
    prod = db.get(Product, product_id)
    if prod is None or not prod.enabled:
        return {}
    return dict(prod.manifest.get("roles") or {})


def _valid_manifest(pid: str, data: Any) -> bool:
    return isinstance(data, dict) and data.get("id") == pid and isinstance(data.get("roles"), dict)


def refresh_product(db: Session, prod: Product, client: httpx.Client | None = None) -> None:
    """Читает /manifest и /health/ready по внутреннему адресу (контракт v1.1, п. 5.2)."""
    own = client is None
    client = client or httpx.Client(timeout=5.0)
    now = utcnow()
    try:
        try:
            r = client.get(f"{prod.internal_url}/manifest")
            r.raise_for_status()
            data = r.json()
            if _valid_manifest(prod.id, data):
                prod.manifest = data
                prod.title = data.get("title") or prod.title
                prod.version = str(data.get("version") or "")
                prod.manifest_fetched_at = now
                prod.last_error = None
                from . import events  # noqa: PLC0415 - избегаем цикла импортов

                events.sync_subscription(db, prod)
            else:
                prod.last_error = "манифест не соответствует контракту"
        except (httpx.HTTPError, ValueError) as exc:
            prod.last_error = f"манифест: {exc}"[:500]
        try:
            r = client.get(f"{prod.internal_url}/health/ready")
            prod.health = "ok" if r.status_code == 200 else "down"
        except httpx.HTTPError as exc:
            prod.health = "down"
            prod.last_error = (prod.last_error or f"health: {exc}")[:500]
        prod.health_checked_at = now
        db.commit()
    finally:
        if own:
            client.close()


def refresh_all() -> None:
    with session_scope() as db:
        for prod in enabled_products(db):
            try:
                refresh_product(db, prod)
            except Exception:  # noqa: BLE001 - фоновый опрос не должен падать
                log.exception("Ошибка опроса продукта %s", prod.id)
                db.rollback()


class ManifestPoller(threading.Thread):
    def __init__(self, interval: int) -> None:
        super().__init__(name="manifest-poller", daemon=True)
        self.interval = interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            refresh_all()
            self.stop_event.wait(self.interval)

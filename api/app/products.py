"""Реестр продуктов: какие продукты есть в установке, их манифесты и состояние.

Продукт есть в установке, если задан его <ID>_API_UPSTREAM. Пока платформа не получила
настоящий манифест (продукт ещё не поднялся), используется встроенный манифест по умолчанию
с ролями из задания: вкладку и роли можно настраивать заранее.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import session_scope, utcnow
from .models import Product

log = logging.getLogger(__name__)

DEFAULT_MANIFESTS: dict[str, dict[str, Any]] = {
    "scanner": {
        "id": "scanner",
        "title": "Сканер",
        "subtitle": "уязвимости и соответствие",
        "icon": "radar",
        "base_path": "/scanner/",
        "api_base": "/api/scanner/",
        "version": "",
        "roles": {
            "admin": "Администратор",
            "operator": "Оператор",
            "auditor": "Аудитор",
            "cred_audit": "Аудит паролей (надбавка)",
            "host_credentials": "Учётные записи хостов (надбавка)",
        },
        "admin_roles": ["admin"],
        "nav": [],
        "search_url": "/api/scanner/search",
        "health_url": "/api/scanner/health/ready",
        "summary_url": "/api/scanner/summary",
    },
    "vm": {
        "id": "vm",
        "title": "Устранение",
        "subtitle": "управление уязвимостями",
        "icon": "wrench",
        "base_path": "/vm/",
        "api_base": "/api/vm/",
        "version": "",
        "roles": {
            "admin": "Администратор",
            "manager": "Руководитель",
            "engineer": "Исполнитель",
            "viewer": "Наблюдатель",
            "remediate_execute": "Запуск исправлений (надбавка)",
            "custom_commands": "Свои команды (надбавка)",
        },
        "admin_roles": ["admin"],
        "nav": [],
        "search_url": "/api/vm/search",
        "health_url": "/api/vm/health/ready",
        "summary_url": "/api/vm/summary",
    },
    "grc": {
        "id": "grc",
        "title": "Аттестация",
        "subtitle": "ФСТЭК №117/21/239",
        "icon": "shield-check",
        "base_path": "/grc/",
        "api_base": "/api/grc/",
        "version": "",
        "roles": {
            "admin": "Администратор",
            "methodologist": "Методист",
            "assessor": "Аттестатор",
            "approve": "Утверждение (надбавка)",
            "viewer": "Наблюдатель",
        },
        "admin_roles": ["admin"],
        "nav": [],
        "search_url": "/api/grc/search",
        "health_url": "/api/grc/health/ready",
        "summary_url": "/api/grc/summary",
    },
}

# Порядок вкладок в оболочке.
ORDER = {"scanner": 0, "vm": 1, "grc": 2}


def sync_from_settings(db: Session) -> None:
    """Приводит таблицу products к переменным окружения."""
    configured = {p.id: p for p in get_settings().products()}
    existing = {p.id: p for p in db.scalars(select(Product))}
    for pid, cfg in configured.items():
        prod = existing.get(pid)
        if prod is None:
            manifest = DEFAULT_MANIFESTS[pid]
            prod = Product(id=pid, title=manifest["title"], manifest=manifest)
            db.add(prod)
        prod.internal_url = cfg.api_upstream
        prod.enabled = True
    for pid, prod in existing.items():
        if pid not in configured:
            prod.enabled = False
    db.commit()


def enabled_products(db: Session) -> list[Product]:
    items = list(db.scalars(select(Product).where(Product.enabled.is_(True))))
    return sorted(items, key=lambda p: ORDER.get(p.id, 99))


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

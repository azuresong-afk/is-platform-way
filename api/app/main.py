"""Точка входа platform-api."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from . import products, users
from .config import get_settings
from .db import init_engine, session_scope
from .routers import health
from .security import keys

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    init_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        with session_scope() as db:
            db.execute(text("SELECT 1"))
            products.sync_from_settings(db)
            keys.ensure_active_key(db)
            users.ensure_bootstrap_admin(db)
        poller = None
        if settings.background_tasks:
            poller = products.ManifestPoller(settings.manifest_poll_seconds)
            poller.start()
        yield
        if poller:
            poller.stop_event.set()

    # API работает за шлюзом с отрезанием префикса /api/platform (контракт v1, п. 1);
    # префикс для документации задаётся при запуске: uvicorn --root-path /api/platform.
    app = FastAPI(
        title="Платформа — API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.include_router(health.router)
    for module in _routers():
        app.include_router(module.router)
    return app


def _routers():
    # Подключаются по мере реализации шагов плана.
    from .routers import ROUTERS

    return ROUTERS

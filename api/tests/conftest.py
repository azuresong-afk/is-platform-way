"""Общие фикстуры: SQLite в памяти, приложение без фоновых задач."""

from __future__ import annotations

import base64
import os

import pytest

os.environ.setdefault("PLATFORM_SECRET_KEY", base64.b64encode(b"k" * 32).decode())
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["BACKGROUND_TASKS"] = "false"
os.environ["COOKIE_SECURE"] = "false"
os.environ["SCANNER_API_UPSTREAM"] = "http://scanner.test"
os.environ["VM_API_UPSTREAM"] = "http://vm.test"
os.environ["GRC_API_UPSTREAM"] = ""
os.environ["SCANNER_EVENTS_SECRET"] = "scanner-secret"
os.environ["VM_EVENTS_SECRET"] = "vm-secret"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin-password-1"


@pytest.fixture
def app():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.db import Base, get_engine
    from app.main import create_app
    from app.security import keys

    keys._private_cache.clear()
    application = create_app()
    Base.metadata.create_all(get_engine())
    yield application
    Base.metadata.drop_all(get_engine())


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def db(client):
    from app.db import session_scope

    s = session_scope()
    yield s
    s.close()

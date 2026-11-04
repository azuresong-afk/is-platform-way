"""Подключение к БД и сессии."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# JSONB в PostgreSQL, JSON в SQLite (юнит-тесты).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite возвращает наивное время — считаем его UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    global _engine, _session_factory
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _rec):  # pragma: no cover - служебное
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    assert _engine is not None, "init_engine() не вызван"
    return _engine


def session_scope() -> Session:
    assert _session_factory is not None, "init_engine() не вызван"
    return _session_factory()


def get_db() -> Iterator[Session]:
    db = session_scope()
    try:
        yield db
    finally:
        db.close()

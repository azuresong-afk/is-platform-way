"""Тест-страж: цепочка миграций непрерывна, номера идут подряд, схема совпадает с моделями."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

API_DIR = Path(__file__).resolve().parents[1]


def _script() -> ScriptDirectory:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_single_head_and_sequential_numbers():
    script = _script()
    assert len(script.get_heads()) == 1, "у цепочки миграций несколько голов"
    revs = list(reversed(list(script.walk_revisions())))
    for i, rev in enumerate(revs, start=1):
        assert rev.revision == f"{i:04d}", f"ожидалась ревизия {i:04d}, а не {rev.revision}"
        expected_down = None if i == 1 else f"{i - 1:04d}"
        assert rev.down_revision == expected_down
    files = sorted(p.name for p in (API_DIR / "alembic" / "versions").glob("*.py"))
    assert all(re.match(r"^\d{4}_[a-z0-9_]+\.py$", f) for f in files), files


PG_URL = os.environ.get("PLATFORM_TEST_PG_URL")


@pytest.mark.skipif(not PG_URL, reason="PLATFORM_TEST_PG_URL не задан")
def test_postgres_upgrade_matches_models_and_audit_is_append_only():
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, text

    from alembic import command
    from app.db import Base

    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", PG_URL)
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], diff
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_log(time, product, actor_name, action, object, result, ip, details) "
                "VALUES (now(), 'platform', '', 'test', '', 'success', '', '{}')"
            )
        )
    for stmt in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
        with pytest.raises(Exception, match="запрещены"), engine.begin() as conn:
            conn.execute(text(stmt))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

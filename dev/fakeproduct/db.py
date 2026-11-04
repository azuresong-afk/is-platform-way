"""Своя БД заглушки — только в составе комплекта (docker-compose.suite.yml).

Если задан DATABASE_URL, заглушка при старте создаёт таблицу `fake_boot` и пишет в неё строку,
а /health/ready проверяет соединение. Так проверка восстановления из копии видит, что продукт
работает со своей базой под своим пользователем. Без DATABASE_URL заглушка живёт в памяти, как раньше.
"""

from __future__ import annotations

import os
import time


def _dsn() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    # Формат SQLAlchemy (postgresql+psycopg://) → формат libpq.
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def init(product_id: str, version: str, attempts: int = 30) -> None:
    dsn = _dsn()
    if not dsn:
        return
    import psycopg

    for i in range(attempts):
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS fake_boot ("
                    " id bigserial PRIMARY KEY, product text NOT NULL, version text NOT NULL,"
                    " at timestamptz NOT NULL DEFAULT now())"
                )
                conn.execute(
                    "INSERT INTO fake_boot (product, version) VALUES (%s, %s)", (product_id, version)
                )
            return
        except psycopg.OperationalError:
            if i == attempts - 1:
                raise
            time.sleep(1)


def ready() -> bool:
    dsn = _dsn()
    if not dsn:
        return True
    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False

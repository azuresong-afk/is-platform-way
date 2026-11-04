"""Окружение Alembic: адрес БД — из настроек приложения (DATABASE_URL)."""

from sqlalchemy import engine_from_config, pool

from alembic import context
from app import models  # noqa: F401 - регистрирует таблицы в метаданных
from app.config import get_settings
from app.db import Base

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()

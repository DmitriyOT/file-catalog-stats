"""Окружение Alembic: async-движок, URL из настроек приложения.

Источники URL в порядке приоритета:
1. `alembic -x dburl=...` — для локальных проверок (например, SQLite-файл);
2. settings.database_url (переменная окружения DATABASE_URL).
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config import settings
from app.db import Base
from app.models import DownloadJob, File  # noqa: F401 — регистрация таблиц в metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return context.get_x_argument(as_dictionary=True).get("dburl") or settings.database_url


def run_migrations_offline() -> None:
    """Миграции без подключения: генерация SQL-скриптов."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Миграции с подключением к базе."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(configuration, prefix="sqlalchemy.")

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

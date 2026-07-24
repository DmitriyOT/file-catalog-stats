"""initial: таблицы files и download_jobs

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-24

Миграция идемпотентна и доводит до актуальной схемы базу в любом состоянии:
- пустая база — создаются обе таблицы и индексы;
- база, созданная ранее через Base.metadata.create_all (без alembic_version),
  получает недостающие колонки/индексы (в частности download_jobs.banned_until).

В offline-режиме (генерация SQL без подключения) инспекция невозможна,
поэтому скрипт генерируется под пустую базу.
"""

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _create_files() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_files_name", "files", ["name"], unique=True)


def _create_download_jobs() -> None:
    op.create_table(
        "download_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("names_received", sa.Integer(), nullable=False),
        sa.Column("files_downloaded", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("banned_until", sa.DateTime(timezone=True), nullable=True),
    )
    # Одновременно активна только одна задача (работает и в PostgreSQL, и в SQLite)
    op.create_index(
        "uq_download_jobs_running",
        "download_jobs",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
        sqlite_where=sa.text("status = 'running'"),
    )


def upgrade() -> None:
    if context.is_offline_mode():
        # Инспекция без подключения невозможна: генерируем DDL для пустой базы
        _create_files()
        _create_download_jobs()
        return

    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "files" not in tables:
        _create_files()

    if "download_jobs" not in tables:
        _create_download_jobs()
        return

    # Таблица уже есть (создана create_all): доводим колонки и индексы
    columns = {col["name"] for col in inspector.get_columns("download_jobs")}
    if "banned_until" not in columns:
        op.add_column("download_jobs", sa.Column("banned_until", sa.DateTime(timezone=True), nullable=True))

    indexes = {idx["name"] for idx in inspector.get_indexes("download_jobs")}
    if "uq_download_jobs_running" not in indexes:
        op.create_index(
            "uq_download_jobs_running",
            "download_jobs",
            ["status"],
            unique=True,
            postgresql_where=sa.text("status = 'running'"),
            sqlite_where=sa.text("status = 'running'"),
        )


def downgrade() -> None:
    op.drop_table("download_jobs")
    op.drop_table("files")

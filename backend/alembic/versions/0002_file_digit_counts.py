"""files.digit_counts: кэш частот цифр

Revision ID: 0002_file_digit_counts
Revises: 0001_initial
Create Date: 2026-07-24

Идемпотентна, как 0001: если колонка уже есть (база доведена вручную),
миграция — no-op. В offline-режиме инспекция невозможна, DDL генерируется
без проверки.
"""
from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_file_digit_counts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        columns = {col["name"] for col in inspector.get_columns("files")}
        if "digit_counts" in columns:
            return
    op.add_column("files", sa.Column("digit_counts", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "digit_counts")

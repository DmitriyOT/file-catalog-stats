from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class File(Base):
    """Скачанный файл каталога."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DownloadJob(Base):
    """Запуск процесса скачивания каталога."""

    __tablename__ = "download_jobs"
    # Одновременно активна только одна задача: частичный unique index
    # защищает от гонки двух стартов (работает и в PostgreSQL, и в SQLite).
    __table_args__ = (
        Index(
            "uq_download_jobs_running",
            "status",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed | cancelled
    names_received: Mapped[int] = mapped_column(default=0)
    files_downloaded: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Момент окончания бана внешнего API (403 + Retry-After); NULL — бана нет
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

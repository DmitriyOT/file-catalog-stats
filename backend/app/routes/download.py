from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_client import FileApiClient
from app.db import get_session, session_factory
from app.downloader import cancel_download_job, is_running, make_ban_callback, start_download_job
from app.models import DownloadJob
from app.timefmt import format_nsk

router = APIRouter(prefix="/api/job", tags=["Скачивание"])


class JobStatus(BaseModel):
    id: int
    status: str
    started_at: datetime
    started_at_nsk: str
    finished_at: datetime | None
    names_received: int
    files_downloaded: int
    error: str | None
    banned_until: datetime | None
    banned_until_nsk: str | None


def to_status(job: DownloadJob) -> JobStatus:
    return JobStatus(
        id=job.id,
        status=job.status,
        started_at=job.started_at,
        started_at_nsk=format_nsk(job.started_at),
        finished_at=job.finished_at,
        names_received=job.names_received,
        files_downloaded=job.files_downloaded,
        error=job.error,
        banned_until=job.banned_until,
        banned_until_nsk=format_nsk(job.banned_until) if job.banned_until is not None else None,
    )


@router.post("/start", response_model=JobStatus, status_code=201)
async def start_job(session: AsyncSession = Depends(get_session)) -> JobStatus:
    """Запустить скачивание каталога. Одновременно может быть активна только одна задача."""
    active = await session.scalar(select(DownloadJob).where(DownloadJob.status == "running"))
    if active is not None and is_running(active.id):
        raise HTTPException(status_code=409, detail="Скачивание уже запущено")

    job = DownloadJob(status="running")
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        # Гонка двух стартов: unique index на status='running' пропустил только одну задачу
        await session.rollback()
        raise HTTPException(status_code=409, detail="Скачивание уже запущено") from None
    await session.refresh(job)

    client = FileApiClient(on_ban=make_ban_callback(job.id, session_factory))
    start_download_job(job.id, session_factory, client)
    return to_status(job)


@router.get("/status", response_model=JobStatus | None)
async def job_status(session: AsyncSession = Depends(get_session)) -> JobStatus | None:
    """Статус последней задачи скачивания (null, если задач ещё не было)."""
    job = await session.scalar(select(DownloadJob).order_by(DownloadJob.id.desc()).limit(1))
    return to_status(job) if job is not None else None


@router.post("/cancel", response_model=JobStatus)
async def cancel_job(session: AsyncSession = Depends(get_session)) -> JobStatus:
    """Отменить активное скачивание. Статус задачи станет cancelled, когда фоновая
    задача обработает отмену (обычно мгновенно, даже во время ожидания разбана)."""
    job = await session.scalar(select(DownloadJob).where(DownloadJob.status == "running"))
    if job is None or not cancel_download_job(job.id):
        raise HTTPException(status_code=409, detail="Нет активной задачи для отмены")
    return to_status(job)

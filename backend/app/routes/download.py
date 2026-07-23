from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_client import FileApiClient
from app.db import get_session, session_factory
from app.downloader import is_running, start_download_job
from app.models import DownloadJob

router = APIRouter(prefix="/api/job", tags=["Скачивание"])

NSK = ZoneInfo("Asia/Novosibirsk")


class JobStatus(BaseModel):
    id: int
    status: str
    started_at: datetime
    started_at_nsk: str
    finished_at: datetime | None
    names_received: int
    files_downloaded: int
    error: str | None


def to_status(job: DownloadJob) -> JobStatus:
    return JobStatus(
        id=job.id,
        status=job.status,
        started_at=job.started_at,
        started_at_nsk=job.started_at.astimezone(NSK).strftime("%d.%m.%Y %H:%M:%S"),
        finished_at=job.finished_at,
        names_received=job.names_received,
        files_downloaded=job.files_downloaded,
        error=job.error,
    )


@router.post("/start", response_model=JobStatus, status_code=201)
async def start_job(session: AsyncSession = Depends(get_session)) -> JobStatus:
    """Запустить скачивание каталога. Одновременно может быть активна только одна задача."""
    active = await session.scalar(select(DownloadJob).where(DownloadJob.status == "running"))
    if active is not None and is_running(active.id):
        raise HTTPException(status_code=409, detail="Скачивание уже запущено")

    job = DownloadJob(status="running")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    start_download_job(job.id, session_factory, FileApiClient())
    return to_status(job)


@router.get("/status", response_model=JobStatus | None)
async def job_status(session: AsyncSession = Depends(get_session)) -> JobStatus | None:
    """Статус последней задачи скачивания (null, если задач ещё не было)."""
    job = await session.scalar(select(DownloadJob).order_by(DownloadJob.id.desc()).limit(1))
    return to_status(job) if job is not None else None

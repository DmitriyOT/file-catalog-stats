from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import File
from app.stats import calculate_stats_cached

router = APIRouter(prefix="/api/stats", tags=["Расчёты"])


class StatsRequest(BaseModel):
    file_ids: list[int] = Field(default_factory=list)
    all: bool = False  # расчёт по всем скачанным файлам


class FileStats(BaseModel):
    id: int
    name: str
    counts: dict[str, int]


class StatsResponse(BaseModel):
    total: dict[str, int]
    files: list[FileStats]


@router.post("", response_model=StatsResponse)
async def calculate(
    payload: StatsRequest,
    session: AsyncSession = Depends(get_session),
) -> StatsResponse:
    """Частоты цифр по выбранным файлам: общая и по каждому файлу."""
    if payload.all:
        files = (await session.scalars(select(File).order_by(File.name))).all()
    elif payload.file_ids:
        files = (
            await session.scalars(select(File).where(File.id.in_(payload.file_ids)).order_by(File.name))
        ).all()
    else:
        raise HTTPException(status_code=422, detail="Укажите file_ids или all=true")

    total, per_file = await calculate_stats_cached(files, session)
    return StatsResponse(
        total=total,
        files=[FileStats(id=f.id, name=f.name, counts=counts) for f, counts in per_file],
    )

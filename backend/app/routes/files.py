from datetime import datetime
from math import ceil
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import File

router = APIRouter(prefix="/api/files", tags=["Файлы"])

NSK = ZoneInfo("Asia/Novosibirsk")


class FileItem(BaseModel):
    id: int
    name: str
    downloaded_at: datetime
    downloaded_at_nsk: str


class FilePage(BaseModel):
    items: list[FileItem]
    total: int
    page: int
    per_page: int
    pages: int


@router.get("", response_model=FilePage)
async def list_files(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sort: str = Query("asc", pattern="^(asc|desc)$"),
    search: str = Query("", max_length=255),
    session: AsyncSession = Depends(get_session),
) -> FilePage:
    """Список скачанных файлов с пагинацией, сортировкой и поиском по имени."""
    count_stmt = select(func.count(File.id))
    list_stmt = select(File)
    if search:
        condition = File.name.ilike(f"%{search}%")
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)

    total = await session.scalar(count_stmt) or 0
    order = File.downloaded_at.desc() if sort == "desc" else File.downloaded_at.asc()
    rows = await session.scalars(
        list_stmt.order_by(order, File.id).offset((page - 1) * per_page).limit(per_page)
    )
    return FilePage(
        items=[
            FileItem(
                id=f.id,
                name=f.name,
                downloaded_at=f.downloaded_at,
                downloaded_at_nsk=f.downloaded_at.astimezone(NSK).strftime("%d.%m.%Y %H:%M:%S"),
            )
            for f in rows
        ],
        total=total,
        page=page,
        per_page=per_page,
        pages=ceil(total / per_page) if total else 0,
    )

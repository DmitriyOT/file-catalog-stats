import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.db import init_db, session_factory
from app.models import DownloadJob
from app.routes import download, files, stats

# Логи приложения (api_client, downloader) в stdout — видны через docker compose logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


async def fail_stale_jobs() -> None:
    """Задачи, оставшиеся в running после перезапуска процесса, считаем прерванными."""
    async with session_factory() as session:
        await session.execute(
            update(DownloadJob)
            .where(DownloadJob.status == "running")
            .values(status="failed", error="Прервано перезапуском сервера")
        )
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await fail_stale_jobs()
    yield


app = FastAPI(title="Сервис скачивания и анализа файлов", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(download.router)
app.include_router(files.router)
app.include_router(stats.router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

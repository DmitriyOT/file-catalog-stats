from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routes import download, files, stats

# Логи приложения (api_client, downloader) в stdout — видны через docker compose logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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

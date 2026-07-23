import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api_client import FileApiClient
from app.models import DownloadJob, File

logger = logging.getLogger(__name__)

BATCH_SIZE = 3

# Активные задачи: job_id -> asyncio.Task
_running: dict[int, asyncio.Task] = {}


def is_running(job_id: int) -> bool:
    task = _running.get(job_id)
    return task is not None and not task.done()


async def run_download_job(
    job_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    client: FileApiClient,
) -> None:
    """Скачать весь каталог: имена -> скачивание по 3 -> отметка, до пустого списка имён.

    Задача владеет переданным клиентом и закрывает его по завершении.
    """
    try:
        async with session_factory() as session:
            while True:
                names = await client.get_names()
                if not names:
                    break

                job = await session.get(DownloadJob, job_id)
                job.names_received += len(names)
                await session.commit()

                for i in range(0, len(names), BATCH_SIZE):
                    batch = names[i : i + BATCH_SIZE]
                    files = await client.download(batch)

                    for name, content in files.items():
                        exists = await session.scalar(select(File.id).where(File.name == name))
                        if exists is None:
                            session.add(File(name=name, content=content, downloaded_at=datetime.now(UTC)))

                    job = await session.get(DownloadJob, job_id)
                    job.files_downloaded += len(files)
                    await session.commit()

                    # Отметка на сервере — только после commit: иначе при падении
                    # коммита файлы окажутся отмеченными, но не сохранёнными локально.
                    # При повторном прогоне дубли отсечёт exists-check выше, а mark идемпотентен.
                    await client.mark_downloaded(list(files))
                    logger.info(
                        "Задача %d: получено %d имён, скачано %d",
                        job_id, job.names_received, job.files_downloaded,
                    )

            job = await session.get(DownloadJob, job_id)
            job.status = "done"
            job.finished_at = datetime.now(UTC)
            await session.commit()
            logger.info("Задача %d завершена: скачано %d файлов", job_id, job.files_downloaded)
    except Exception as exc:
        logger.exception("Задача %d завершилась с ошибкой", job_id)
        async with session_factory() as session:
            job = await session.get(DownloadJob, job_id)
            if job is not None:
                job.status = "failed"
                job.finished_at = datetime.now(UTC)
                job.error = str(exc)
                await session.commit()
    finally:
        _running.pop(job_id, None)
        await client.close()


def start_download_job(
    job_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    client: FileApiClient,
) -> asyncio.Task:
    task = asyncio.create_task(run_download_job(job_id, session_factory, client))
    _running[job_id] = task
    return task

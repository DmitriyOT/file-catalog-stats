import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

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


def cancel_download_job(job_id: int) -> bool:
    """Запросить отмену активной задачи. False — задача не запущена."""
    task = _running.get(job_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def make_ban_callback(
    job_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[float | None], Awaitable[None]]:
    """Callback для FileApiClient: отражает бан внешнего API в поле job.banned_until.

    Сессия открывается на каждое уведомление: бан может длиться полчаса,
    держать соединение всё это время нельзя.
    """

    async def on_ban(wait: float | None) -> None:
        async with session_factory() as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                return
            job.banned_until = (
                datetime.now(UTC) + timedelta(seconds=wait) if wait is not None else None
            )
            await session.commit()

    return on_ban


async def _get_job_or_raise(session: AsyncSession, job_id: int) -> DownloadJob:
    """Загрузить задачу или упасть с внятной ошибкой, если запись удалена."""
    job = await session.get(DownloadJob, job_id)
    if job is None:
        raise RuntimeError(f"Задача {job_id} не найдена в БД")
    return job


async def run_download_job(
    job_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    client: FileApiClient,
) -> None:
    """Скачать весь каталог: имена -> скачивание по 3 -> отметка, до пустого списка имён.

    Задача владеет переданным клиентом и закрывает его по завершении.
    Сессия переоткрывается на каждую итерацию: цикл с банами/паузами может идти
    часами, и одно соединение на весь прогон не переживёт обрыв сети.
    """
    try:
        while True:
            names = await client.get_names()
            if not names:
                break

            async with session_factory() as session:
                job = await _get_job_or_raise(session, job_id)
                job.names_received += len(names)
                await session.commit()

                for i in range(0, len(names), BATCH_SIZE):
                    batch = names[i : i + BATCH_SIZE]
                    files = await client.download(batch)

                    for name, content in files.items():
                        exists = await session.scalar(select(File.id).where(File.name == name))
                        if exists is None:
                            session.add(File(name=name, content=content, downloaded_at=datetime.now(UTC)))

                    job = await _get_job_or_raise(session, job_id)
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

        async with session_factory() as session:
            job = await _get_job_or_raise(session, job_id)
            job.status = "done"
            job.finished_at = datetime.now(UTC)
            await session.commit()
            logger.info("Задача %d завершена: скачано %d файлов", job_id, job.files_downloaded)
    except asyncio.CancelledError:
        # Отмена через POST /api/job/cancel (в т.ч. во время сна на бане в клиенте)
        logger.info("Задача %d отменена", job_id)
        async with session_factory() as session:
            cancelled_job = await session.get(DownloadJob, job_id)
            if cancelled_job is not None:
                cancelled_job.status = "cancelled"
                cancelled_job.finished_at = datetime.now(UTC)
                await session.commit()
        raise
    except Exception as exc:
        logger.exception("Задача %d завершилась с ошибкой", job_id)
        async with session_factory() as session:
            failed_job = await session.get(DownloadJob, job_id)
            if failed_job is not None:
                failed_job.status = "failed"
                failed_job.finished_at = datetime.now(UTC)
                failed_job.error = str(exc)
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

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

import app.routes.download as download_route
from app.downloader import is_running, run_download_job
from app.models import DownloadJob, File


class FakeApiClient:
    """Двойник FileApiClient: выдаёт имена порциями, записывает порядок вызовов."""

    def __init__(self, pages: list[list[str]]):
        self._pages = [list(page) for page in pages]
        self.events: list[str] = []
        self.closed = False

    async def get_names(self) -> list[str]:
        self.events.append("get_names")
        return self._pages.pop(0) if self._pages else []

    async def download(self, file_names: list[str]) -> dict[str, str]:
        self.events.append(f"download:{','.join(file_names)}")
        return {name: f"content of {name}" for name in file_names}

    async def mark_downloaded(self, file_names: list[str]) -> None:
        self.events.append(f"mark:{','.join(file_names)}")

    async def close(self) -> None:
        self.closed = True


async def create_job(session_factory, status: str = "running") -> int:
    async with session_factory() as session:
        job = DownloadJob(status=status)
        session.add(job)
        await session.commit()
        return job.id


async def test_run_download_job_full_cycle(session_factory):
    job_id = await create_job(session_factory)
    client = FakeApiClient([["a.txt", "b.txt", "c.txt", "d.txt"], ["e.txt"]])

    # mark_downloaded должен вызываться после commit: к моменту отметки
    # файлы уже обязаны лежать в БД
    marked_but_missing: list[str] = []
    orig_mark = client.mark_downloaded

    async def mark_and_check(names: list[str]) -> None:
        async with session_factory() as s:
            existing = await s.scalars(select(File.name).where(File.name.in_(names)))
            marked_but_missing.extend(set(names) - set(existing))
        await orig_mark(names)

    client.mark_downloaded = mark_and_check

    await run_download_job(job_id, session_factory, client)

    async with session_factory() as session:
        names = sorted(await session.scalars(select(File.name)))
        job = await session.get(DownloadJob, job_id)

    assert names == ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"]
    assert job.status == "done"
    assert job.names_received == 5
    assert job.files_downloaded == 5
    assert job.finished_at is not None
    assert marked_but_missing == []
    assert client.events.count("get_names") == 3  # две порции + пустой ответ = конец каталога
    assert client.closed


async def test_run_download_job_failure_marks_failed_and_closes_client(session_factory):
    job_id = await create_job(session_factory)

    class FailingClient(FakeApiClient):
        async def download(self, file_names: list[str]) -> dict[str, str]:
            raise RuntimeError("сеть упала")

    client = FailingClient([["a.txt"]])
    await run_download_job(job_id, session_factory, client)

    async with session_factory() as session:
        job = await session.get(DownloadJob, job_id)
    assert job.status == "failed"
    assert "сеть упала" in job.error
    assert client.closed


async def test_start_job_and_conflict_while_running(client, session_factory, monkeypatch):
    gate = asyncio.Event()
    fake = FakeApiClient([])

    # Задача "висит" на get_names, пока тест не отпустит gate
    orig_get_names = fake.get_names

    async def gated_get_names() -> list[str]:
        await gate.wait()
        return await orig_get_names()

    fake.get_names = gated_get_names

    monkeypatch.setattr(download_route, "FileApiClient", lambda: fake)
    monkeypatch.setattr(download_route, "session_factory", session_factory)

    resp = await client.post("/api/job/start")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "running"

    # started_at_nsk — это started_at (UTC), переведённое по Новосибирску
    started = datetime.fromisoformat(body["started_at"])
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    expected = started.astimezone(ZoneInfo("Asia/Novosibirsk")).strftime("%d.%m.%Y %H:%M:%S")
    assert body["started_at_nsk"] == expected

    # повторный старт при активной задаче — 409
    resp = await client.post("/api/job/start")
    assert resp.status_code == 409

    gate.set()
    while is_running(body["id"]):
        await asyncio.sleep(0.01)

    resp = await client.get("/api/job/status")
    assert resp.json()["status"] == "done"
    assert fake.closed


async def test_start_job_conflict_via_unique_index(client, session_factory, monkeypatch):
    # «Зависшая» running-задача без живого фонового таска: предварительная
    # проверка пропустит запрос, но partial unique index не даст вставить
    # вторую running-запись — защита от гонки двух одновременных стартов
    await create_job(session_factory, status="running")
    monkeypatch.setattr(download_route, "FileApiClient", lambda: FakeApiClient([]))
    monkeypatch.setattr(download_route, "session_factory", session_factory)

    resp = await client.post("/api/job/start")
    assert resp.status_code == 409

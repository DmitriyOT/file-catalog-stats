import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

import app.routes.download as download_route
from app.api_client import FileApiClient
from app.config import settings
from app.downloader import (
    cancel_download_job,
    is_running,
    make_ban_callback,
    run_download_job,
    start_download_job,
)
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

    monkeypatch.setattr(download_route, "FileApiClient", lambda **kwargs: fake)
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
    monkeypatch.setattr(download_route, "FileApiClient", lambda **kwargs: FakeApiClient([]))
    monkeypatch.setattr(download_route, "session_factory", session_factory)

    resp = await client.post("/api/job/start")
    assert resp.status_code == 409


async def wait_for(condition, timeout: float = 5.0) -> None:
    """Опрос условия с небольшим шагом, чтобы не гонять event loop впустую."""
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise TimeoutError(f"условие не наступило за {timeout:.1f} c")


async def test_ban_callback_sets_and_clears_banned_until(session_factory):
    job_id = await create_job(session_factory)
    on_ban = make_ban_callback(job_id, session_factory)

    before = datetime.now(UTC)
    await on_ban(60)
    async with session_factory() as session:
        job = await session.get(DownloadJob, job_id)
    banned_until = job.banned_until
    if banned_until.tzinfo is None:  # SQLite возвращает naive — считаем UTC
        banned_until = banned_until.replace(tzinfo=UTC)
    assert before + timedelta(seconds=60) <= banned_until <= datetime.now(UTC) + timedelta(seconds=60)

    await on_ban(None)
    async with session_factory() as session:
        job = await session.get(DownloadJob, job_id)
    assert job.banned_until is None


async def test_ban_visible_in_status_endpoint(client, session_factory, monkeypatch):
    gate = asyncio.Event()
    ban_written = asyncio.Event()  # выставляется после коммита banned_until в фоновой задаче

    class BanningClient(FakeApiClient):
        """Имитирует бан: сообщает on_ban(600) и «спит» до gate, после — сброс бана."""

        def __init__(self, on_ban=None):
            super().__init__([])
            self._on_ban = on_ban

        async def get_names(self) -> list[str]:
            if self._on_ban is not None:
                await self._on_ban(600)
                ban_written.set()
            await gate.wait()
            if self._on_ban is not None:
                # разбанили: имитируем сброс, как делает клиент после успешного запроса
                await self._on_ban(None)
                self._on_ban = None
            return []

    monkeypatch.setattr(download_route, "FileApiClient", lambda **kwargs: BanningClient(**kwargs))
    monkeypatch.setattr(download_route, "session_factory", session_factory)

    resp = await client.post("/api/job/start")
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    # Ждём именно событие, а не опрашиваем /status в цикле: параллельные SELECT
    # и UPDATE на единственном соединении StaticPool могут заблокировать друг друга.
    await asyncio.wait_for(ban_written.wait(), timeout=5)
    body = (await client.get("/api/job/status")).json()

    # banned_until_nsk — это banned_until (UTC), переведённое по Новосибирску
    banned = datetime.fromisoformat(body["banned_until"])
    if banned.tzinfo is None:
        banned = banned.replace(tzinfo=UTC)
    expected = banned.astimezone(ZoneInfo("Asia/Novosibirsk")).strftime("%d.%m.%Y %H:%M:%S")
    assert body["banned_until_nsk"] == expected

    # снятие бана -> поле очищается
    gate.set()
    while is_running(job_id):
        await asyncio.sleep(0.01)

    body = (await client.get("/api/job/status")).json()
    assert body["status"] == "done"
    assert body["banned_until"] is None
    assert body["banned_until_nsk"] is None


async def test_cancel_running_job(client, session_factory, monkeypatch):
    started = asyncio.Event()
    never = asyncio.Event()  # не выставляется никогда: задача висит, пока её не отменят
    fake = FakeApiClient([])

    async def hanging_get_names() -> list[str]:
        started.set()
        await never.wait()
        return []

    fake.get_names = hanging_get_names

    monkeypatch.setattr(download_route, "FileApiClient", lambda **kwargs: fake)
    monkeypatch.setattr(download_route, "session_factory", session_factory)

    resp = await client.post("/api/job/start")
    assert resp.status_code == 201
    job_id = resp.json()["id"]
    await asyncio.wait_for(started.wait(), timeout=5)

    resp = await client.post("/api/job/cancel")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id

    # ждём, пока фоновая задача обработает отмену
    while is_running(job_id):
        await asyncio.sleep(0.01)

    body = (await client.get("/api/job/status")).json()
    assert body["status"] == "cancelled"
    assert body["finished_at"] is not None
    assert fake.closed  # клиент закрыт в finally даже при отмене

    # повторная отмена — активной задачи уже нет
    resp = await client.post("/api/job/cancel")
    assert resp.status_code == 409


async def test_cancel_without_running_job_returns_409(client):
    resp = await client.post("/api/job/cancel")
    assert resp.status_code == 409


async def test_cancel_during_ban_sleep(session_factory, monkeypatch):
    """Отмена прерывает сон на бане внутри клиента, а не ждёт конца Retry-After."""
    monkeypatch.setattr(settings, "request_min_interval", 0)

    transport = httpx.MockTransport(lambda request: httpx.Response(403, headers={"Retry-After": "60"}))
    real_client = FileApiClient(
        base_url="http://test",
        candidate_id="test-candidate",
        client=httpx.AsyncClient(transport=transport, base_url="http://test"),
    )

    job_id = await create_job(session_factory)
    task = start_download_job(job_id, session_factory, real_client)

    # ждём, пока клиент получит 403 и уйдёт в сон на 60 секунд
    await wait_for(lambda: real_client._banned)

    assert cancel_download_job(job_id)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    async with session_factory() as session:
        job = await session.get(DownloadJob, job_id)
    assert job.status == "cancelled"
    assert job.finished_at is not None

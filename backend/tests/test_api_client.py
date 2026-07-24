import io
import zipfile

import httpx
import pytest

from app import api_client as api_client_module
from app.api_client import ExternalApiError, FileApiClient
from app.config import settings


@pytest.fixture(autouse=True)
def no_delays(monkeypatch):
    """Убрать паузы throttle/retry, чтобы тесты не ждали."""
    monkeypatch.setattr(settings, "request_min_interval", 0)
    monkeypatch.setattr(settings, "request_timeout", 5)
    monkeypatch.setattr(api_client_module.asyncio, "sleep", _no_sleep)


async def _no_sleep(delay):
    return None


def make_client(handler, on_ban=None) -> FileApiClient:
    transport = httpx.MockTransport(handler)
    return FileApiClient(
        base_url="http://test",
        candidate_id="test-candidate",
        client=httpx.AsyncClient(transport=transport, base_url="http://test"),
        on_ban=on_ban,
    )


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


async def test_get_names():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Candidate-Id"] == "test-candidate"
        return httpx.Response(200, json={"file_names": ["a.txt", "b.txt"]})

    client = make_client(handler)
    assert await client.get_names() == ["a.txt", "b.txt"]


async def test_retry_on_429_then_success():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"detail": "slow down"}, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"file_names": ["a.txt"]})

    client = make_client(handler)
    assert await client.get_names() == ["a.txt"]
    assert calls == 2


async def test_retry_on_403_then_success():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 2:
            return httpx.Response(403, json={"detail": "banned"}, headers={"Retry-After": "5"})
        return httpx.Response(200, json={"file_names": []})

    client = make_client(handler)
    assert await client.get_names() == []
    assert calls == 3


async def test_404_raises_immediately():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"detail": "no such file"})

    client = make_client(handler)
    with pytest.raises(ExternalApiError, match="404"):
        await client.download(["missing.txt"])
    assert calls == 1


async def test_exhausted_retries_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = make_client(handler)
    with pytest.raises(ExternalApiError, match="исчерпаны повторы"):
        await client.get_names()


async def test_download_unpacks_zip():
    payload = {"a.txt": "0123456789", "b.txt": "55555"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=make_zip(payload), headers={"Content-Type": "application/zip"})

    client = make_client(handler)
    assert await client.download(["a.txt", "b.txt"]) == payload


async def test_download_batch_limit():
    client = make_client(lambda r: httpx.Response(200))
    with pytest.raises(ValueError):
        await client.download(["a", "b", "c", "d"])
    with pytest.raises(ValueError):
        await client.download([])


async def test_mark_downloaded():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"marked_now": 2, "already_marked": 1})

    client = make_client(handler)
    result = await client.mark_downloaded(["a.txt", "b.txt", "c.txt"])
    assert result.marked_now == 2
    assert result.already_marked == 1


async def test_429_raises_min_interval():
    """Retry-After при 429 — это лимит сервера: интервал растёт на всю сессию."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"detail": "slow down"}, headers={"Retry-After": "5"})
        return httpx.Response(200, json={"file_names": []})

    client = make_client(handler)
    assert client._min_interval == 0  # в тестах базовый интервал обнулён
    assert await client.get_names() == []
    assert client._min_interval == 5.0
    assert client._blocked_until > 0


async def test_429_never_shrinks_interval():
    """Меньший Retry-After не должен снижать уже выученный лимит."""
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "10"}),
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"file_names": []}),
        ]
    )

    client = make_client(lambda r: next(responses))
    assert await client.get_names() == []
    assert client._min_interval == 10.0


async def test_403_raises_min_interval():
    """После бана (403) темп снижаем: прежний интервал уже привёл к бану."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(403, json={"detail": "banned"}, headers={"Retry-After": "1800"})
        return httpx.Response(200, json={"file_names": []})

    client = make_client(handler)
    assert await client.get_names() == []
    assert client._min_interval == 1800.0  # интервал вырос, чтобы не словить повторный бан
    assert client._blocked_until > 0  # и запросы заблокированы до разбана


async def test_403_notifies_on_ban_and_reset_after_success():
    """403 с Retry-After -> on_ban(секунды); первый успех после бана -> on_ban(None)."""
    calls = 0
    ban_events: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(403, json={"detail": "banned"}, headers={"Retry-After": "30"})
        return httpx.Response(200, json={"file_names": []})

    client = make_client(handler, on_ban=ban_events.append)  # sync-callback тоже поддерживается
    assert await client.get_names() == []
    assert ban_events == [30.0, None]
    assert client._min_interval == 30.0


async def test_on_ban_async_callback():
    calls = 0
    ban_events: list[float | None] = []

    async def on_ban(wait: float | None) -> None:
        ban_events.append(wait)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(403, headers={"Retry-After": "10"})
        return httpx.Response(200, json={"file_names": []})

    client = make_client(handler, on_ban=on_ban)
    assert await client.get_names() == []
    assert ban_events == [10.0, None]


async def test_429_does_not_notify_on_ban():
    """429 — не бан: on_ban не вызывается."""
    calls = 0
    ban_events: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "5"})
        return httpx.Response(200, json={"file_names": []})

    client = make_client(handler, on_ban=ban_events.append)
    assert await client.get_names() == []
    assert ban_events == []

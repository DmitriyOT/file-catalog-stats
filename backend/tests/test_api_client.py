import io
import zipfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from app import api_client as api_client_module
from app.api_client import (
    DEFAULT_RETRY_AFTER,
    MAX_RETRY_AFTER,
    ExternalApiError,
    FileApiClient,
)
from app.config import settings


@pytest.fixture(autouse=True)
def no_delays(monkeypatch):
    """Убрать паузы throttle/retry, чтобы тесты не ждали."""
    monkeypatch.setattr(settings, "request_min_interval", 0)
    monkeypatch.setattr(settings, "request_timeout", 5)
    monkeypatch.setattr(api_client_module.asyncio, "sleep", _no_sleep)


async def _no_sleep(delay):
    return None


def record_sleeps(monkeypatch) -> list[float]:
    """Заменить sleep на регистратор: вернуть список запрошенных пауз."""
    sleeps: list[float] = []

    async def record(delay):
        sleeps.append(delay)

    monkeypatch.setattr(api_client_module.asyncio, "sleep", record)
    return sleeps


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


# --- Парсинг Retry-After ---


def test_parse_retry_after_numeric():
    assert FileApiClient._parse_retry_after(httpx.Response(429, headers={"Retry-After": "7"})) == 7.0
    # 0 — валидное значение, дефолтом не подменяется
    assert FileApiClient._parse_retry_after(httpx.Response(429, headers={"Retry-After": "0"})) == 0.0
    assert FileApiClient._parse_retry_after(httpx.Response(429, headers={"Retry-After": "1.5"})) == 1.5


def test_parse_retry_after_negative_and_garbage_are_default():
    assert FileApiClient._parse_retry_after(httpx.Response(429, headers={"Retry-After": "-5"})) == DEFAULT_RETRY_AFTER
    assert FileApiClient._parse_retry_after(httpx.Response(429, headers={"Retry-After": "soon"})) == DEFAULT_RETRY_AFTER


def test_parse_retry_after_missing_is_default():
    assert FileApiClient._parse_retry_after(httpx.Response(429)) == DEFAULT_RETRY_AFTER


def test_parse_retry_after_capped():
    """Кривой заголовок не должен усыпить задачу на сутки: потолок MAX_RETRY_AFTER."""
    assert FileApiClient._parse_retry_after(httpx.Response(429, headers={"Retry-After": "999999"})) == MAX_RETRY_AFTER
    future = datetime.now(timezone.utc) + timedelta(days=2)
    resp = httpx.Response(429, headers={"Retry-After": format_datetime(future, usegmt=True)})
    assert FileApiClient._parse_retry_after(resp) == MAX_RETRY_AFTER


def test_parse_retry_after_http_date_future():
    future = datetime.now(timezone.utc) + timedelta(seconds=120)
    resp = httpx.Response(429, headers={"Retry-After": format_datetime(future, usegmt=True)})
    value = FileApiClient._parse_retry_after(resp)
    assert 100 < value <= 120  # допуск на время выполнения теста


def test_parse_retry_after_http_date_past_is_zero():
    past = datetime.now(timezone.utc) - timedelta(seconds=120)
    resp = httpx.Response(429, headers={"Retry-After": format_datetime(past, usegmt=True)})
    assert FileApiClient._parse_retry_after(resp) == 0.0


# --- Ожидание: Retry-After против backoff ---


async def test_retry_after_zero_means_no_default_wait(monkeypatch):
    """Retry-After: 0 -> ожидание 0, а не дефолтные 5 с."""
    sleeps = record_sleeps(monkeypatch)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"file_names": []})

    client = make_client(handler)
    assert await client.get_names() == []
    assert DEFAULT_RETRY_AFTER not in sleeps
    assert all(delay < 1.0 for delay in sleeps)


async def test_retry_after_takes_priority_over_backoff(monkeypatch):
    """Есть Retry-After — ждём строго его, а не экспоненту backoff."""
    sleeps = record_sleeps(monkeypatch)
    responses = iter(
        [
            httpx.Response(500),  # backoff: 1 c
            httpx.Response(429, headers={"Retry-After": "7"}),  # ждём 7, а не 2**1
            httpx.Response(200, json={"file_names": []}),
        ]
    )

    client = make_client(lambda r: next(responses))
    assert await client.get_names() == []
    assert sleeps[0] == 1  # backoff для 500
    assert 6.5 < sleeps[1] <= 7.0  # Retry-After в приоритете над экспонентой


async def test_separate_backoff_counters(monkeypatch):
    """Серия 429 не накручивает backoff сетевых ошибок/5xx: счётчики раздельные."""
    sleeps = record_sleeps(monkeypatch)
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(500),  # backoff стартует с 1 c, а не с 2**3=8
            httpx.Response(200, json={"file_names": []}),
        ]
    )

    client = make_client(lambda r: next(responses))
    assert await client.get_names() == []
    assert 8 not in sleeps  # общий счётчик дал бы 2**3
    assert 1 in sleeps  # backoff для 5xx — с минимальной задержки


async def test_success_resets_backoff_counters(monkeypatch):
    """Успешный запрос сбрасывает счётчики backoff."""
    sleeps = record_sleeps(monkeypatch)
    responses = iter(
        [
            httpx.Response(500),  # backoff 1 c
            httpx.Response(500),  # backoff 2 c
            httpx.Response(200, json={"file_names": []}),  # сброс счётчиков
            httpx.Response(500),  # снова backoff 1 c, а не 4
            httpx.Response(200, json={"file_names": []}),
        ]
    )

    client = make_client(lambda r: next(responses))
    assert await client.get_names() == []
    assert await client.get_names() == []
    assert sleeps == [1, 2, 1]
    assert client._error_attempts == 0
    assert client._rate_attempts == 0


async def test_on_ban_gets_delay_from_http_date():
    """on_ban получает фактическое время ожидания и при Retry-After в формате HTTP-date."""
    calls = 0
    ban_events: list[float | None] = []
    unbanned_at = datetime.now(timezone.utc) + timedelta(seconds=90)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                403,
                headers={"Retry-After": format_datetime(unbanned_at, usegmt=True)},
            )
        return httpx.Response(200, json={"file_names": []})

    client = make_client(handler, on_ban=ban_events.append)
    assert await client.get_names() == []
    assert len(ban_events) == 2
    assert 80 < ban_events[0] <= 90
    assert ban_events[1] is None

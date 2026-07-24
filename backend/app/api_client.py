import asyncio
import inspect
import io
import logging
import time
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_RETRY_AFTER = 5.0
MAX_BATCH_SIZE = 3

# Уведомление о бане: секунды до разбана или None, когда бан снят
OnBanCallback = Callable[[float | None], Awaitable[None] | None]


@dataclass
class MarkResult:
    marked_now: int
    already_marked: int


class ExternalApiError(Exception):
    """Непреодолимая ошибка внешнего API после всех повторов."""


class FileApiClient:
    """Клиент API выдачи файлов с учётом ограничений частоты запросов.

    - проактивная пауза между запросами (request_min_interval);
    - 429/403: все запросы блокируются до конца Retry-After (_blocked_until);
    - 429/403: Retry-After запоминается как лимит темпа на всю сессию —
      сервер сообщил «не чаще, чем раз в N секунд», и мы ему подчиняемся,
      иначе повторные нарушения приведут к новому 30-минутному бану (403);
    - 403 (бан): перед сном на Retry-After вызывается on_ban(секунды),
      после первого успешного запроса — on_ban(None);
    - сетевые ошибки и 5xx: повтор с экспоненциальным backoff.
    """

    def __init__(
        self,
        base_url: str | None = None,
        candidate_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        on_ban: OnBanCallback | None = None,
    ) -> None:
        self._base_url = (base_url or settings.api_base_url).rstrip("/")
        self._candidate_id = candidate_id or settings.candidate_id
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=settings.request_timeout,
        )
        self._owns_client = client is None
        self._on_ban = on_ban
        self._banned = False  # сейчас отбываем бан (403), ждём разбана
        self._last_request_at = 0.0
        self._blocked_until = 0.0  # монотонное время, до которого запросы запрещены (Retry-After)
        self._min_interval = settings.request_min_interval  # растёт при 429/403 — см. _slow_down

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_names(self) -> list[str]:
        """Порция случайных имён, ещё не отмеченных как скачанные. Пустой список — каталог скачан."""
        resp = await self._request("GET", "/api/files/names")
        return resp.json()["file_names"]

    async def download(self, file_names: list[str]) -> dict[str, str]:
        """Скачать до 3 файлов одним ZIP-архивом. Возвращает {имя: содержимое}."""
        if not 1 <= len(file_names) <= MAX_BATCH_SIZE:
            raise ValueError(f"За один запрос можно скачать от 1 до {MAX_BATCH_SIZE} файлов")
        resp = await self._request("POST", "/api/files/download", json={"file_names": file_names})
        return self._unpack_zip(resp.content)

    async def mark_downloaded(self, file_names: list[str]) -> MarkResult:
        """Отметить файлы скачанными, чтобы они исчезли из выдачи имён."""
        if not file_names:
            raise ValueError("Список имён не должен быть пустым")
        resp = await self._request("POST", "/api/files/downloaded", json={"file_names": file_names})
        data = resp.json()
        return MarkResult(marked_now=data["marked_now"], already_marked=data["already_marked"])

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers["X-Candidate-Id"] = self._candidate_id

        for attempt in range(settings.max_retries):
            await self._throttle()
            try:
                resp = await self._client.request(method, path, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                await self._backoff(attempt, f"сетевая ошибка: {exc}")
                continue

            if resp.status_code < 400:
                if self._banned:
                    # Первый успешный запрос после бана — бан отбыт
                    self._banned = False
                    await self._notify_ban(None)
                return resp

            if resp.status_code in (403, 429):
                retry_after = self._parse_retry_after(resp)
                logger.warning(
                    "%s %s -> %s, повтор через %.1f c (попытка %d/%d)",
                    method, path, resp.status_code, retry_after, attempt + 1, settings.max_retries,
                )
                if resp.status_code == 403:
                    self._banned = True
                    await self._notify_ban(retry_after)
                self._slow_down(retry_after)
                continue

            if resp.status_code >= 500:
                await self._backoff(attempt, f"HTTP {resp.status_code}")
                continue

            # 4xx, которые не имеет смысла повторять (404, 422)
            raise ExternalApiError(f"{method} {path} -> {resp.status_code}: {resp.text}")

        raise ExternalApiError(f"{method} {path}: исчерпаны повторы ({settings.max_retries})")

    def _slow_down(self, retry_after: float) -> None:
        """Остановить все запросы до конца Retry-After и запомнить лимит темпа.

        Retry-After при 429 — это фактически сообщение о лимите сервера
        («не чаще одного запроса в N секунд»), поэтому он становится новым
        минимальным интервалом на всю сессию. После 403 (бана) интервал тоже
        поднимаем: прежний темп уже привёл к бану, повторять его нельзя.
        """
        self._blocked_until = time.monotonic() + retry_after
        if retry_after > self._min_interval:
            self._min_interval = retry_after
            logger.info("Сервер сообщил лимит: не чаще 1 запроса в %.1f c", retry_after)

    async def _notify_ban(self, wait: float | None) -> None:
        """Сообщить подписчику о бане (секунды до разбана) или о его снятии (None)."""
        if self._on_ban is None:
            return
        result = self._on_ban(wait)
        if inspect.isawaitable(result):
            await result

    async def _throttle(self) -> None:
        wait = max(
            self._blocked_until,
            self._last_request_at + self._min_interval,
        ) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float:
        try:
            return max(float(resp.headers.get("Retry-After", "")), 0.0) or DEFAULT_RETRY_AFTER
        except ValueError:
            return DEFAULT_RETRY_AFTER

    @staticmethod
    async def _backoff(attempt: int, reason: str) -> None:
        delay = min(2**attempt, 30)
        logger.warning("Ошибка (%s), повтор через %d c", reason, delay)
        await asyncio.sleep(delay)

    @staticmethod
    def _unpack_zip(content: bytes) -> dict[str, str]:
        files: dict[str, str] = {}
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                files[name] = zf.read(name).decode("utf-8")
        return files

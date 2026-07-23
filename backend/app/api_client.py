import asyncio
import io
import logging
import time
import zipfile
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_RETRY_AFTER = 5.0
MAX_BATCH_SIZE = 3


@dataclass
class MarkResult:
    marked_now: int
    already_marked: int


class ExternalApiError(Exception):
    """Непреодолимая ошибка внешнего API после всех повторов."""


class FileApiClient:
    """Клиент API выдачи файлов с учётом ограничений частоты запросов.

    - проактивная пауза между запросами (request_min_interval);
    - 429/403: пауза по заголовку Retry-After и повтор;
    - сетевые ошибки и 5xx: повтор с экспоненциальным backoff.
    """

    def __init__(
        self,
        base_url: str | None = None,
        candidate_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or settings.api_base_url).rstrip("/")
        self._candidate_id = candidate_id or settings.candidate_id
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=settings.request_timeout,
        )
        self._owns_client = client is None
        self._last_request_at = 0.0

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
                return resp

            if resp.status_code in (403, 429):
                retry_after = self._parse_retry_after(resp)
                logger.warning(
                    "%s %s -> %s, повтор через %.1f c (попытка %d/%d)",
                    method, path, resp.status_code, retry_after, attempt + 1, settings.max_retries,
                )
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                await self._backoff(attempt, f"HTTP {resp.status_code}")
                continue

            # 4xx, которые не имеет смысла повторять (404, 422)
            raise ExternalApiError(f"{method} {path} -> {resp.status_code}: {resp.text}")

        raise ExternalApiError(f"{method} {path}: исчерпаны повторы ({settings.max_retries})")

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < settings.request_min_interval:
            await asyncio.sleep(settings.request_min_interval - elapsed)
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

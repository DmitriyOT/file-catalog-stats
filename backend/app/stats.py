from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import File

DIGITS = tuple("0123456789")


def count_digits(content: str) -> dict[str, int]:
    """Частоты цифр 0-9 в содержимом файла. Прочие символы игнорируются."""
    counts = dict.fromkeys(DIGITS, 0)
    for ch in content:
        if ch in counts:
            counts[ch] += 1
    return counts


def calculate_stats(files: Iterable[File]) -> tuple[dict[str, int], list[tuple[File, dict[str, int]]]]:
    """Общая статистика и статистика по каждому файлу."""
    total = dict.fromkeys(DIGITS, 0)
    per_file: list[tuple[File, dict[str, int]]] = []
    for f in files:
        counts = count_digits(f.content)
        per_file.append((f, counts))
        for digit, n in counts.items():
            total[digit] += n
    return total, per_file


async def calculate_stats_cached(
    files: Iterable[File],
    session: AsyncSession,
) -> tuple[dict[str, int], list[tuple[File, dict[str, int]]]]:
    """Общая статистика с кэшем частот в File.digit_counts.

    Кэш заполняется лениво: у файлов без digit_counts (старые записи) частоты
    считаются один раз и сохраняются в БД, повторные запросы берут готовые.
    """
    total = dict.fromkeys(DIGITS, 0)
    per_file: list[tuple[File, dict[str, int]]] = []
    cache_updated = False
    for f in files:
        counts = f.digit_counts
        if counts is None:
            counts = count_digits(f.content)
            f.digit_counts = counts
            cache_updated = True
        per_file.append((f, counts))
        for digit, n in counts.items():
            total[digit] += n
    if cache_updated:
        await session.commit()
    return total, per_file

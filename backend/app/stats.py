from collections.abc import Iterable

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

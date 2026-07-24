"""Форматирование времени для ответов API."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

NSK = ZoneInfo("Asia/Novosibirsk")


def format_nsk(dt: datetime) -> str:
    """Время по Новосибирску. Naive datetime (например, из SQLite) считается UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(NSK).strftime("%d.%m.%Y %H:%M:%S")

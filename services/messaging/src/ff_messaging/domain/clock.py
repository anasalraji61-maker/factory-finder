"""Wall clock used for persisted timestamps (UTC, millisecond precision)."""

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def format_utc(value: datetime) -> str:
    """ISO-8601 UTC with millisecond precision and a ``Z`` suffix."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

import hashlib
import random
import asyncio
from datetime import datetime, timezone
from typing import Optional


def normalize_channel(value: str) -> str:
    value = value.strip()

    value = value.replace("https://t.me/", "")
    value = value.replace("http://t.me/", "")
    value = value.replace("t.me/", "")
    value = value.strip("/")

    if not value.startswith("@"):
        value = "@" + value

    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def is_inside_date_range(
    message_date: Optional[datetime],
    after_date: Optional[datetime],
    before_date: Optional[datetime],
) -> bool:
    if message_date is None:
        return True

    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)

    if after_date and message_date < after_date:
        return False

    if before_date and message_date > before_date:
        return False

    return True


async def polite_delay(min_seconds: float, max_seconds: float) -> None:
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)
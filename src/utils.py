from __future__ import annotations

import asyncio
import hashlib
import hmac
import random
from datetime import datetime, timezone


def normalize_channel(value: str) -> str:
    channel = value.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if channel.startswith(prefix):
            channel = channel[len(prefix) :]
            break
    channel = channel.strip("/")
    if not channel:
        raise ValueError("Telegram channel value is empty.")
    return channel if channel.startswith("@") else f"@{channel}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def pseudonymize(value: str, salt: str) -> str:
    return hmac.new(
        salt.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_inside_date_range(
    message_date: datetime | None,
    after_date: datetime | None,
    before_date: datetime | None,
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
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))

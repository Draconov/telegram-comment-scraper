import csv
from typing import Dict, List

from src.utils import normalize_channel


TRUTHY_VALUES = {"true", "1", "yes", "y", "active"}


def _is_active(value: str) -> bool:
    if value is None:
        return True

    return value.strip().lower() in TRUTHY_VALUES


def load_sources(path: str) -> List[Dict[str, str]]:
    sources = []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for index, row in enumerate(reader, start=1):
            active_value = row.get("active", "true")

            if not _is_active(active_value):
                continue

            raw_channel = (
                row.get("telegram_username")
                or row.get("channel_url")
                or row.get("channel")
                or ""
            )

            if not raw_channel:
                print(f"Skipping row {index}: no Telegram channel found.")
                continue

            telegram_username = normalize_channel(raw_channel)

            source_id = row.get("source_id") or telegram_username.replace("@", "")

            source = {
                "source_id": source_id,
                "channel_title": row.get("channel_title", ""),
                "channel_url": row.get("channel_url", ""),
                "telegram_username": telegram_username,
                "language": row.get("language", ""),
                "source_type": row.get("source_type", ""),
                "topic_label": row.get("topic_label", ""),
                "toxicity_expected": row.get("toxicity_expected", ""),
                "notes": row.get("notes", ""),
                "active": "true",
            }

            sources.append(source)

    return sources
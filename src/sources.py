from __future__ import annotations

import csv
from pathlib import Path

from src.utils import normalize_channel

TRUTHY_VALUES = {"true", "1", "yes", "y", "active"}


def _is_active(value: str | None) -> bool:
    if value is None or not value.strip():
        return True
    return value.strip().lower() in TRUTHY_VALUES


def load_sources(path: str | Path) -> list[dict[str, str]]:
    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(
            f"Source file not found: {source_path}. "
            "Copy sources.example.csv to sources.csv and edit it locally."
        )

    sources: list[dict[str, str]] = []
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Source file has no CSV header: {source_path}")

        for row_number, row in enumerate(reader, start=2):
            if not _is_active(row.get("active", "true")):
                continue

            raw_channel = (
                row.get("telegram_username")
                or row.get("channel_url")
                or row.get("channel")
                or ""
            ).strip()
            if not raw_channel:
                print(f"Skipping CSV row {row_number}: no Telegram channel found.")
                continue

            try:
                telegram_username = normalize_channel(raw_channel)
            except ValueError as error:
                print(f"Skipping CSV row {row_number}: {error}")
                continue

            source_id = (row.get("source_id") or "").strip()
            if not source_id:
                source_id = telegram_username.removeprefix("@")

            sources.append(
                {
                    "source_id": source_id,
                    "channel_title": (row.get("channel_title") or "").strip(),
                    "channel_url": (row.get("channel_url") or "").strip(),
                    "telegram_username": telegram_username,
                    "language": (row.get("language") or "").strip(),
                    "source_type": (row.get("source_type") or "").strip(),
                    "topic_label": (row.get("topic_label") or "").strip(),
                    "toxicity_expected": (
                        row.get("toxicity_expected") or ""
                    ).strip(),
                    "notes": (row.get("notes") or "").strip(),
                    "active": "true",
                }
            )

    return sources

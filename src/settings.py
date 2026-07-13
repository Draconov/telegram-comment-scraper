from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    session_name: str


@dataclass(frozen=True)
class InputConfig:
    sources_file: str


@dataclass(frozen=True)
class DatabaseConfig:
    path: str


@dataclass(frozen=True)
class ScrapingConfig:
    posts_per_channel: int
    comments_per_post: int
    scrape_comments: bool
    after_date: str | None
    before_date: str | None
    keyword_filter: str | None
    include_posts_without_text: bool
    min_delay_seconds: float
    max_delay_seconds: float
    stop_on_flood_wait: bool


@dataclass(frozen=True)
class PrivacyConfig:
    hash_sender_ids: bool
    save_sender_ids: bool
    save_usernames: bool
    anonymization_salt: str | None


@dataclass(frozen=True)
class ExportConfig:
    output_dir: str


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    input: InputConfig
    database: DatabaseConfig
    scraping: ScrapingConfig
    privacy: PrivacyConfig
    export: ExportConfig


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing environment variable {name}. "
            "Create a local .env file from .env.example."
        )
    return value


def _mapping(value: Any, section: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"The '{section}' section in config.yaml must be a mapping.")
    return value


def load_config(path: str | Path) -> AppConfig:
    load_dotenv()

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    raw = _mapping(raw, "root")
    input_raw = _mapping(raw.get("input", {}), "input")
    database_raw = _mapping(raw.get("database", {}), "database")
    scraping_raw = _mapping(raw.get("scraping", {}), "scraping")
    privacy_raw = _mapping(raw.get("privacy", {}), "privacy")
    export_raw = _mapping(raw.get("export", {}), "export")

    api_id_text = _require_env("TELEGRAM_API_ID")
    try:
        api_id = int(api_id_text)
    except ValueError as error:
        raise ValueError("TELEGRAM_API_ID must contain digits only.") from error

    hash_sender_ids = bool(privacy_raw.get("hash_sender_ids", True))
    anonymization_salt = os.getenv("ANONYMIZATION_SALT", "").strip() or None
    if hash_sender_ids and not anonymization_salt:
        raise RuntimeError(
            "ANONYMIZATION_SALT is required when hash_sender_ids is enabled. "
            "Generate one locally with: python -c \"import secrets; "
            "print(secrets.token_hex(32))\""
        )

    min_delay = float(scraping_raw.get("min_delay_seconds", 2))
    max_delay = float(scraping_raw.get("max_delay_seconds", 6))
    if min_delay < 0 or max_delay < min_delay:
        raise ValueError(
            "Scraping delays must satisfy 0 <= min_delay_seconds <= max_delay_seconds."
        )

    return AppConfig(
        telegram=TelegramConfig(
            api_id=api_id,
            api_hash=_require_env("TELEGRAM_API_HASH"),
            session_name=os.getenv(
                "TELEGRAM_SESSION_NAME", "sessions/research_session"
            ).strip(),
        ),
        input=InputConfig(
            sources_file=str(input_raw.get("sources_file", "sources.csv")),
        ),
        database=DatabaseConfig(
            path=str(database_raw.get("path", "data/telegram_research.sqlite")),
        ),
        scraping=ScrapingConfig(
            posts_per_channel=max(0, int(scraping_raw.get("posts_per_channel", 100))),
            comments_per_post=max(0, int(scraping_raw.get("comments_per_post", 100))),
            scrape_comments=bool(scraping_raw.get("scrape_comments", True)),
            after_date=scraping_raw.get("after_date"),
            before_date=scraping_raw.get("before_date"),
            keyword_filter=scraping_raw.get("keyword_filter"),
            include_posts_without_text=bool(
                scraping_raw.get("include_posts_without_text", False)
            ),
            min_delay_seconds=min_delay,
            max_delay_seconds=max_delay,
            stop_on_flood_wait=bool(
                scraping_raw.get("stop_on_flood_wait", False)
            ),
        ),
        privacy=PrivacyConfig(
            hash_sender_ids=hash_sender_ids,
            save_sender_ids=bool(privacy_raw.get("save_sender_ids", False)),
            save_usernames=bool(privacy_raw.get("save_usernames", False)),
            anonymization_salt=anonymization_salt,
        ),
        export=ExportConfig(
            output_dir=str(export_raw.get("output_dir", "exports")),
        ),
    )

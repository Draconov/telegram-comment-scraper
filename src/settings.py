import os
from dataclasses import dataclass
from typing import Optional

import yaml
from dotenv import load_dotenv


@dataclass
class TelegramConfig:
    api_id: int
    api_hash: str
    session_name: str


@dataclass
class InputConfig:
    sources_file: str


@dataclass
class DatabaseConfig:
    path: str


@dataclass
class ScrapingConfig:
    posts_per_channel: int
    comments_per_post: int
    scrape_comments: bool
    after_date: Optional[str]
    before_date: Optional[str]
    keyword_filter: Optional[str]
    include_posts_without_text: bool
    min_delay_seconds: float
    max_delay_seconds: float
    stop_on_flood_wait: bool


@dataclass
class PrivacyConfig:
    hash_sender_ids: bool
    save_sender_ids: bool
    save_usernames: bool
    save_media: bool


@dataclass
class ExportConfig:
    output_dir: str


@dataclass
class AppConfig:
    telegram: TelegramConfig
    input: InputConfig
    database: DatabaseConfig
    scraping: ScrapingConfig
    privacy: PrivacyConfig
    export: ExportConfig


def _require_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Missing environment variable: {name}. "
            f"Create a .env file based on .env.example."
        )

    return value


def load_config(path: str) -> AppConfig:
    load_dotenv()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    api_id = int(_require_env("TELEGRAM_API_ID"))
    api_hash = _require_env("TELEGRAM_API_HASH")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "research_session")

    scraping_raw = raw.get("scraping", {})
    privacy_raw = raw.get("privacy", {})
    export_raw = raw.get("export", {})

    return AppConfig(
        telegram=TelegramConfig(
            api_id=api_id,
            api_hash=api_hash,
            session_name=session_name,
        ),
        input=InputConfig(
            sources_file=raw["input"]["sources_file"],
        ),
        database=DatabaseConfig(
            path=raw["database"]["path"],
        ),
        scraping=ScrapingConfig(
            posts_per_channel=int(scraping_raw.get("posts_per_channel", 100)),
            comments_per_post=int(scraping_raw.get("comments_per_post", 100)),
            scrape_comments=bool(scraping_raw.get("scrape_comments", True)),
            after_date=scraping_raw.get("after_date"),
            before_date=scraping_raw.get("before_date"),
            keyword_filter=scraping_raw.get("keyword_filter"),
            include_posts_without_text=bool(
                scraping_raw.get("include_posts_without_text", False)
            ),
            min_delay_seconds=float(scraping_raw.get("min_delay_seconds", 2)),
            max_delay_seconds=float(scraping_raw.get("max_delay_seconds", 6)),
            stop_on_flood_wait=bool(scraping_raw.get("stop_on_flood_wait", False)),
        ),
        privacy=PrivacyConfig(
            hash_sender_ids=bool(privacy_raw.get("hash_sender_ids", True)),
            save_sender_ids=bool(privacy_raw.get("save_sender_ids", False)),
            save_usernames=bool(privacy_raw.get("save_usernames", False)),
            save_media=bool(privacy_raw.get("save_media", False)),
        ),
        export=ExportConfig(
            output_dir=export_raw.get("output_dir", "exports"),
        ),
    )
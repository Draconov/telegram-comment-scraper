from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.utils import utc_now_iso


def connect_database(path: str | Path) -> sqlite3.Connection:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA foreign_keys=ON;")
    return connection


def init_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            channel_title TEXT,
            channel_url TEXT,
            telegram_username TEXT,
            language TEXT,
            source_type TEXT,
            topic_label TEXT,
            toxicity_expected TEXT,
            notes TEXT,
            active TEXT,
            scraped_at TEXT
        );

        CREATE TABLE IF NOT EXISTS posts (
            post_uid TEXT PRIMARY KEY,
            source_id TEXT,
            channel_username TEXT,
            post_id INTEGER,
            post_url TEXT,
            date TEXT,
            text TEXT,
            views INTEGER,
            forwards INTEGER,
            reactions_json TEXT,
            comments_count INTEGER,
            scraped_at TEXT,
            FOREIGN KEY(source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            comment_uid TEXT PRIMARY KEY,
            post_uid TEXT,
            source_id TEXT,
            channel_username TEXT,
            post_id INTEGER,
            comment_id INTEGER,
            date TEXT,
            sender_id TEXT,
            sender_hash TEXT,
            sender_username TEXT,
            text TEXT,
            media_type TEXT,
            scraped_at TEXT,
            FOREIGN KEY(post_uid) REFERENCES posts(post_uid),
            FOREIGN KEY(source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE IF NOT EXISTS scrape_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            config_json TEXT NOT NULL,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS run_sources (
            run_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            posts_collected INTEGER NOT NULL DEFAULT 0,
            comments_collected INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            PRIMARY KEY (run_id, source_id),
            FOREIGN KEY(run_id) REFERENCES scrape_runs(run_id),
            FOREIGN KEY(source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE IF NOT EXISTS run_posts (
            run_id TEXT NOT NULL,
            post_uid TEXT NOT NULL,
            PRIMARY KEY (run_id, post_uid),
            FOREIGN KEY(run_id) REFERENCES scrape_runs(run_id),
            FOREIGN KEY(post_uid) REFERENCES posts(post_uid)
        );

        CREATE TABLE IF NOT EXISTS run_comments (
            run_id TEXT NOT NULL,
            comment_uid TEXT NOT NULL,
            PRIMARY KEY (run_id, comment_uid),
            FOREIGN KEY(run_id) REFERENCES scrape_runs(run_id),
            FOREIGN KEY(comment_uid) REFERENCES comments(comment_uid)
        );

        CREATE INDEX IF NOT EXISTS idx_posts_source_id
            ON posts(source_id);
        CREATE INDEX IF NOT EXISTS idx_comments_post_uid
            ON comments(post_uid);
        CREATE INDEX IF NOT EXISTS idx_comments_source_id
            ON comments(source_id);
        CREATE INDEX IF NOT EXISTS idx_run_sources_run_id
            ON run_sources(run_id);
        CREATE INDEX IF NOT EXISTS idx_run_posts_run_id
            ON run_posts(run_id);
        CREATE INDEX IF NOT EXISTS idx_run_comments_run_id
            ON run_comments(run_id);
        """
    )
    connection.commit()


def create_scrape_run(
    connection: sqlite3.Connection,
    config_snapshot: dict[str, Any],
) -> str:
    """Create a unique collection-run record and return its run ID."""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}_{uuid4().hex[:8]}"
    connection.execute(
        """
        INSERT INTO scrape_runs (
            run_id, started_at, status, config_json
        ) VALUES (?, ?, 'running', ?)
        """,
        (
            run_id,
            utc_now_iso(),
            json.dumps(config_snapshot, ensure_ascii=False, sort_keys=True),
        ),
    )
    connection.commit()
    return run_id


def finish_scrape_run(
    connection: sqlite3.Connection,
    run_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE scrape_runs
        SET completed_at = ?, status = ?, error_message = ?
        WHERE run_id = ?
        """,
        (utc_now_iso(), status, error_message, run_id),
    )
    connection.commit()


def start_run_source(
    connection: sqlite3.Connection,
    run_id: str,
    source_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO run_sources (
            run_id, source_id, status, started_at
        ) VALUES (?, ?, 'running', ?)
        ON CONFLICT(run_id, source_id) DO UPDATE SET
            status = excluded.status,
            started_at = excluded.started_at,
            completed_at = NULL,
            posts_collected = 0,
            comments_collected = 0,
            error_message = NULL
        """,
        (run_id, source_id, utc_now_iso()),
    )
    connection.commit()


def finish_run_source(
    connection: sqlite3.Connection,
    run_id: str,
    source_id: str,
    status: str,
    posts_collected: int,
    comments_collected: int,
    error_message: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE run_sources
        SET completed_at = ?, status = ?, posts_collected = ?,
            comments_collected = ?, error_message = ?
        WHERE run_id = ? AND source_id = ?
        """,
        (
            utc_now_iso(),
            status,
            posts_collected,
            comments_collected,
            error_message,
            run_id,
            source_id,
        ),
    )
    connection.commit()


def save_source(connection: sqlite3.Connection, source: dict[str, str]) -> None:
    connection.execute(
        """
        INSERT INTO sources (
            source_id, channel_title, channel_url, telegram_username,
            language, source_type, topic_label, toxicity_expected,
            notes, active, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            channel_title = excluded.channel_title,
            channel_url = excluded.channel_url,
            telegram_username = excluded.telegram_username,
            language = excluded.language,
            source_type = excluded.source_type,
            topic_label = excluded.topic_label,
            toxicity_expected = excluded.toxicity_expected,
            notes = excluded.notes,
            active = excluded.active,
            scraped_at = excluded.scraped_at
        """,
        (
            source.get("source_id"),
            source.get("channel_title"),
            source.get("channel_url"),
            source.get("telegram_username"),
            source.get("language"),
            source.get("source_type"),
            source.get("topic_label"),
            source.get("toxicity_expected"),
            source.get("notes"),
            source.get("active", "true"),
            utc_now_iso(),
        ),
    )
    connection.commit()


def _reactions_to_json(message: Any) -> str | None:
    reactions = getattr(message, "reactions", None)
    if not reactions:
        return None
    try:
        return json.dumps(reactions.to_dict(), ensure_ascii=False)
    except (AttributeError, TypeError, ValueError):
        return str(reactions)


def _comments_count(message: Any) -> int | None:
    replies = getattr(message, "replies", None)
    return getattr(replies, "replies", None) if replies else None


def save_post(
    connection: sqlite3.Connection,
    source: dict[str, str],
    channel_username: str,
    post: Any,
    run_id: str | None = None,
) -> str:
    clean_channel = channel_username.removeprefix("@")
    post_uid = f"{clean_channel}:{post.id}"
    post_url = f"https://t.me/{clean_channel}/{post.id}"

    connection.execute(
        """
        INSERT INTO posts (
            post_uid, source_id, channel_username, post_id, post_url,
            date, text, views, forwards, reactions_json, comments_count,
            scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_uid) DO UPDATE SET
            source_id = excluded.source_id,
            channel_username = excluded.channel_username,
            post_id = excluded.post_id,
            post_url = excluded.post_url,
            date = excluded.date,
            text = excluded.text,
            views = excluded.views,
            forwards = excluded.forwards,
            reactions_json = excluded.reactions_json,
            comments_count = excluded.comments_count,
            scraped_at = excluded.scraped_at
        """,
        (
            post_uid,
            source.get("source_id"),
            channel_username,
            post.id,
            post_url,
            post.date.isoformat() if post.date else None,
            post.message,
            getattr(post, "views", None),
            getattr(post, "forwards", None),
            _reactions_to_json(post),
            _comments_count(post),
            utc_now_iso(),
        ),
    )

    if run_id is not None:
        connection.execute(
            "INSERT OR IGNORE INTO run_posts (run_id, post_uid) VALUES (?, ?)",
            (run_id, post_uid),
        )

    return post_uid


def save_comment(
    connection: sqlite3.Connection,
    source: dict[str, str],
    channel_username: str,
    post_uid: str,
    post_id: int,
    comment: Any,
    sender_id: str | None,
    sender_hash: str | None,
    sender_username: str | None,
    run_id: str | None = None,
) -> None:
    clean_channel = channel_username.removeprefix("@")
    comment_uid = f"{clean_channel}:{post_id}:{comment.id}"
    media = getattr(comment, "media", None)
    media_type = type(media).__name__ if media is not None else None

    connection.execute(
        """
        INSERT INTO comments (
            comment_uid, post_uid, source_id, channel_username,
            post_id, comment_id, date, sender_id, sender_hash,
            sender_username, text, media_type, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(comment_uid) DO UPDATE SET
            post_uid = excluded.post_uid,
            source_id = excluded.source_id,
            channel_username = excluded.channel_username,
            post_id = excluded.post_id,
            comment_id = excluded.comment_id,
            date = excluded.date,
            sender_id = excluded.sender_id,
            sender_hash = excluded.sender_hash,
            sender_username = excluded.sender_username,
            text = excluded.text,
            media_type = excluded.media_type,
            scraped_at = excluded.scraped_at
        """,
        (
            comment_uid,
            post_uid,
            source.get("source_id"),
            channel_username,
            post_id,
            comment.id,
            comment.date.isoformat() if comment.date else None,
            sender_id,
            sender_hash,
            sender_username,
            comment.message,
            media_type,
            utc_now_iso(),
        ),
    )

    if run_id is not None:
        connection.execute(
            """
            INSERT OR IGNORE INTO run_comments (run_id, comment_uid)
            VALUES (?, ?)
            """,
            (run_id, comment_uid),
        )

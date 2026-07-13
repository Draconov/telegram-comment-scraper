from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

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

        CREATE INDEX IF NOT EXISTS idx_posts_source_id
            ON posts(source_id);
        CREATE INDEX IF NOT EXISTS idx_comments_post_uid
            ON comments(post_uid);
        CREATE INDEX IF NOT EXISTS idx_comments_source_id
            ON comments(source_id);
        """
    )
    connection.commit()


def save_source(connection: sqlite3.Connection, source: dict[str, str]) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO sources (
            source_id, channel_title, channel_url, telegram_username,
            language, source_type, topic_label, toxicity_expected,
            notes, active, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
) -> str:
    clean_channel = channel_username.removeprefix("@")
    post_uid = f"{clean_channel}:{post.id}"
    post_url = f"https://t.me/{clean_channel}/{post.id}"

    connection.execute(
        """
        INSERT OR REPLACE INTO posts (
            post_uid, source_id, channel_username, post_id, post_url,
            date, text, views, forwards, reactions_json, comments_count,
            scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    connection.commit()
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
) -> None:
    clean_channel = channel_username.removeprefix("@")
    comment_uid = f"{clean_channel}:{post_id}:{comment.id}"
    media = getattr(comment, "media", None)
    media_type = type(media).__name__ if media is not None else None

    connection.execute(
        """
        INSERT OR REPLACE INTO comments (
            comment_uid, post_uid, source_id, channel_username,
            post_id, comment_id, date, sender_id, sender_hash,
            sender_username, text, media_type, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    connection.commit()

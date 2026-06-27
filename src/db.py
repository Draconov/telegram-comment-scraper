import json
import os
import sqlite3
from typing import Any, Dict, Optional

from src.utils import utc_now_iso


def connect_database(path: str) -> sqlite3.Connection:
    directory = os.path.dirname(path)

    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_database(conn: sqlite3.Connection) -> None:
    conn.execute(
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
        )
        """
    )

    conn.execute(
        """
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
        )
        """
    )

    conn.execute(
        """
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
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_posts_source_id
        ON posts(source_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_comments_post_uid
        ON comments(post_uid)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_comments_source_id
        ON comments(source_id)
        """
    )

    conn.commit()


def save_source(conn: sqlite3.Connection, source: Dict[str, str]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO sources (
            source_id,
            channel_title,
            channel_url,
            telegram_username,
            language,
            source_type,
            topic_label,
            toxicity_expected,
            notes,
            active,
            scraped_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    conn.commit()


def _message_reactions_to_json(message: Any) -> Optional[str]:
    reactions = getattr(message, "reactions", None)

    if not reactions:
        return None

    try:
        return json.dumps(reactions.to_dict(), ensure_ascii=False)
    except Exception:
        return str(reactions)


def _message_comments_count(message: Any) -> Optional[int]:
    replies = getattr(message, "replies", None)

    if not replies:
        return None

    return getattr(replies, "replies", None)


def save_post(
    conn: sqlite3.Connection,
    source: Dict[str, str],
    channel_username: str,
    post: Any,
) -> str:
    clean_channel = channel_username.replace("@", "")
    post_uid = f"{clean_channel}:{post.id}"
    post_url = f"https://t.me/{clean_channel}/{post.id}"

    conn.execute(
        """
        INSERT OR REPLACE INTO posts (
            post_uid,
            source_id,
            channel_username,
            post_id,
            post_url,
            date,
            text,
            views,
            forwards,
            reactions_json,
            comments_count,
            scraped_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            _message_reactions_to_json(post),
            _message_comments_count(post),
            utc_now_iso(),
        ),
    )

    conn.commit()
    return post_uid


def save_comment(
    conn: sqlite3.Connection,
    source: Dict[str, str],
    channel_username: str,
    post_uid: str,
    post_id: int,
    comment: Any,
    sender_id: Optional[str],
    sender_hash: Optional[str],
    sender_username: Optional[str],
) -> None:
    clean_channel = channel_username.replace("@", "")
    comment_uid = f"{clean_channel}:{post_id}:{comment.id}"

    media_type = None
    if getattr(comment, "media", None):
        media_type = type(comment.media).__name__

    conn.execute(
        """
        INSERT OR REPLACE INTO comments (
            comment_uid,
            post_uid,
            source_id,
            channel_username,
            post_id,
            comment_id,
            date,
            sender_id,
            sender_hash,
            sender_username,
            text,
            media_type,
            scraped_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    conn.commit()
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4


def _unique_destination_path(base_directory: Path, name: str) -> Path:
    base_directory.mkdir(parents=True, exist_ok=True)
    destination = base_directory / name
    duplicate_number = 2

    while destination.exists():
        destination = base_directory / f"{name}_{duplicate_number:02d}"
        duplicate_number += 1

    return destination


def _temporary_export_directory(destination: Path) -> Path:
    temporary = destination.parent / (
        f".{destination.name}.tmp_{uuid4().hex[:8]}"
    )
    temporary.mkdir(parents=False, exist_ok=False)
    return temporary


def _write_query_to_csv(
    connection: sqlite3.Connection,
    query: str,
    parameters: Sequence[Any],
    output_path: Path,
) -> dict[str, Any]:
    cursor = connection.execute(query, parameters)
    fieldnames = [column[0] for column in cursor.description or []]
    rows = cursor.fetchall()

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fieldnames)
        writer.writerows(tuple(row) for row in rows)

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    print(f"Exported {len(rows)} rows: {output_path}")
    return {
        "file": output_path.name,
        "rows": len(rows),
        "sha256": digest,
    }


def _run_record(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM scrape_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown scrape run: {run_id}")
    return row


def latest_completed_run_id(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        """
        SELECT run_id
        FROM scrape_runs
        WHERE status = 'completed'
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("No completed scrape runs are available to export.")
    return str(row[0])


def list_scrape_runs(database_path: str) -> list[dict[str, Any]]:
    database = Path(database_path)
    if not database.exists():
        raise FileNotFoundError(
            f"Database not found: {database}. Run the scraper first."
        )

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT
                r.run_id,
                r.started_at,
                r.completed_at,
                r.status,
                COUNT(DISTINCT rp.post_uid) AS posts,
                COUNT(DISTINCT rc.comment_uid) AS comments
            FROM scrape_runs AS r
            LEFT JOIN run_posts AS rp ON r.run_id = rp.run_id
            LEFT JOIN run_comments AS rc ON r.run_id = rc.run_id
            GROUP BY r.run_id
            ORDER BY r.started_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def export_scrape_run(
    database_path: str,
    output_dir: str,
    run_id: str | None = None,
) -> Path:
    """Export only records observed during one specific scrape run."""

    database = Path(database_path)
    if not database.exists():
        raise FileNotFoundError(
            f"Database not found: {database}. Run the scraper first."
        )

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        selected_run_id = run_id or latest_completed_run_id(connection)
        run = _run_record(connection, selected_run_id)
        destination = _unique_destination_path(
            Path(output_dir),
            selected_run_id,
        )
        temporary = _temporary_export_directory(destination)

        exported_files: list[dict[str, Any]] = []

        exported_files.append(
            _write_query_to_csv(
                connection,
                """
                SELECT ? AS scrape_run_id, s.*
                FROM sources AS s
                INNER JOIN run_sources AS rs ON s.source_id = rs.source_id
                WHERE rs.run_id = ?
                ORDER BY s.source_id
                """,
                (selected_run_id, selected_run_id),
                temporary / "sources.csv",
            )
        )
        exported_files.append(
            _write_query_to_csv(
                connection,
                """
                SELECT ? AS scrape_run_id, p.*
                FROM posts AS p
                INNER JOIN run_posts AS rp ON p.post_uid = rp.post_uid
                WHERE rp.run_id = ?
                ORDER BY p.source_id, p.date, p.post_id
                """,
                (selected_run_id, selected_run_id),
                temporary / "posts.csv",
            )
        )
        exported_files.append(
            _write_query_to_csv(
                connection,
                """
                SELECT ? AS scrape_run_id, c.*
                FROM comments AS c
                INNER JOIN run_comments AS rc ON c.comment_uid = rc.comment_uid
                WHERE rc.run_id = ?
                ORDER BY c.source_id, c.post_id, c.date, c.comment_id
                """,
                (selected_run_id, selected_run_id),
                temporary / "comments.csv",
            )
        )
        exported_files.append(
            _write_query_to_csv(
                connection,
                """
                SELECT
                    ? AS scrape_run_id,
                    c.comment_uid,
                    c.post_uid,
                    c.source_id,
                    s.channel_title,
                    s.telegram_username,
                    s.language,
                    s.source_type,
                    s.topic_label,
                    s.toxicity_expected,
                    c.post_id,
                    c.comment_id,
                    c.date AS comment_date,
                    c.text AS comment_text,
                    c.sender_hash,
                    p.date AS post_date,
                    p.text AS post_text,
                    p.post_url
                FROM run_comments AS rc
                INNER JOIN comments AS c ON rc.comment_uid = c.comment_uid
                LEFT JOIN posts AS p ON c.post_uid = p.post_uid
                LEFT JOIN sources AS s ON c.source_id = s.source_id
                WHERE rc.run_id = ?
                ORDER BY c.source_id, c.post_id, c.date, c.comment_id
                """,
                (selected_run_id, selected_run_id),
                temporary / "comments_with_source_labels.csv",
            )
        )
        exported_files.append(
            _write_query_to_csv(
                connection,
                """
                SELECT
                    run_id,
                    source_id,
                    status,
                    started_at,
                    completed_at,
                    posts_collected,
                    comments_collected,
                    error_message
                FROM run_sources
                WHERE run_id = ?
                ORDER BY source_id
                """,
                (selected_run_id,),
                temporary / "run_summary.csv",
            )
        )

        try:
            settings = json.loads(run["config_json"])
        except (TypeError, json.JSONDecodeError):
            settings = {}

        manifest = {
            "schema_version": 1,
            "run_id": selected_run_id,
            "run_status": run["status"],
            "started_at": run["started_at"],
            "completed_at": run["completed_at"],
            "exported_at": datetime.now().astimezone().isoformat(),
            "export_mode": "single_scrape_run",
            "settings": settings,
            "files": exported_files,
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        temporary.rename(destination)

        latest_pointer = Path(output_dir) / "latest_run.txt"
        latest_pointer.write_text(
            f"{destination.name}\n",
            encoding="utf-8",
        )
    except Exception:
        if "temporary" in locals() and temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        connection.close()

    print(f"Run export completed: {destination}")
    return destination


def export_all_tables(database_path: str, output_dir: str) -> Path:
    """Export a cumulative snapshot of the full database."""

    database = Path(database_path)
    if not database.exists():
        raise FileNotFoundError(
            f"Database not found: {database}. Run the scraper first."
        )

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    destination = _unique_destination_path(
        Path(output_dir),
        f"all_data_{timestamp}",
    )
    temporary = _temporary_export_directory(destination)

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        for table_name in (
            "sources",
            "posts",
            "comments",
            "scrape_runs",
            "run_sources",
            "run_posts",
            "run_comments",
        ):
            _write_query_to_csv(
                connection,
                f"SELECT * FROM {table_name}",
                (),
                temporary / f"{table_name}.csv",
            )

        _write_query_to_csv(
            connection,
            """
            SELECT
                c.comment_uid,
                c.post_uid,
                c.source_id,
                s.channel_title,
                s.telegram_username,
                s.language,
                s.source_type,
                s.topic_label,
                s.toxicity_expected,
                c.post_id,
                c.comment_id,
                c.date AS comment_date,
                c.text AS comment_text,
                c.sender_hash,
                p.date AS post_date,
                p.text AS post_text,
                p.post_url
            FROM comments AS c
            LEFT JOIN posts AS p ON c.post_uid = p.post_uid
            LEFT JOIN sources AS s ON c.source_id = s.source_id
            """,
            (),
            temporary / "comments_with_source_labels.csv",
        )
        temporary.rename(destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        connection.close()

    print(f"Cumulative export completed: {destination}")
    return destination

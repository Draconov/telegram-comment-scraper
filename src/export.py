from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterable


def _write_rows_to_csv(
    rows: Iterable[sqlite3.Row],
    output_path: Path,
) -> None:
    materialized = list(rows)
    if not materialized:
        print(f"No rows to export: {output_path}")
        return

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=materialized[0].keys())
        writer.writeheader()
        writer.writerows(dict(row) for row in materialized)
    print(f"Exported: {output_path}")


def export_table(
    connection: sqlite3.Connection,
    table_name: str,
    output_dir: Path,
) -> None:
    allowed_tables = {"sources", "posts", "comments"}
    if table_name not in allowed_tables:
        raise ValueError(f"Unsupported table name: {table_name}")
    rows = connection.execute(f"SELECT * FROM {table_name}").fetchall()
    _write_rows_to_csv(rows, output_dir / f"{table_name}.csv")


def export_comments_with_source_labels(
    connection: sqlite3.Connection,
    output_dir: Path,
) -> None:
    rows = connection.execute(
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
        """
    ).fetchall()
    _write_rows_to_csv(rows, output_dir / "comments_with_source_labels.csv")


def export_all_tables(database_path: str, output_dir: str) -> None:
    database = Path(database_path)
    if not database.exists():
        raise FileNotFoundError(
            f"Database not found: {database}. Run the scraper first."
        )

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        for table_name in ("sources", "posts", "comments"):
            export_table(connection, table_name, destination)
        export_comments_with_source_labels(connection, destination)
    finally:
        connection.close()

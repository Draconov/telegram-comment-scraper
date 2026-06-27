import csv
import os
import sqlite3
from typing import Iterable


def _write_rows_to_csv(
    rows: Iterable[sqlite3.Row],
    output_path: str,
) -> None:
    rows = list(rows)

    if not rows:
        print(f"No rows to export: {output_path}")
        return

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()

        for row in rows:
            writer.writerow(dict(row))

    print(f"Exported: {output_path}")


def export_table(
    conn: sqlite3.Connection,
    table_name: str,
    output_dir: str,
) -> None:
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    output_path = os.path.join(output_dir, f"{table_name}.csv")
    _write_rows_to_csv(rows, output_path)


def export_comments_with_source_labels(
    conn: sqlite3.Connection,
    output_dir: str,
) -> None:
    query = """
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
    FROM comments c
    LEFT JOIN posts p
        ON c.post_uid = p.post_uid
    LEFT JOIN sources s
        ON c.source_id = s.source_id
    """

    rows = conn.execute(query).fetchall()
    output_path = os.path.join(output_dir, "comments_with_source_labels.csv")
    _write_rows_to_csv(rows, output_path)


def export_all_tables(database_path: str, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row

    export_table(conn, "sources", output_dir)
    export_table(conn, "posts", output_dir)
    export_table(conn, "comments", output_dir)
    export_comments_with_source_labels(conn, output_dir)

    conn.close()
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.db import (
    connect_database,
    create_scrape_run,
    finish_run_source,
    finish_scrape_run,
    init_database,
    save_comment,
    save_post,
    save_source,
    start_run_source,
)
from src.export import export_all_tables, export_scrape_run, list_scrape_runs


class ScrapeRunExportTest(unittest.TestCase):
    def test_run_specific_and_cumulative_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "data" / "research.sqlite"
            exports = root / "exports"
            connection = connect_database(database)
            init_database(connection)

            source = {
                "source_id": "src_001",
                "channel_title": "Synthetic Channel",
                "channel_url": "https://t.me/synthetic",
                "telegram_username": "@synthetic",
                "language": "uk",
                "source_type": "synthetic",
                "topic_label": "test",
                "toxicity_expected": "unknown",
                "notes": "SYNTHETIC TEST DATA",
                "active": "true",
            }
            save_source(connection, source)
            run_id = create_scrape_run(
                connection,
                {
                    "scraping": {"posts_per_channel": 1},
                    "privacy": {"hash_sender_ids": True},
                },
            )
            start_run_source(connection, run_id, source["source_id"])

            now = datetime.now(timezone.utc)
            post = SimpleNamespace(
                id=10,
                date=now,
                message="Synthetic post",
                views=5,
                forwards=1,
                reactions=None,
                replies=SimpleNamespace(replies=1),
            )
            post_uid = save_post(
                connection,
                source,
                source["telegram_username"],
                post,
                run_id,
            )
            comment = SimpleNamespace(
                id=20,
                date=now,
                message="Synthetic comment",
                media=None,
            )
            save_comment(
                connection,
                source,
                source["telegram_username"],
                post_uid,
                post.id,
                comment,
                sender_id=None,
                sender_hash="synthetic_hash",
                sender_username=None,
                run_id=run_id,
            )
            connection.commit()
            finish_run_source(
                connection,
                run_id,
                source["source_id"],
                status="completed",
                posts_collected=1,
                comments_collected=1,
            )
            finish_scrape_run(connection, run_id, status="completed")
            connection.close()

            run_export = export_scrape_run(str(database), str(exports), run_id)
            expected = {
                "sources.csv",
                "posts.csv",
                "comments.csv",
                "comments_with_source_labels.csv",
                "run_summary.csv",
                "manifest.json",
            }
            self.assertTrue(expected.issubset({path.name for path in run_export.iterdir()}))

            with (run_export / "comments_with_source_labels.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                comments = list(csv.DictReader(handle))
            self.assertEqual(len(comments), 1)
            self.assertEqual(comments[0]["telegram_username"], "@synthetic")
            self.assertEqual(comments[0]["comment_text"], "Synthetic comment")

            manifest = json.loads((run_export / "manifest.json").read_text("utf-8"))
            self.assertEqual(manifest["run_id"], run_id)
            self.assertNotIn("api_hash", json.dumps(manifest).casefold())
            self.assertNotIn("anonymization_salt", json.dumps(manifest).casefold())

            runs = list_scrape_runs(str(database))
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["posts"], 1)
            self.assertEqual(runs[0]["comments"], 1)

            cumulative = export_all_tables(str(database), str(exports))
            self.assertTrue((cumulative / "comments_with_source_labels.csv").exists())


if __name__ == "__main__":
    unittest.main()

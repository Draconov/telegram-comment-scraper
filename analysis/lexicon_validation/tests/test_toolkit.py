from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class ToolkitEndToEndTest(unittest.TestCase):
    def test_multiline_source_normalization_and_longest_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            export = base / "export"
            export.mkdir()
            write_csv(
                export / "sources.csv",
                ["source_id", "channel_title", "telegram_username"],
                [
                    {
                        "source_id": "src_001",
                        "channel_title": "Channel One",
                        "telegram_username": "@ChannelOne",
                    }
                ],
            )
            write_csv(
                export / "comments_with_source_labels.csv",
                [
                    "comment_uid",
                    "source_id",
                    "channel_title",
                    "telegram_username",
                    "comment_date",
                    "comment_text",
                    "post_text",
                ],
                [
                    {
                        "comment_uid": "c1",
                        "source_id": "src_001",
                        "channel_title": "Channel One",
                        "telegram_username": "@ChannelOne",
                        "comment_date": "2026-01-01",
                        "comment_text": "Перша лінія\nздохни тварюка",
                        "post_text": "Parent post",
                    },
                    {
                        "comment_uid": "c2",
                        "source_id": "src_001",
                        "channel_title": "Channel One",
                        "telegram_username": "@ChannelOne",
                        "comment_date": "2026-01-02",
                        "comment_text": "Нейтральний текст",
                        "post_text": "Parent post",
                    },
                ],
            )
            write_csv(
                export / "posts.csv",
                ["post_uid", "source_id", "channel_username", "date", "text"],
                [
                    {
                        "post_uid": "p1",
                        "source_id": "src_001",
                        "channel_username": "@ChannelOne",
                        "date": "2026-01-01",
                        "text": "Бля, пост",
                    }
                ],
            )
            dictionary = base / "dictionary.csv"
            write_csv(
                dictionary,
                ["term", "category", "primary_aspect"],
                [
                    {
                        "term": "здохни тварюка",
                        "category": "threat",
                        "primary_aspect": "Threat / Harm",
                    },
                    {
                        "term": "здохни",
                        "category": "threat",
                        "primary_aspect": "Threat / Harm",
                    },
                    {
                        "term": "бля",
                        "category": "masked",
                        "primary_aspect": "Obfuscated offensive form",
                    },
                ],
            )
            analysis = base / "analysis"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "analysis.lexicon_validation.analyze_scraping_results",
                    "--input",
                    str(export),
                    "--dictionary",
                    str(dictionary),
                    "--include-posts",
                    "--output",
                    str(analysis),
                ],
                check=True,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            summary = json.loads((analysis / "analysis_summary.json").read_text("utf-8"))
            self.assertEqual(summary["counts"]["total_messages_analyzed"], 3)
            self.assertEqual(summary["quality"]["rows_with_extra_fields"], 0)
            self.assertEqual(summary["quality"]["suspicious_source_values"], [])

            with (analysis / "source_summary.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                sources = list(csv.DictReader(handle))
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["source"], "@channelone")
            self.assertEqual(sources[0]["total_messages_analyzed"], "3")

            with (analysis / "messages_with_matches.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                matches = list(csv.DictReader(handle))
            threat = next(row for row in matches if row["analysis_message_id"] == "c1")
            self.assertEqual(threat["matched_terms"], "здохни тварюка")
            self.assertIn("\n", threat["comment_text"])

            sample = base / "sample"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "analysis.lexicon_validation.prepare_validation_sample",
                    "--input",
                    str(export),
                    "--dictionary",
                    str(dictionary),
                    "--include-posts",
                    "--matched-size",
                    "2",
                    "--unmatched-size",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    str(sample),
                ],
                check=True,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            with (sample / "validation_sample_blinded.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                blinded = list(csv.DictReader(handle))
            self.assertEqual(len(blinded), 3)
            threat_sample = next(row for row in blinded if "здохни" in row["text"])
            self.assertEqual(threat_sample["parent_post_text"], "Parent post")

            # Complete a small first-annotator file with one true positive,
            # one false positive, and one true negative.
            for row in blinded:
                if "здохни" in row["text"]:
                    row["context_label"] = "offensive"
                else:
                    row["context_label"] = "non_offensive"
                row["annotator_id"] = "annotator_a"
            annotations = base / "annotations.csv"
            write_csv(annotations, list(blinded[0]), blinded)

            second = base / "second.csv"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "analysis.lexicon_validation.create_second_annotator_subset",
                    "--input",
                    str(annotations),
                    "--count",
                    "2",
                    "--seed",
                    "7",
                    "--output",
                    str(second),
                ],
                check=True,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            second_fields, second_rows = None, None
            with second.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                second_fields = reader.fieldnames
                second_rows = list(reader)
            self.assertEqual(len(second_rows), 2)
            # Keep the same labels; agreement should be perfect on overlap.
            write_csv(second, second_fields, second_rows)

            metrics = base / "metrics"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "analysis.lexicon_validation.calculate_validation_metrics",
                    "--annotations",
                    str(annotations),
                    "--second-annotations",
                    str(second),
                    "--key",
                    str(sample / "validation_sample_key.csv"),
                    "--output",
                    str(metrics),
                ],
                check=True,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            report = json.loads((metrics / "validation_metrics.json").read_text("utf-8"))
            self.assertEqual(report["unweighted_metrics"]["true_positive"], 1)
            self.assertEqual(report["unweighted_metrics"]["false_positive"], 1)
            self.assertEqual(report["unweighted_metrics"]["true_negative"], 1)
            self.assertEqual(
                report["inter_annotator_agreement"]["observed_agreement"], 1.0
            )


if __name__ == "__main__":
    unittest.main()

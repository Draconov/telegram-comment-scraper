from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from lexicon_common import (
    CsvQuality,
    LexiconEntry,
    compile_matcher,
    discover_inputs,
    dominant_term_index,
    iter_messages,
    join_unique,
    load_dictionary_entries,
    match_message,
    percent,
    per_thousand,
    sha256,
    unique_output_directory,
    write_csv,
)

VERSION = "2.0.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze Telegram scraper exports with dictionary metadata, canonical "
            "source normalization, multiline-safe CSV reading, and portable reports."
        )
    )
    parser.add_argument("--input", required=True, help="Export folder or CSV file.")
    parser.add_argument(
        "--dictionary",
        required=True,
        help=(
            "Dictionary TXT/CSV/TSV/JSON. Use the metadata CSV to obtain category "
            "and aspect statistics."
        ),
    )
    parser.add_argument("--output", help="Optional output folder.")
    parser.add_argument(
        "--include-posts",
        action="store_true",
        help="Analyze posts.csv in addition to comments.",
    )
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument(
        "--match-mode",
        choices=("whole-term", "substring"),
        default="whole-term",
    )
    parser.add_argument("--text-column")
    parser.add_argument("--dictionary-column")
    parser.add_argument(
        "--omit-message-text",
        action="store_true",
        help="Exclude full message text from messages_with_matches.csv.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def _metadata_rows(
    entries: list[LexiconEntry],
    occurrences: Counter[int],
    message_counts: Counter[int],
    type_occurrences: dict[int, Counter[str]],
    type_messages: dict[int, Counter[str]],
) -> list[dict[str, Any]]:
    ranked = sorted(
        range(len(entries)),
        key=lambda index: (-occurrences[index], entries[index].normalized),
    )
    rows: list[dict[str, Any]] = []
    for rank, index in enumerate(ranked, start=1):
        entry = entries[index]
        rows.append(
            {
                "rank": rank,
                **entry.as_metadata(),
                "total_occurrences": occurrences[index],
                "messages_with_term": message_counts[index],
                "comment_occurrences": type_occurrences[index]["comment"],
                "comment_messages": type_messages[index]["comment"],
                "post_occurrences": type_occurrences[index]["post"],
                "post_messages": type_messages[index]["post"],
                "other_occurrences": type_occurrences[index]["message"],
                "other_messages": type_messages[index]["message"],
            }
        )
    return rows


def _dimension_rows(
    dimension_name: str,
    occurrences: Counter[str],
    message_counts: Counter[str],
    type_occurrences: dict[str, Counter[str]],
    type_messages: dict[str, Counter[str]],
    total_messages: int,
) -> list[dict[str, Any]]:
    values = sorted(
        set(occurrences) | set(message_counts),
        key=lambda value: (-occurrences[value], value),
    )
    return [
        {
            dimension_name: value,
            "total_occurrences": occurrences[value],
            "messages_with_value": message_counts[value],
            "messages_with_value_percentage": percent(
                message_counts[value], total_messages
            ),
            "occurrences_per_1000_messages": per_thousand(
                occurrences[value], total_messages
            ),
            "comment_occurrences": type_occurrences[value]["comment"],
            "comment_messages": type_messages[value]["comment"],
            "post_occurrences": type_occurrences[value]["post"],
            "post_messages": type_messages[value]["post"],
        }
        for value in values
    ]


def analyze(args: argparse.Namespace) -> Path:
    input_path = Path(args.input)
    dictionary_path = Path(args.dictionary)
    specs, source_map = discover_inputs(
        input_path,
        include_posts=args.include_posts,
        text_override=args.text_column,
    )
    entries, duplicates = load_dictionary_entries(
        dictionary_path,
        case_sensitive=args.case_sensitive,
        dictionary_column=args.dictionary_column,
    )
    normalized_to_index = {
        entry.normalized: index for index, entry in enumerate(entries)
    }
    matcher = compile_matcher(entries, args.match_mode)

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    default_parent = input_path if input_path.is_dir() else input_path.parent
    base = Path(args.output) if args.output else default_parent / f"lexicon_analysis_{timestamp}"
    destination = unique_output_directory(base)

    quality = CsvQuality()
    term_occurrences: Counter[int] = Counter()
    term_messages: Counter[int] = Counter()
    term_type_occurrences: dict[int, Counter[str]] = defaultdict(Counter)
    term_type_messages: dict[int, Counter[str]] = defaultdict(Counter)

    category_occurrences: Counter[str] = Counter()
    category_messages: Counter[str] = Counter()
    category_type_occurrences: dict[str, Counter[str]] = defaultdict(Counter)
    category_type_messages: dict[str, Counter[str]] = defaultdict(Counter)

    aspect_occurrences: Counter[str] = Counter()
    aspect_messages: Counter[str] = Counter()
    aspect_type_occurrences: dict[str, Counter[str]] = defaultdict(Counter)
    aspect_type_messages: dict[str, Counter[str]] = defaultdict(Counter)

    source_stats: dict[str, dict[str, Any]] = {}
    source_term_occurrences: Counter[tuple[str, int]] = Counter()
    source_term_messages: Counter[tuple[str, int]] = Counter()
    source_category_occurrences: Counter[tuple[str, str]] = Counter()
    source_category_messages: Counter[tuple[str, str]] = Counter()
    source_aspect_occurrences: Counter[tuple[str, str]] = Counter()
    source_aspect_messages: Counter[tuple[str, str]] = Counter()

    matched_rows: list[dict[str, Any]] = []
    total_messages = 0
    messages_with_matches = 0
    total_occurrences = 0
    type_counts: Counter[str] = Counter()

    try:
        for message in iter_messages(specs, source_map, quality=quality):
            total_messages += 1
            type_counts[message.message_type] += 1
            source = source_stats.setdefault(
                message.source,
                {
                    "source": message.source,
                    "source_id": message.source_id,
                    "telegram_username": message.telegram_username,
                    "channel_title": message.channel_title,
                    "total_messages_analyzed": 0,
                    "messages_with_match": 0,
                    "total_occurrences": 0,
                    "detected_terms": set(),
                },
            )
            source["total_messages_analyzed"] += 1

            per_message = match_message(
                message.text,
                matcher,
                normalized_to_index,
                args.case_sensitive,
            )
            if not per_message:
                continue

            messages_with_matches += 1
            message_occurrences = sum(per_message.values())
            total_occurrences += message_occurrences
            source["messages_with_match"] += 1
            source["total_occurrences"] += message_occurrences
            source["detected_terms"].update(per_message)

            message_categories: Counter[str] = Counter()
            message_aspects: Counter[str] = Counter()
            for term_index, count in per_message.items():
                entry = entries[term_index]
                term_occurrences[term_index] += count
                term_messages[term_index] += 1
                term_type_occurrences[term_index][message.message_type] += count
                term_type_messages[term_index][message.message_type] += 1
                source_term_occurrences[(message.source, term_index)] += count
                source_term_messages[(message.source, term_index)] += 1

                if entry.category:
                    message_categories[entry.category] += count
                if entry.primary_aspect:
                    message_aspects[entry.primary_aspect] += count

            for category, count in message_categories.items():
                category_occurrences[category] += count
                category_messages[category] += 1
                category_type_occurrences[category][message.message_type] += count
                category_type_messages[category][message.message_type] += 1
                source_category_occurrences[(message.source, category)] += count
                source_category_messages[(message.source, category)] += 1

            for aspect, count in message_aspects.items():
                aspect_occurrences[aspect] += count
                aspect_messages[aspect] += 1
                aspect_type_occurrences[aspect][message.message_type] += count
                aspect_type_messages[aspect][message.message_type] += 1
                source_aspect_occurrences[(message.source, aspect)] += count
                source_aspect_messages[(message.source, aspect)] += 1

            dominant_index = dominant_term_index(per_message, entries)
            dominant_entry = entries[dominant_index] if dominant_index is not None else None
            matched_terms = [entries[index].term for index in per_message]
            match_counts = {
                entries[index].term: count for index, count in per_message.items()
            }
            analysis_fields: dict[str, Any] = {
                "analysis_message_type": message.message_type,
                "analysis_message_id": message.message_id,
                "analysis_source": message.source,
                "analysis_source_id": message.source_id,
                "analysis_telegram_username": message.telegram_username,
                "analysis_channel_title": message.channel_title,
                "analysis_date": message.date,
                "analysis_url": message.url,
                "analysis_input_file": message.input_file,
                "matched_terms": " | ".join(matched_terms),
                "matched_categories": join_unique(
                    entries[index].category for index in per_message
                ),
                "matched_primary_aspects": join_unique(
                    entries[index].primary_aspect for index in per_message
                ),
                "matched_secondary_aspects": join_unique(
                    entries[index].secondary_aspect for index in per_message
                ),
                "dominant_term": dominant_entry.term if dominant_entry else "",
                "dominant_category": dominant_entry.category if dominant_entry else "",
                "dominant_primary_aspect": (
                    dominant_entry.primary_aspect if dominant_entry else ""
                ),
                "unique_matched_terms": len(per_message),
                "total_dictionary_occurrences": message_occurrences,
                "match_counts_json": json.dumps(
                    match_counts, ensure_ascii=False, sort_keys=True
                ),
            }
            original = dict(message.original_row)
            if args.omit_message_text:
                for field in ("comment_text", "message_text", "text", "post_text", "body"):
                    original.pop(field, None)
            matched_rows.append({**analysis_fields, **original})

        word_rows = _metadata_rows(
            entries,
            term_occurrences,
            term_messages,
            term_type_occurrences,
            term_type_messages,
        )
        category_rows = _dimension_rows(
            "category",
            category_occurrences,
            category_messages,
            category_type_occurrences,
            category_type_messages,
            total_messages,
        )
        aspect_rows = _dimension_rows(
            "primary_aspect",
            aspect_occurrences,
            aspect_messages,
            aspect_type_occurrences,
            aspect_type_messages,
            total_messages,
        )

        source_rows: list[dict[str, Any]] = []
        for item in sorted(source_stats.values(), key=lambda row: row["source"]):
            total = int(item["total_messages_analyzed"])
            matched = int(item["messages_with_match"])
            source_rows.append(
                {
                    "source": item["source"],
                    "source_id": item["source_id"],
                    "telegram_username": item["telegram_username"],
                    "channel_title": item["channel_title"],
                    "total_messages_analyzed": total,
                    "messages_with_match": matched,
                    "messages_without_match": total - matched,
                    "matched_message_percentage": percent(matched, total),
                    "total_dictionary_occurrences": item["total_occurrences"],
                    "occurrences_per_1000_messages": per_thousand(
                        item["total_occurrences"], total
                    ),
                    "unique_dictionary_terms_detected": len(item["detected_terms"]),
                }
            )

        source_term_rows = []
        for (source_name, index), count in sorted(
            source_term_occurrences.items(),
            key=lambda pair: (pair[0][0], -pair[1], entries[pair[0][1]].normalized),
        ):
            source_term_rows.append(
                {
                    "source": source_name,
                    **entries[index].as_metadata(),
                    "total_occurrences": count,
                    "messages_with_term": source_term_messages[(source_name, index)],
                }
            )

        category_source_rows = [
            {
                "source": source,
                "category": category,
                "total_occurrences": count,
                "messages_with_category": source_category_messages[(source, category)],
            }
            for (source, category), count in sorted(
                source_category_occurrences.items(),
                key=lambda pair: (pair[0][0], -pair[1], pair[0][1]),
            )
        ]
        aspect_source_rows = [
            {
                "source": source,
                "primary_aspect": aspect,
                "total_occurrences": count,
                "messages_with_aspect": source_aspect_messages[(source, aspect)],
            }
            for (source, aspect), count in sorted(
                source_aspect_occurrences.items(),
                key=lambda pair: (pair[0][0], -pair[1], pair[0][1]),
            )
        ]

        analysis_columns = [
            "analysis_message_type",
            "analysis_message_id",
            "analysis_source",
            "analysis_source_id",
            "analysis_telegram_username",
            "analysis_channel_title",
            "analysis_date",
            "analysis_url",
            "analysis_input_file",
            "matched_terms",
            "matched_categories",
            "matched_primary_aspects",
            "matched_secondary_aspects",
            "dominant_term",
            "dominant_category",
            "dominant_primary_aspect",
            "unique_matched_terms",
            "total_dictionary_occurrences",
            "match_counts_json",
        ]
        for spec in specs:
            for field in spec.fieldnames:
                if field not in analysis_columns:
                    analysis_columns.append(field)
        if args.omit_message_text:
            analysis_columns = [
                field
                for field in analysis_columns
                if field not in {"comment_text", "message_text", "text", "post_text", "body"}
            ]

        word_fields = [
            "rank",
            "dictionary_term",
            "normalized_term",
            "category",
            "meaning",
            "dictionary_source",
            "primary_aspect",
            "secondary_aspect",
            "annotation_notes",
            "total_occurrences",
            "messages_with_term",
            "comment_occurrences",
            "comment_messages",
            "post_occurrences",
            "post_messages",
            "other_occurrences",
            "other_messages",
        ]
        dimension_fields = [
            "total_occurrences",
            "messages_with_value",
            "messages_with_value_percentage",
            "occurrences_per_1000_messages",
            "comment_occurrences",
            "comment_messages",
            "post_occurrences",
            "post_messages",
        ]

        paths = {
            "word_frequencies": destination / "word_frequencies.csv",
            "messages_with_matches": destination / "messages_with_matches.csv",
            "source_summary": destination / "source_summary.csv",
            "word_frequencies_by_source": destination / "word_frequencies_by_source.csv",
            "category_summary": destination / "category_summary.csv",
            "primary_aspect_summary": destination / "primary_aspect_summary.csv",
            "category_by_source": destination / "category_by_source.csv",
            "primary_aspect_by_source": destination / "primary_aspect_by_source.csv",
        }
        write_csv(paths["word_frequencies"], word_fields, word_rows)
        write_csv(paths["messages_with_matches"], analysis_columns, matched_rows)
        write_csv(
            paths["source_summary"],
            [
                "source",
                "source_id",
                "telegram_username",
                "channel_title",
                "total_messages_analyzed",
                "messages_with_match",
                "messages_without_match",
                "matched_message_percentage",
                "total_dictionary_occurrences",
                "occurrences_per_1000_messages",
                "unique_dictionary_terms_detected",
            ],
            source_rows,
        )
        write_csv(
            paths["word_frequencies_by_source"],
            [
                "source",
                "dictionary_term",
                "normalized_term",
                "category",
                "meaning",
                "dictionary_source",
                "primary_aspect",
                "secondary_aspect",
                "annotation_notes",
                "total_occurrences",
                "messages_with_term",
            ],
            source_term_rows,
        )
        write_csv(paths["category_summary"], ["category", *dimension_fields], category_rows)
        write_csv(
            paths["primary_aspect_summary"],
            ["primary_aspect", *dimension_fields],
            aspect_rows,
        )
        write_csv(
            paths["category_by_source"],
            ["source", "category", "total_occurrences", "messages_with_category"],
            category_source_rows,
        )
        write_csv(
            paths["primary_aspect_by_source"],
            ["source", "primary_aspect", "total_occurrences", "messages_with_aspect"],
            aspect_source_rows,
        )

        snapshot = destination / f"dictionary_snapshot{dictionary_path.suffix}"
        shutil.copy2(dictionary_path, snapshot)

        suspicious = [
            {"source": source, "rows": count}
            for source, count in quality.suspicious_sources.most_common()
        ]
        summary = {
            "schema_version": 2,
            "analyzer_version": VERSION,
            "analyzed_at": datetime.now().astimezone().isoformat(),
            "path_policy": "portable file names only; no personal absolute paths",
            "input": {
                "requested_path": input_path.name,
                "files": [
                    {
                        "file": spec.path.name,
                        "sha256": sha256(spec.path),
                        "message_type": spec.message_type,
                        "text_column": spec.text_column,
                    }
                    for spec in specs
                ],
            },
            "dictionary": {
                "file": dictionary_path.name,
                "sha256": sha256(dictionary_path),
                "entries": len(entries),
                "duplicate_entries_removed": duplicates,
                "metadata_available": any(
                    entry.category or entry.primary_aspect for entry in entries
                ),
            },
            "matching": {
                "mode": args.match_mode,
                "case_sensitive": args.case_sensitive,
                "unicode_normalization": "NFKC",
                "apostrophe_normalization": True,
                "hyphen_normalization": True,
                "multiword_whitespace_normalization": True,
                "overlap_policy": "longest alternative wins at the same position",
                "lemmatization": False,
            },
            "counts": {
                "total_messages_analyzed": total_messages,
                "comments_analyzed": type_counts["comment"],
                "posts_analyzed": type_counts["post"],
                "other_messages_analyzed": type_counts["message"],
                "messages_with_dictionary_match": messages_with_matches,
                "messages_without_dictionary_match": total_messages - messages_with_matches,
                "matched_message_percentage": percent(messages_with_matches, total_messages),
                "total_dictionary_occurrences": total_occurrences,
                "unique_dictionary_terms_detected": sum(
                    1 for index in range(len(entries)) if term_occurrences[index] > 0
                ),
            },
            "quality": {
                "csv_rows_read": quality.rows_read,
                "rows_with_extra_fields": quality.rows_with_extra_fields,
                "rows_with_missing_fields": quality.rows_with_missing_fields,
                "rows_with_unknown_source": quality.unknown_source_rows,
                "suspicious_source_values": suspicious,
                "multiline_csv_fields_preserved": True,
            },
            "outputs": {name: path.name for name, path in paths.items()},
        }
        (destination / "analysis_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    print(
        f"Analyzed {total_messages} messages; {messages_with_matches} matched "
        f"({percent(messages_with_matches, total_messages)}%)."
    )
    print(f"Results: {destination}")
    return destination


def main() -> int:
    args = build_parser().parse_args()
    try:
        analyze(args)
    except (FileNotFoundError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

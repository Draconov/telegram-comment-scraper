from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from lexicon_common import (
    allocate_stratified_sample,
    compile_matcher,
    discover_inputs,
    dominant_term_index,
    iter_messages,
    join_unique,
    load_dictionary_entries,
    match_message,
    reservoir_consider,
    unique_output_directory,
    write_csv,
)

VERSION = "1.0.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a deterministic, stratified, blinded validation sample from "
            "Telegram scraper exports."
        )
    )
    parser.add_argument("--input", required=True, help="Scrape-run export folder.")
    parser.add_argument("--dictionary", required=True, help="Metadata dictionary CSV.")
    parser.add_argument("--output", help="Optional output folder.")
    parser.add_argument("--include-posts", action="store_true")
    parser.add_argument("--matched-size", type=int, default=400)
    parser.add_argument("--unmatched-size", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument(
        "--match-mode", choices=("whole-term", "substring"), default="whole-term"
    )
    parser.add_argument("--dictionary-column")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def frequency_band(messages_with_term: int) -> str:
    if messages_with_term >= 100:
        return "high_100_plus"
    if messages_with_term >= 10:
        return "medium_10_99"
    return "low_1_9"


def matched_stratum(message_type: str, aspect: str, band: str) -> str:
    return f"matched::{message_type}::{aspect or 'Unspecified'}::{band}"


def unmatched_stratum(message_type: str, source: str) -> str:
    return f"unmatched::{message_type}::{source}"


def build_candidate(message: Any, entries: Any, per_message: Counter[int]) -> dict[str, Any]:
    dominant_index = dominant_term_index(per_message, entries)
    dominant = entries[dominant_index] if dominant_index is not None else None
    return {
        "message_type": message.message_type,
        "message_id": message.message_id,
        "source": message.source,
        "source_id": message.source_id,
        "telegram_username": message.telegram_username,
        "channel_title": message.channel_title,
        "date": message.date,
        "url": message.url,
        "text": message.text,
        "parent_post_text": message.original_row.get("post_text", ""),
        "parent_post_date": message.original_row.get("post_date", ""),
        "dictionary_prediction": 1 if per_message else 0,
        "matched_terms": " | ".join(entries[index].term for index in per_message),
        "matched_categories": join_unique(entries[index].category for index in per_message),
        "matched_primary_aspects": join_unique(
            entries[index].primary_aspect for index in per_message
        ),
        "dominant_term": dominant.term if dominant else "",
        "dominant_category": dominant.category if dominant else "",
        "dominant_primary_aspect": dominant.primary_aspect if dominant else "",
        "total_dictionary_occurrences": sum(per_message.values()),
    }


def prepare(args: argparse.Namespace) -> Path:
    input_path = Path(args.input)
    dictionary_path = Path(args.dictionary)
    specs, source_map = discover_inputs(input_path, include_posts=args.include_posts)
    entries, duplicates = load_dictionary_entries(
        dictionary_path,
        case_sensitive=args.case_sensitive,
        dictionary_column=args.dictionary_column,
    )
    normalized_to_index = {entry.normalized: i for i, entry in enumerate(entries)}
    matcher = compile_matcher(entries, args.match_mode)

    # Pass 1: term frequencies, needed for high/medium/low matched strata.
    term_message_counts: Counter[int] = Counter()
    total_messages = 0
    matched_population = 0
    for message in iter_messages(specs, source_map):
        total_messages += 1
        per_message = match_message(
            message.text, matcher, normalized_to_index, args.case_sensitive
        )
        if per_message:
            matched_population += 1
            for index in per_message:
                term_message_counts[index] += 1

    # Pass 2: exact stratum population sizes.
    populations: Counter[str] = Counter()
    for message in iter_messages(specs, source_map):
        per_message = match_message(
            message.text, matcher, normalized_to_index, args.case_sensitive
        )
        if per_message:
            dominant_index = dominant_term_index(per_message, entries)
            aspect = entries[dominant_index].primary_aspect if dominant_index is not None else ""
            band = frequency_band(term_message_counts[dominant_index]) if dominant_index is not None else "low_1_9"
            stratum = matched_stratum(message.message_type, aspect, band)
        else:
            stratum = unmatched_stratum(message.message_type, message.source)
        populations[stratum] += 1

    matched_populations = {k: v for k, v in populations.items() if k.startswith("matched::")}
    unmatched_populations = {k: v for k, v in populations.items() if k.startswith("unmatched::")}
    matched_allocation = allocate_stratified_sample(
        matched_populations, args.matched_size, minimum_per_stratum=1
    )
    unmatched_allocation = allocate_stratified_sample(
        unmatched_populations, args.unmatched_size, minimum_per_stratum=1
    )
    allocation = {**matched_allocation, **unmatched_allocation}

    # Pass 3: bounded reservoir sampling within every stratum.
    rng = random.Random(args.seed)
    reservoirs: dict[str, list[dict[str, Any]]] = {}
    seen: Counter[str] = Counter()
    for message in iter_messages(specs, source_map):
        per_message = match_message(
            message.text, matcher, normalized_to_index, args.case_sensitive
        )
        candidate = build_candidate(message, entries, per_message)
        if per_message:
            dominant_index = dominant_term_index(per_message, entries)
            aspect = entries[dominant_index].primary_aspect if dominant_index is not None else ""
            band = frequency_band(term_message_counts[dominant_index]) if dominant_index is not None else "low_1_9"
            stratum = matched_stratum(message.message_type, aspect, band)
        else:
            stratum = unmatched_stratum(message.message_type, message.source)
        candidate["sampling_stratum"] = stratum
        reservoir_consider(
            reservoirs,
            seen,
            stratum,
            candidate,
            allocation.get(stratum, 0),
            rng,
        )

    selected: list[dict[str, Any]] = []
    for stratum, bucket in reservoirs.items():
        sampled = len(bucket)
        population = populations[stratum]
        weight = population / sampled if sampled else 0.0
        for row in bucket:
            row["population_stratum_size"] = population
            row["sampled_stratum_size"] = sampled
            row["sampling_weight"] = round(weight, 8)
            selected.append(row)
    rng.shuffle(selected)

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    base = Path(args.output) if args.output else input_path / f"validation_sample_{timestamp}"
    destination = unique_output_directory(base)

    blinded_rows: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for number, row in enumerate(selected, start=1):
        sample_id = f"VAL{number:05d}"
        blinded_rows.append(
            {
                "sample_id": sample_id,
                "message_type": row["message_type"],
                "source": row["source"],
                "date": row["date"],
                "url": row["url"],
                "text": row["text"],
                "parent_post_text": row["parent_post_text"],
                "parent_post_date": row["parent_post_date"],
                "context_label": "",
                "usage_type": "",
                "target_type": "",
                "target_text": "",
                "primary_aspect_gold": "",
                "quoted_or_reported": "",
                "annotator_id": "",
                "annotation_notes": "",
            }
        )
        key_rows.append(
            {
                "sample_id": sample_id,
                "message_id": row["message_id"],
                "message_type": row["message_type"],
                "source": row["source"],
                "source_id": row["source_id"],
                "telegram_username": row["telegram_username"],
                "channel_title": row["channel_title"],
                "dictionary_prediction": row["dictionary_prediction"],
                "matched_terms": row["matched_terms"],
                "matched_categories": row["matched_categories"],
                "matched_primary_aspects": row["matched_primary_aspects"],
                "dominant_term": row["dominant_term"],
                "dominant_category": row["dominant_category"],
                "dominant_primary_aspect": row["dominant_primary_aspect"],
                "total_dictionary_occurrences": row["total_dictionary_occurrences"],
                "sampling_stratum": row["sampling_stratum"],
                "population_stratum_size": row["population_stratum_size"],
                "sampled_stratum_size": row["sampled_stratum_size"],
                "sampling_weight": row["sampling_weight"],
            }
        )

    write_csv(
        destination / "validation_sample_blinded.csv",
        [
            "sample_id",
            "message_type",
            "source",
            "date",
            "url",
            "text",
            "parent_post_text",
            "parent_post_date",
            "context_label",
            "usage_type",
            "target_type",
            "target_text",
            "primary_aspect_gold",
            "quoted_or_reported",
            "annotator_id",
            "annotation_notes",
        ],
        blinded_rows,
    )
    write_csv(
        destination / "validation_sample_key.csv",
        [
            "sample_id",
            "message_id",
            "message_type",
            "source",
            "source_id",
            "telegram_username",
            "channel_title",
            "dictionary_prediction",
            "matched_terms",
            "matched_categories",
            "matched_primary_aspects",
            "dominant_term",
            "dominant_category",
            "dominant_primary_aspect",
            "total_dictionary_occurrences",
            "sampling_stratum",
            "population_stratum_size",
            "sampled_stratum_size",
            "sampling_weight",
        ],
        key_rows,
    )

    report = {
        "schema_version": 1,
        "sampler_version": VERSION,
        "created_at": datetime.now().astimezone().isoformat(),
        "seed": args.seed,
        "input_folder": input_path.name,
        "dictionary_file": dictionary_path.name,
        "dictionary_entries": len(entries),
        "dictionary_duplicates_removed": duplicates,
        "include_posts": args.include_posts,
        "population": {
            "total_messages": total_messages,
            "matched_messages": matched_population,
            "unmatched_messages": total_messages - matched_population,
        },
        "requested_sample": {
            "matched": args.matched_size,
            "unmatched": args.unmatched_size,
        },
        "actual_sample": {
            "matched": sum(int(row["dictionary_prediction"]) for row in key_rows),
            "unmatched": sum(1 - int(row["dictionary_prediction"]) for row in key_rows),
            "total": len(key_rows),
        },
        "strata": [
            {
                "stratum": stratum,
                "population": populations[stratum],
                "sampled": allocation.get(stratum, 0),
            }
            for stratum in sorted(populations)
            if allocation.get(stratum, 0) > 0
        ],
        "blinding": (
            "Annotators receive validation_sample_blinded.csv. Dictionary predictions "
            "and matched terms are kept separately in validation_sample_key.csv."
        ),
    }
    (destination / "sampling_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    guidelines_source = Path(__file__).with_name("ANNOTATION_GUIDELINES.md")
    if guidelines_source.exists():
        shutil.copy2(guidelines_source, destination / guidelines_source.name)

    print(f"Created {len(selected)} validation items: {destination}")
    return destination


def main() -> int:
    args = build_parser().parse_args()
    if args.matched_size < 0 or args.unmatched_size < 0:
        print("Error: sample sizes must be non-negative.", file=sys.stderr)
        return 1
    try:
        prepare(args)
    except (FileNotFoundError, ValueError, UnicodeError, json.JSONDecodeError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

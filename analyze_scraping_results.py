from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


VERSION = "1.0.0"
SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-16", "cp1251")
DICTIONARY_HEADERS = {
    "term",
    "word",
    "words",
    "lexeme",
    "lemma",
    "entry",
    "token",
    "слово",
    "лексема",
    "лема",
}
TEXT_COLUMN_CANDIDATES = (
    "comment_text",
    "message_text",
    "text",
    "post_text",
    "content",
    "body",
)
MESSAGE_ID_CANDIDATES = (
    "comment_uid",
    "message_uid",
    "post_uid",
    "comment_id",
    "message_id",
    "post_id",
    "id",
)
SOURCE_COLUMN_CANDIDATES = (
    "telegram_username",
    "channel_title",
    "source_id",
    "channel",
    "source",
)
DATE_COLUMN_CANDIDATES = (
    "comment_date",
    "message_date",
    "date",
    "post_date",
    "created_at",
)
URL_COLUMN_CANDIDATES = (
    "post_url",
    "message_url",
    "url",
    "link",
)
APOSTROPHE_TRANSLATION = str.maketrans(
    {
        "’": "'",
        "ʼ": "'",
        "ʻ": "'",
        "`": "'",
        "´": "'",
    }
)
HYPHEN_TRANSLATION = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)
TERM_BOUNDARY = r"[\w'-]"


@dataclass(frozen=True)
class LexiconEntry:
    original: str
    normalized: str


@dataclass(frozen=True)
class InputSpec:
    path: Path
    message_type: str
    text_column: str
    message_id_column: str | None
    source_column: str | None
    date_column: str | None
    url_column: str | None
    fieldnames: tuple[str, ...]


@dataclass(frozen=True)
class MessageRecord:
    message_type: str
    message_id: str
    source: str
    date: str
    url: str
    text: str
    original_row: dict[str, str]
    input_file: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze exported Telegram scraper CSV files against a dictionary "
            "without modifying or importing the scraper project."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help=(
            "Path to an export folder or a CSV file. For a folder, "
            "comments_with_source_labels.csv is preferred automatically."
        ),
    )
    parser.add_argument(
        "--dictionary",
        required=True,
        help="Dictionary file in TXT, CSV, TSV, or JSON format.",
    )
    parser.add_argument(
        "--output",
        help=(
            "Output folder. By default, a timestamped analysis folder is "
            "created inside the export folder or next to the input CSV."
        ),
    )
    parser.add_argument(
        "--include-posts",
        action="store_true",
        help=(
            "When --input is an export folder, analyze posts.csv in addition "
            "to comments."
        ),
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Use case-sensitive matching. Default: case-insensitive.",
    )
    parser.add_argument(
        "--match-mode",
        choices=("whole-term", "substring"),
        default="whole-term",
        help=(
            "whole-term avoids matches inside longer words; substring matches "
            "any occurrence. Default: whole-term."
        ),
    )
    parser.add_argument(
        "--text-column",
        help="Override automatic text-column detection for a single CSV input.",
    )
    parser.add_argument(
        "--source-column",
        help="Override automatic source-column detection for a single CSV input.",
    )
    parser.add_argument(
        "--dictionary-column",
        help="Column name containing terms when the dictionary is CSV/TSV.",
    )
    parser.add_argument(
        "--omit-message-text",
        action="store_true",
        help="Do not copy full message text into messages_with_matches.csv.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser


def decode_text(path: Path) -> str:
    raw = path.read_bytes()
    last_error: UnicodeDecodeError | None = None
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as error:
            last_error = error
    raise UnicodeError(
        f"Could not decode {path}. Save it as UTF-8, UTF-16, or Windows-1251."
    ) from last_error


def normalize_text(value: str, case_sensitive: bool) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = text.translate(APOSTROPHE_TRANSLATION).translate(HYPHEN_TRANSLATION)
    text = re.sub(r"\s+", " ", text.strip())
    return text if case_sensitive else text.casefold()


def sniff_dialect(text: str, fallback_delimiter: str = ",") -> csv.Dialect:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        class FallbackDialect(csv.excel):
            delimiter = fallback_delimiter
        return FallbackDialect


def read_csv_rows(path: Path) -> tuple[list[str], Iterator[dict[str, str]]]:
    text = decode_text(path)
    dialect = sniff_dialect(text, "\t" if path.suffix.casefold() == ".tsv" else ",")
    lines = text.splitlines()
    reader = csv.DictReader(lines, dialect=dialect)
    fieldnames = [name.strip() for name in (reader.fieldnames or []) if name]
    if not fieldnames:
        raise ValueError(f"CSV file has no header row: {path}")

    def iterator() -> Iterator[dict[str, str]]:
        for raw_row in reader:
            row: dict[str, str] = {}
            for key, value in raw_row.items():
                if key is None:
                    continue
                clean_key = key.strip()
                row[clean_key] = "" if value is None else str(value)
            yield row

    return fieldnames, iterator()


def load_dictionary_entries(
    dictionary_path: Path,
    case_sensitive: bool,
    dictionary_column: str | None,
) -> tuple[list[LexiconEntry], int]:
    if not dictionary_path.exists() or not dictionary_path.is_file():
        raise FileNotFoundError(f"Dictionary file not found: {dictionary_path}")

    suffix = dictionary_path.suffix.casefold()
    raw_entries: list[str]

    if suffix in {".txt", ".list", ".dic"}:
        raw_entries = [
            line.strip()
            for line in decode_text(dictionary_path).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    elif suffix in {".csv", ".tsv"}:
        fieldnames, rows = read_csv_rows(dictionary_path)
        normalized_headers = {
            normalize_text(name, False): name for name in fieldnames
        }
        selected_column = dictionary_column
        if selected_column is not None and selected_column not in fieldnames:
            raise ValueError(
                f"Dictionary column '{selected_column}' not found. "
                f"Available columns: {', '.join(fieldnames)}"
            )
        if selected_column is None:
            for candidate in DICTIONARY_HEADERS:
                if candidate in normalized_headers:
                    selected_column = normalized_headers[candidate]
                    break
        selected_column = selected_column or fieldnames[0]
        raw_entries = [
            row.get(selected_column, "").strip()
            for row in rows
            if row.get(selected_column, "").strip()
        ]
    elif suffix == ".json":
        payload = json.loads(decode_text(dictionary_path))
        raw_entries = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str):
                    raw_entries.append(item)
                elif isinstance(item, dict):
                    selected = None
                    if dictionary_column and isinstance(item.get(dictionary_column), str):
                        selected = item[dictionary_column]
                    else:
                        for key, value in item.items():
                            if (
                                normalize_text(str(key), False) in DICTIONARY_HEADERS
                                and isinstance(value, str)
                            ):
                                selected = value
                                break
                    if selected:
                        raw_entries.append(selected)
        elif isinstance(payload, dict):
            for key in ("terms", "words", "lexicon", "entries"):
                value = payload.get(key)
                if isinstance(value, list):
                    raw_entries = [str(item) for item in value]
                    break
        else:
            raise ValueError("Unsupported JSON dictionary structure.")
    else:
        raise ValueError("Unsupported dictionary format. Use TXT, CSV, TSV, or JSON.")

    entries: list[LexiconEntry] = []
    seen: set[str] = set()
    duplicate_count = 0
    for raw in raw_entries:
        original = str(raw).strip()
        normalized = normalize_text(original, case_sensitive)
        if not normalized:
            continue
        if normalized in seen:
            duplicate_count += 1
            continue
        seen.add(normalized)
        entries.append(LexiconEntry(original=original, normalized=normalized))

    if not entries:
        raise ValueError(f"Dictionary contains no usable entries: {dictionary_path}")
    return entries, duplicate_count


def choose_column(
    fieldnames: Iterable[str],
    candidates: Iterable[str],
    override: str | None = None,
    required: bool = False,
) -> str | None:
    available = list(fieldnames)
    if override:
        if override not in available:
            raise ValueError(
                f"Column '{override}' not found. Available columns: "
                + ", ".join(available)
            )
        return override
    normalized = {normalize_text(name, False): name for name in available}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    if required:
        raise ValueError(
            "Could not detect a required column. Available columns: "
            + ", ".join(available)
        )
    return None


def inspect_input_csv(
    path: Path,
    message_type: str,
    text_override: str | None = None,
    source_override: str | None = None,
) -> InputSpec:
    fieldnames, _ = read_csv_rows(path)
    text_column = choose_column(
        fieldnames,
        TEXT_COLUMN_CANDIDATES,
        override=text_override,
        required=True,
    )
    return InputSpec(
        path=path,
        message_type=message_type,
        text_column=str(text_column),
        message_id_column=choose_column(fieldnames, MESSAGE_ID_CANDIDATES),
        source_column=choose_column(
            fieldnames,
            SOURCE_COLUMN_CANDIDATES,
            override=source_override,
        ),
        date_column=choose_column(fieldnames, DATE_COLUMN_CANDIDATES),
        url_column=choose_column(fieldnames, URL_COLUMN_CANDIDATES),
        fieldnames=tuple(fieldnames),
    )


def discover_inputs(
    input_path: Path,
    include_posts: bool,
    text_override: str | None,
    source_override: str | None,
) -> list[InputSpec]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")

    if input_path.is_file():
        if input_path.suffix.casefold() not in {".csv", ".tsv"}:
            raise ValueError("Single-file input must be CSV or TSV.")
        return [
            inspect_input_csv(
                input_path,
                message_type="message",
                text_override=text_override,
                source_override=source_override,
            )
        ]

    comments_candidates = (
        input_path / "comments_with_source_labels.csv",
        input_path / "comments.csv",
    )
    comments_file = next((path for path in comments_candidates if path.exists()), None)
    if comments_file is None:
        raise FileNotFoundError(
            "Export folder does not contain comments_with_source_labels.csv "
            "or comments.csv."
        )

    specs = [inspect_input_csv(comments_file, message_type="comment")]
    if include_posts:
        posts_file = input_path / "posts.csv"
        if not posts_file.exists():
            raise FileNotFoundError(
                "--include-posts was used, but posts.csv is missing from the export folder."
            )
        specs.append(inspect_input_csv(posts_file, message_type="post"))
    return specs


def compile_matcher(entries: list[LexiconEntry], match_mode: str) -> re.Pattern[str]:
    ordered = sorted(entries, key=lambda item: len(item.normalized), reverse=True)
    alternatives = [
        re.escape(entry.normalized).replace(r"\ ", r"\s+") for entry in ordered
    ]
    body = "(?:" + "|".join(alternatives) + ")"
    if match_mode == "whole-term":
        body = rf"(?<!{TERM_BOUNDARY}){body}(?!{TERM_BOUNDARY})"
    try:
        return re.compile(body)
    except re.error as error:
        raise ValueError(
            "Could not compile the dictionary matcher. The dictionary may be too large "
            "for one regular expression or contain unsupported entries."
        ) from error


def iter_messages(specs: list[InputSpec]) -> Iterator[MessageRecord]:
    generated_id = 0
    for spec in specs:
        _, rows = read_csv_rows(spec.path)
        for row in rows:
            text = row.get(spec.text_column, "")
            if not text or not text.strip():
                continue
            generated_id += 1
            message_id = (
                row.get(spec.message_id_column, "").strip()
                if spec.message_id_column
                else ""
            ) or f"generated_{generated_id}"
            source = (
                row.get(spec.source_column, "").strip()
                if spec.source_column
                else ""
            ) or "unknown"
            date = (
                row.get(spec.date_column, "").strip()
                if spec.date_column
                else ""
            )
            url = (
                row.get(spec.url_column, "").strip()
                if spec.url_column
                else ""
            )
            yield MessageRecord(
                message_type=spec.message_type,
                message_id=message_id,
                source=source,
                date=date,
                url=url,
                text=text,
                original_row=row,
                input_file=spec.path.name,
            )


def unique_output_directory(base: Path) -> Path:
    base.parent.mkdir(parents=True, exist_ok=True)
    candidate = base
    number = 2
    while candidate.exists():
        candidate = base.parent / f"{base.name}_{number:02d}"
        number += 1
    candidate.mkdir(parents=False, exist_ok=False)
    return candidate


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(
    input_path: Path,
    dictionary_path: Path,
    output_path: Path | None,
    include_posts: bool,
    case_sensitive: bool,
    match_mode: str,
    text_override: str | None,
    source_override: str | None,
    dictionary_column: str | None,
    omit_message_text: bool,
) -> Path:
    specs = discover_inputs(
        input_path,
        include_posts=include_posts,
        text_override=text_override,
        source_override=source_override,
    )
    entries, duplicate_count = load_dictionary_entries(
        dictionary_path,
        case_sensitive=case_sensitive,
        dictionary_column=dictionary_column,
    )
    normalized_to_index = {
        entry.normalized: index for index, entry in enumerate(entries)
    }
    matcher = compile_matcher(entries, match_mode)

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    if output_path is None:
        base_dir = input_path if input_path.is_dir() else input_path.parent
        output_path = base_dir / f"lexicon_analysis_{timestamp}"
    destination = unique_output_directory(output_path)

    term_occurrences: Counter[int] = Counter()
    term_message_counts: Counter[int] = Counter()
    term_type_occurrences: dict[int, Counter[str]] = defaultdict(Counter)
    term_type_messages: dict[int, Counter[str]] = defaultdict(Counter)
    source_stats: dict[str, dict[str, Any]] = {}
    source_term_occurrences: dict[tuple[str, int], int] = defaultdict(int)
    source_term_messages: dict[tuple[str, int], int] = defaultdict(int)
    matched_rows: list[dict[str, Any]] = []

    total_messages = 0
    messages_with_matches = 0
    total_occurrences = 0
    input_message_counts: Counter[str] = Counter()

    try:
        for message in iter_messages(specs):
            total_messages += 1
            input_message_counts[message.message_type] += 1
            source = source_stats.setdefault(
                message.source,
                {
                    "source": message.source,
                    "total_messages_analyzed": 0,
                    "messages_with_match": 0,
                    "total_occurrences": 0,
                    "detected_terms": set(),
                },
            )
            source["total_messages_analyzed"] += 1

            normalized_message = normalize_text(message.text, case_sensitive)
            per_message: Counter[int] = Counter()
            for match in matcher.finditer(normalized_message):
                normalized_match = normalize_text(match.group(0), case_sensitive)
                term_index = normalized_to_index.get(normalized_match)
                if term_index is not None:
                    per_message[term_index] += 1

            if not per_message:
                continue

            messages_with_matches += 1
            message_occurrences = sum(per_message.values())
            total_occurrences += message_occurrences
            source["messages_with_match"] += 1
            source["total_occurrences"] += message_occurrences
            source["detected_terms"].update(per_message)

            for term_index, count in per_message.items():
                term_occurrences[term_index] += count
                term_message_counts[term_index] += 1
                term_type_occurrences[term_index][message.message_type] += count
                term_type_messages[term_index][message.message_type] += 1
                source_term_occurrences[(message.source, term_index)] += count
                source_term_messages[(message.source, term_index)] += 1

            matched_terms = [entries[index].original for index in per_message]
            match_counts = {
                entries[index].original: count for index, count in per_message.items()
            }
            analysis_fields: dict[str, Any] = {
                "analysis_message_type": message.message_type,
                "analysis_message_id": message.message_id,
                "analysis_source": message.source,
                "analysis_date": message.date,
                "analysis_url": message.url,
                "analysis_input_file": message.input_file,
                "matched_terms": " | ".join(matched_terms),
                "unique_matched_terms": len(per_message),
                "total_dictionary_occurrences": message_occurrences,
                "match_counts_json": json.dumps(
                    match_counts,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
            original = dict(message.original_row)
            if omit_message_text:
                for candidate in TEXT_COLUMN_CANDIDATES:
                    original.pop(candidate, None)
            matched_rows.append({**analysis_fields, **original})

        ranked_indices = sorted(
            range(len(entries)),
            key=lambda index: (-term_occurrences[index], entries[index].normalized),
        )
        frequency_rows: list[dict[str, Any]] = []
        for rank, index in enumerate(ranked_indices, start=1):
            entry = entries[index]
            frequency_rows.append(
                {
                    "rank": rank,
                    "dictionary_term": entry.original,
                    "normalized_term": entry.normalized,
                    "total_occurrences": term_occurrences[index],
                    "messages_with_term": term_message_counts[index],
                    "comment_occurrences": term_type_occurrences[index]["comment"],
                    "comment_messages": term_type_messages[index]["comment"],
                    "post_occurrences": term_type_occurrences[index]["post"],
                    "post_messages": term_type_messages[index]["post"],
                    "other_occurrences": term_type_occurrences[index]["message"],
                    "other_messages": term_type_messages[index]["message"],
                }
            )

        source_rows: list[dict[str, Any]] = []
        for source in sorted(source_stats.values(), key=lambda item: item["source"]):
            total = int(source["total_messages_analyzed"])
            matched = int(source["messages_with_match"])
            source_rows.append(
                {
                    "source": source["source"],
                    "total_messages_analyzed": total,
                    "messages_with_match": matched,
                    "messages_without_match": total - matched,
                    "matched_message_percentage": round(matched / total * 100, 4)
                    if total
                    else 0.0,
                    "total_dictionary_occurrences": source["total_occurrences"],
                    "unique_dictionary_terms_detected": len(source["detected_terms"]),
                }
            )

        source_term_rows: list[dict[str, Any]] = []
        for (source_name, term_index), count in sorted(
            source_term_occurrences.items(),
            key=lambda item: (item[0][0], -item[1], entries[item[0][1]].normalized),
        ):
            source_term_rows.append(
                {
                    "source": source_name,
                    "dictionary_term": entries[term_index].original,
                    "total_occurrences": count,
                    "messages_with_term": source_term_messages[(source_name, term_index)],
                }
            )

        matched_fieldnames: list[str] = [
            "analysis_message_type",
            "analysis_message_id",
            "analysis_source",
            "analysis_date",
            "analysis_url",
            "analysis_input_file",
            "matched_terms",
            "unique_matched_terms",
            "total_dictionary_occurrences",
            "match_counts_json",
        ]
        for spec in specs:
            for field in spec.fieldnames:
                if field not in matched_fieldnames:
                    matched_fieldnames.append(field)
        if omit_message_text:
            matched_fieldnames = [
                field for field in matched_fieldnames if field not in TEXT_COLUMN_CANDIDATES
            ]

        frequency_path = destination / "word_frequencies.csv"
        messages_path = destination / "messages_with_matches.csv"
        source_path = destination / "source_summary.csv"
        source_terms_path = destination / "word_frequencies_by_source.csv"
        summary_path = destination / "analysis_summary.json"
        dictionary_snapshot = destination / f"dictionary_snapshot{dictionary_path.suffix}"

        write_csv(
            frequency_path,
            [
                "rank",
                "dictionary_term",
                "normalized_term",
                "total_occurrences",
                "messages_with_term",
                "comment_occurrences",
                "comment_messages",
                "post_occurrences",
                "post_messages",
                "other_occurrences",
                "other_messages",
            ],
            frequency_rows,
        )
        write_csv(messages_path, matched_fieldnames, matched_rows)
        write_csv(
            source_path,
            [
                "source",
                "total_messages_analyzed",
                "messages_with_match",
                "messages_without_match",
                "matched_message_percentage",
                "total_dictionary_occurrences",
                "unique_dictionary_terms_detected",
            ],
            source_rows,
        )
        write_csv(
            source_terms_path,
            [
                "source",
                "dictionary_term",
                "total_occurrences",
                "messages_with_term",
            ],
            source_term_rows,
        )
        shutil.copy2(dictionary_path, dictionary_snapshot)

        summary = {
            "schema_version": 1,
            "analyzer_version": VERSION,
            "analyzed_at": datetime.now().astimezone().isoformat(),
            "input": {
                "requested_path": str(input_path.resolve()),
                "files": [
                    {
                        "file": str(spec.path.resolve()),
                        "sha256": sha256(spec.path),
                        "message_type": spec.message_type,
                        "text_column": spec.text_column,
                        "source_column": spec.source_column,
                    }
                    for spec in specs
                ],
            },
            "dictionary": {
                "file": str(dictionary_path.resolve()),
                "sha256": sha256(dictionary_path),
                "entries": len(entries),
                "duplicate_entries_removed": duplicate_count,
            },
            "matching": {
                "mode": match_mode,
                "case_sensitive": case_sensitive,
                "unicode_normalization": "NFKC",
                "apostrophe_normalization": True,
                "hyphen_normalization": True,
                "multiword_whitespace_normalization": True,
                "overlap_policy": "longest alternative wins at the same position",
                "lemmatization": False,
            },
            "counts": {
                "total_messages_analyzed": total_messages,
                "comments_analyzed": input_message_counts["comment"],
                "posts_analyzed": input_message_counts["post"],
                "other_messages_analyzed": input_message_counts["message"],
                "messages_with_dictionary_match": messages_with_matches,
                "messages_without_dictionary_match": total_messages
                - messages_with_matches,
                "matched_message_percentage": round(
                    messages_with_matches / total_messages * 100, 4
                )
                if total_messages
                else 0.0,
                "total_dictionary_occurrences": total_occurrences,
                "unique_dictionary_terms_detected": sum(
                    1 for index in range(len(entries)) if term_occurrences[index] > 0
                ),
            },
            "outputs": {
                "word_frequencies": frequency_path.name,
                "messages_with_matches": messages_path.name,
                "source_summary": source_path.name,
                "word_frequencies_by_source": source_terms_path.name,
                "dictionary_snapshot": dictionary_snapshot.name,
            },
        }
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    print(
        f"Analyzed {total_messages} messages: "
        f"{messages_with_matches} contained dictionary matches "
        f"({summary['counts']['matched_message_percentage']}%)."
    )
    print(f"Total dictionary occurrences: {total_occurrences}")
    print(f"Results: {destination}")
    return destination


def main() -> int:
    args = build_parser().parse_args()
    try:
        analyze(
            input_path=Path(args.input),
            dictionary_path=Path(args.dictionary),
            output_path=Path(args.output) if args.output else None,
            include_posts=args.include_posts,
            case_sensitive=args.case_sensitive,
            match_mode=args.match_mode,
            text_override=args.text_column,
            source_override=args.source_column,
            dictionary_column=args.dictionary_column,
            omit_message_text=args.omit_message_text,
        )
    except (FileNotFoundError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

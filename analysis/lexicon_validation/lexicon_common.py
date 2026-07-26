from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

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
TELEGRAM_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?P<name>[A-Za-z0-9_]+)(?:/.*)?$",
    re.IGNORECASE,
)
TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class LexiconEntry:
    term: str
    normalized: str
    category: str = ""
    meaning: str = ""
    source: str = ""
    primary_aspect: str = ""
    secondary_aspect: str = ""
    annotation_notes: str = ""

    def as_metadata(self) -> dict[str, str]:
        return {
            "dictionary_term": self.term,
            "normalized_term": self.normalized,
            "category": self.category,
            "meaning": self.meaning,
            "dictionary_source": self.source,
            "primary_aspect": self.primary_aspect,
            "secondary_aspect": self.secondary_aspect,
            "annotation_notes": self.annotation_notes,
        }


@dataclass(frozen=True)
class SourceMetadata:
    source_id: str
    telegram_username: str
    channel_title: str


@dataclass(frozen=True)
class InputSpec:
    path: Path
    message_type: str
    text_column: str
    message_id_column: str | None
    date_column: str | None
    url_column: str | None
    fieldnames: tuple[str, ...]


@dataclass(frozen=True)
class MessageRecord:
    message_type: str
    message_id: str
    source: str
    source_id: str
    telegram_username: str
    channel_title: str
    date: str
    url: str
    text: str
    original_row: dict[str, str]
    input_file: str


@dataclass
class CsvQuality:
    rows_read: int = 0
    rows_with_extra_fields: int = 0
    rows_with_missing_fields: int = 0
    suspicious_sources: Counter[str] = field(default_factory=Counter)
    unknown_source_rows: int = 0


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
    sample = text[:65536]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        class FallbackDialect(csv.excel):
            delimiter = fallback_delimiter

        return FallbackDialect


def clean_header(value: str) -> str:
    return value.strip().lstrip("\ufeff")


def read_csv_rows(
    path: Path,
    quality: CsvQuality | None = None,
) -> tuple[list[str], Iterator[dict[str, str]]]:
    """Read CSV/TSV correctly, including quoted fields containing newlines.

    The earlier analyzer used ``text.splitlines()`` before ``csv.DictReader``.
    That breaks valid multiline Telegram messages and can shift message text into
    unrelated columns. This implementation keeps the CSV stream intact.
    """

    text = decode_text(path)
    fallback = "\t" if path.suffix.casefold() == ".tsv" else ","
    dialect = sniff_dialect(text, fallback)

    header_stream = io.StringIO(text, newline="")
    header_reader = csv.DictReader(header_stream, dialect=dialect)
    raw_fieldnames = list(header_reader.fieldnames or [])
    fieldnames = [clean_header(name) for name in raw_fieldnames if name is not None]
    if not fieldnames:
        raise ValueError(f"CSV file has no header row: {path}")
    if len(fieldnames) != len(set(fieldnames)):
        raise ValueError(f"CSV file has duplicate column names after trimming: {path}")

    def iterator() -> Iterator[dict[str, str]]:
        stream = io.StringIO(text, newline="")
        reader = csv.DictReader(stream, dialect=dialect)
        for raw_row in reader:
            if quality is not None:
                quality.rows_read += 1
                if None in raw_row and raw_row[None]:
                    quality.rows_with_extra_fields += 1
                if any(value is None for key, value in raw_row.items() if key is not None):
                    quality.rows_with_missing_fields += 1
            row: dict[str, str] = {}
            for key, value in raw_row.items():
                if key is None:
                    continue
                row[clean_header(key)] = "" if value is None else str(value)
            yield row

    return fieldnames, iterator()


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


def normalize_telegram_username(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    match = TELEGRAM_URL_RE.match(raw)
    if match:
        raw = match.group("name")
    raw = raw.removeprefix("@").strip()
    if not TELEGRAM_USERNAME_RE.fullmatch(raw):
        return ""
    return "@" + raw.casefold()


def load_source_map(export_directory: Path) -> dict[str, SourceMetadata]:
    path = export_directory / "sources.csv"
    if not path.exists():
        return {}
    _, rows = read_csv_rows(path)
    result: dict[str, SourceMetadata] = {}
    for row in rows:
        source_id = row.get("source_id", "").strip()
        if not source_id:
            continue
        result[source_id] = SourceMetadata(
            source_id=source_id,
            telegram_username=normalize_telegram_username(
                row.get("telegram_username", "") or row.get("channel_url", "")
            ),
            channel_title=row.get("channel_title", "").strip(),
        )
    return result


def resolve_source(
    row: Mapping[str, str],
    source_map: Mapping[str, SourceMetadata],
) -> tuple[str, str, str, str]:
    source_id = str(row.get("source_id", "")).strip()
    mapped = source_map.get(source_id)

    username = normalize_telegram_username(
        str(row.get("telegram_username", ""))
        or str(row.get("channel_username", ""))
        or (mapped.telegram_username if mapped else "")
    )
    title = (
        str(row.get("channel_title", "")).strip()
        or (mapped.channel_title if mapped else "")
    )

    canonical = username or title or source_id or "unknown"
    return canonical, source_id, username, title


def source_looks_suspicious(source: str) -> bool:
    if source == "unknown":
        return False
    if source.startswith("@") or re.fullmatch(r"src_[A-Za-z0-9_-]+", source):
        return False
    if "\n" in source or "\r" in source or len(source) > 160:
        return True
    return len(source.split()) > 16


def inspect_input_csv(
    path: Path,
    message_type: str,
    text_override: str | None = None,
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
        date_column=choose_column(fieldnames, DATE_COLUMN_CANDIDATES),
        url_column=choose_column(fieldnames, URL_COLUMN_CANDIDATES),
        fieldnames=tuple(fieldnames),
    )


def discover_inputs(
    input_path: Path,
    include_posts: bool,
    text_override: str | None = None,
) -> tuple[list[InputSpec], dict[str, SourceMetadata]]:
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
            )
        ], {}

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
    return specs, load_source_map(input_path)


def iter_messages(
    specs: Sequence[InputSpec],
    source_map: Mapping[str, SourceMetadata],
    quality: CsvQuality | None = None,
) -> Iterator[MessageRecord]:
    generated_id = 0
    for spec in specs:
        _, rows = read_csv_rows(spec.path, quality=quality)
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
            date = row.get(spec.date_column, "").strip() if spec.date_column else ""
            url = row.get(spec.url_column, "").strip() if spec.url_column else ""
            source, source_id, username, title = resolve_source(row, source_map)
            if quality is not None:
                if source == "unknown":
                    quality.unknown_source_rows += 1
                elif source_looks_suspicious(source):
                    quality.suspicious_sources[source] += 1
            yield MessageRecord(
                message_type=spec.message_type,
                message_id=message_id,
                source=source,
                source_id=source_id,
                telegram_username=username,
                channel_title=title,
                date=date,
                url=url,
                text=text,
                original_row=row,
                input_file=spec.path.name,
            )


def _dictionary_value(row: Mapping[str, Any], names: Sequence[str]) -> str:
    normalized = {normalize_text(str(key), False): value for key, value in row.items()}
    for name in names:
        value = normalized.get(normalize_text(name, False))
        if value is not None:
            return str(value).strip()
    return ""


def _entry_from_mapping(
    row: Mapping[str, Any],
    term_column: str,
    case_sensitive: bool,
) -> LexiconEntry | None:
    term = str(row.get(term_column, "")).strip()
    if not term:
        return None
    return LexiconEntry(
        term=term,
        normalized=normalize_text(term, case_sensitive),
        category=_dictionary_value(row, ("category", "категорія", "категория")),
        meaning=_dictionary_value(row, ("meaning", "значення", "значение")),
        source=_dictionary_value(row, ("source", "джерело", "источник")),
        primary_aspect=_dictionary_value(
            row, ("primary_aspect", "primary aspect", "основний аспект")
        ),
        secondary_aspect=_dictionary_value(
            row, ("secondary_aspect", "secondary aspect", "додатковий аспект")
        ),
        annotation_notes=_dictionary_value(
            row, ("annotation_notes", "annotation notes", "нотатки", "примітки")
        ),
    )


def load_dictionary_entries(
    dictionary_path: Path,
    case_sensitive: bool,
    dictionary_column: str | None = None,
) -> tuple[list[LexiconEntry], int]:
    if not dictionary_path.exists() or not dictionary_path.is_file():
        raise FileNotFoundError(f"Dictionary file not found: {dictionary_path}")

    suffix = dictionary_path.suffix.casefold()
    raw_entries: list[LexiconEntry] = []

    if suffix in {".txt", ".list", ".dic"}:
        for line in decode_text(dictionary_path).splitlines():
            term = line.strip()
            if term and not term.startswith("#"):
                raw_entries.append(
                    LexiconEntry(
                        term=term,
                        normalized=normalize_text(term, case_sensitive),
                    )
                )
    elif suffix in {".csv", ".tsv"}:
        fieldnames, rows = read_csv_rows(dictionary_path)
        normalized_headers = {normalize_text(name, False): name for name in fieldnames}
        selected_column = dictionary_column
        if selected_column and selected_column not in fieldnames:
            raise ValueError(
                f"Dictionary column '{selected_column}' not found. Available columns: "
                + ", ".join(fieldnames)
            )
        if selected_column is None:
            for candidate in DICTIONARY_HEADERS:
                if candidate in normalized_headers:
                    selected_column = normalized_headers[candidate]
                    break
        selected_column = selected_column or fieldnames[0]
        for row in rows:
            entry = _entry_from_mapping(row, selected_column, case_sensitive)
            if entry is not None:
                raw_entries.append(entry)
    elif suffix == ".json":
        payload = json.loads(decode_text(dictionary_path))
        if isinstance(payload, dict):
            for key in ("terms", "words", "lexicon", "entries"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            raise ValueError("Unsupported JSON dictionary structure.")
        for item in payload:
            if isinstance(item, str):
                raw_entries.append(
                    LexiconEntry(
                        term=item.strip(),
                        normalized=normalize_text(item, case_sensitive),
                    )
                )
            elif isinstance(item, dict):
                term_key = dictionary_column
                if term_key is None:
                    for key in item:
                        if normalize_text(str(key), False) in DICTIONARY_HEADERS:
                            term_key = str(key)
                            break
                if term_key:
                    entry = _entry_from_mapping(item, term_key, case_sensitive)
                    if entry is not None:
                        raw_entries.append(entry)
    else:
        raise ValueError("Unsupported dictionary format. Use TXT, CSV, TSV, or JSON.")

    entries: list[LexiconEntry] = []
    seen: set[str] = set()
    duplicates = 0
    for entry in raw_entries:
        if not entry.normalized:
            continue
        if entry.normalized in seen:
            duplicates += 1
            continue
        seen.add(entry.normalized)
        entries.append(entry)
    if not entries:
        raise ValueError(f"Dictionary contains no usable entries: {dictionary_path}")
    return entries, duplicates


def compile_matcher(entries: Sequence[LexiconEntry], match_mode: str) -> re.Pattern[str]:
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
        raise ValueError("Could not compile the dictionary matcher.") from error


def match_message(
    text: str,
    matcher: re.Pattern[str],
    normalized_to_index: Mapping[str, int],
    case_sensitive: bool,
) -> Counter[int]:
    normalized_message = normalize_text(text, case_sensitive)
    result: Counter[int] = Counter()
    for match in matcher.finditer(normalized_message):
        normalized_match = normalize_text(match.group(0), case_sensitive)
        index = normalized_to_index.get(normalized_match)
        if index is not None:
            result[index] += 1
    return result


def dominant_term_index(
    per_message: Mapping[int, int],
    entries: Sequence[LexiconEntry],
) -> int | None:
    if not per_message:
        return None
    return min(
        per_message,
        key=lambda index: (
            -int(per_message[index]),
            -len(entries[index].normalized),
            entries[index].normalized,
        ),
    )


def join_unique(values: Iterable[str]) -> str:
    return " | ".join(sorted({value for value in values if value and value != "-"}))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def unique_output_directory(base: Path) -> Path:
    base.parent.mkdir(parents=True, exist_ok=True)
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = base.parent / f"{base.name}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=False, exist_ok=False)
    return candidate


def percent(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100, 4) if denominator else 0.0


def per_thousand(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 1000, 4) if denominator else 0.0


def allocate_stratified_sample(
    population: Mapping[str, int],
    requested_size: int,
    minimum_per_stratum: int = 1,
) -> dict[str, int]:
    """Allocate a fixed sample proportionally using the largest-remainder method."""

    positive = {key: int(value) for key, value in population.items() if int(value) > 0}
    total_population = sum(positive.values())
    target = min(max(0, int(requested_size)), total_population)
    if target == 0:
        return {key: 0 for key in positive}

    allocation = {key: 0 for key in positive}
    if minimum_per_stratum > 0 and target >= len(positive) * minimum_per_stratum:
        for key, available in positive.items():
            allocation[key] = min(minimum_per_stratum, available)

    remaining = target - sum(allocation.values())
    if remaining <= 0:
        return allocation

    residual_capacity = {
        key: positive[key] - allocation[key] for key in positive
    }
    residual_total = sum(residual_capacity.values())
    if residual_total <= 0:
        return allocation

    ideals: dict[str, float] = {}
    for key, capacity in residual_capacity.items():
        ideals[key] = remaining * capacity / residual_total
        addition = min(capacity, math.floor(ideals[key]))
        allocation[key] += addition

    remaining = target - sum(allocation.values())
    order = sorted(
        positive,
        key=lambda key: (
            -(ideals.get(key, 0.0) - math.floor(ideals.get(key, 0.0))),
            -residual_capacity[key],
            key,
        ),
    )
    while remaining > 0:
        progressed = False
        for key in order:
            if allocation[key] < positive[key]:
                allocation[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break
    return allocation


def reservoir_consider(
    reservoirs: dict[str, list[Any]],
    seen: Counter[str],
    stratum: str,
    item: Any,
    capacity: int,
    rng: random.Random,
) -> None:
    seen[stratum] += 1
    if capacity <= 0:
        return
    bucket = reservoirs.setdefault(stratum, [])
    if len(bucket) < capacity:
        bucket.append(item)
        return
    replacement = rng.randrange(seen[stratum])
    if replacement < capacity:
        bucket[replacement] = item

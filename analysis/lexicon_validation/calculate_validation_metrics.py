from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from lexicon_common import read_csv_rows, write_csv

VERSION = "1.0.0"
VALID_CONTEXT_LABELS = {"offensive", "non_offensive", "uncertain"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate weighted dictionary-detector validation metrics from a "
            "completed blinded annotation file and its hidden key."
        )
    )
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--output", help="Output folder. Default: beside annotations.")
    parser.add_argument(
        "--second-annotations",
        help="Optional second annotator file for Cohen's kappa and disagreements.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def load_by_id(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    fields, rows = read_csv_rows(path)
    if "sample_id" not in fields:
        raise ValueError(f"Missing sample_id column: {path}")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        sample_id = row.get("sample_id", "").strip()
        if not sample_id:
            continue
        if sample_id in result:
            raise ValueError(f"Duplicate sample_id {sample_id} in {path}")
        result[sample_id] = row
    return fields, result


def safe_divide(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def confusion_metrics(tp: float, fp: float, fn: float, tn: float) -> dict[str, Any]:
    precision = safe_divide(tp, tp + fp)
    recall = safe_divide(tp, tp + fn)
    specificity = safe_divide(tn, tn + fp)
    accuracy = safe_divide(tp + tn, tp + fp + fn + tn)
    f1 = (
        round(2 * precision * recall / (precision + recall), 6)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "true_positive": round(tp, 6),
        "false_positive": round(fp, 6),
        "false_negative": round(fn, 6),
        "true_negative": round(tn, 6),
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "accuracy": accuracy,
        "f1": f1,
    }


def cohens_kappa(labels_a: list[str], labels_b: list[str]) -> dict[str, Any]:
    if len(labels_a) != len(labels_b):
        raise ValueError("Agreement label lists have different lengths.")
    n = len(labels_a)
    if n == 0:
        return {"n": 0, "observed_agreement": None, "cohens_kappa": None}
    categories = sorted(set(labels_a) | set(labels_b))
    observed = sum(a == b for a, b in zip(labels_a, labels_b)) / n
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = sum((counts_a[c] / n) * (counts_b[c] / n) for c in categories)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {
        "n": n,
        "observed_agreement": round(observed, 6),
        "cohens_kappa": round(kappa, 6),
        "categories": categories,
    }


def calculate(args: argparse.Namespace) -> Path:
    annotations_path = Path(args.annotations)
    key_path = Path(args.key)
    annotation_fields, annotations = load_by_id(annotations_path)
    _, keys = load_by_id(key_path)
    if "context_label" not in annotation_fields:
        raise ValueError("Annotation file is missing context_label.")

    missing_keys = sorted(set(annotations) - set(keys))
    if missing_keys:
        raise ValueError(
            f"{len(missing_keys)} annotation rows are missing from the key; first: "
            f"{missing_keys[0]}"
        )

    raw = Counter()
    weighted = Counter()
    evaluated = 0
    uncertain = 0
    unlabelled = 0
    false_positive_rows: list[dict[str, Any]] = []
    false_negative_rows: list[dict[str, Any]] = []
    aspect_counts: dict[str, Counter[str]] = defaultdict(Counter)
    term_counts: dict[str, Counter[str]] = defaultdict(Counter)

    merged_rows: list[dict[str, Any]] = []
    for sample_id, annotation in annotations.items():
        key = keys[sample_id]
        label = annotation.get("context_label", "").strip().casefold()
        if not label:
            unlabelled += 1
            continue
        if label not in VALID_CONTEXT_LABELS:
            raise ValueError(
                f"Invalid context_label '{label}' for {sample_id}. Allowed: "
                + ", ".join(sorted(VALID_CONTEXT_LABELS))
            )
        if label == "uncertain":
            uncertain += 1
            continue

        prediction = int(key.get("dictionary_prediction", "0") or 0)
        gold = 1 if label == "offensive" else 0
        weight = float(key.get("sampling_weight", "1") or 1)
        if prediction == 1 and gold == 1:
            cell = "tp"
        elif prediction == 1 and gold == 0:
            cell = "fp"
        elif prediction == 0 and gold == 1:
            cell = "fn"
        else:
            cell = "tn"
        raw[cell] += 1
        weighted[cell] += weight
        evaluated += 1
        merged = {**key, **annotation, "confusion_cell": cell}
        merged_rows.append(merged)
        if cell == "fp":
            false_positive_rows.append(merged)
        elif cell == "fn":
            false_negative_rows.append(merged)

        if prediction == 1:
            aspect = key.get("dominant_primary_aspect", "") or "Unspecified"
            term = key.get("dominant_term", "") or "Unspecified"
            aspect_counts[aspect]["evaluated"] += 1
            term_counts[term]["evaluated"] += 1
            if gold == 1:
                aspect_counts[aspect]["true_positive"] += 1
                term_counts[term]["true_positive"] += 1
            else:
                aspect_counts[aspect]["false_positive"] += 1
                term_counts[term]["false_positive"] += 1

    destination = Path(args.output) if args.output else annotations_path.parent / "validation_metrics"
    destination.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schema_version": 1,
        "metrics_version": VERSION,
        "calculated_at": datetime.now().astimezone().isoformat(),
        "annotations_file": annotations_path.name,
        "key_file": key_path.name,
        "annotation_status": {
            "total_rows": len(annotations),
            "evaluated_binary_rows": evaluated,
            "uncertain_rows_excluded": uncertain,
            "unlabelled_rows_excluded": unlabelled,
        },
        "unweighted_metrics": confusion_metrics(
            raw["tp"], raw["fp"], raw["fn"], raw["tn"]
        ),
        "weighted_population_estimates": confusion_metrics(
            weighted["tp"], weighted["fp"], weighted["fn"], weighted["tn"]
        ),
        "interpretation_note": (
            "Use weighted_population_estimates for the stratified sample. Precision "
            "estimates how often a dictionary match is truly offensive in context; "
            "recall estimates how much contextual offensiveness is detected by the dictionary."
        ),
    }

    if args.second_annotations:
        second_path = Path(args.second_annotations)
        second_fields, second = load_by_id(second_path)
        if "context_label" not in second_fields:
            raise ValueError("Second annotation file is missing context_label.")
        labels_a: list[str] = []
        labels_b: list[str] = []
        disagreements: list[dict[str, str]] = []
        for sample_id in sorted(set(annotations) & set(second)):
            a = annotations[sample_id].get("context_label", "").strip().casefold()
            b = second[sample_id].get("context_label", "").strip().casefold()
            if a not in VALID_CONTEXT_LABELS or b not in VALID_CONTEXT_LABELS:
                continue
            labels_a.append(a)
            labels_b.append(b)
            if a != b:
                disagreements.append(
                    {
                        "sample_id": sample_id,
                        "annotator_a_label": a,
                        "annotator_b_label": b,
                        "text": annotations[sample_id].get("text", ""),
                    }
                )
        report["inter_annotator_agreement"] = cohens_kappa(labels_a, labels_b)
        write_csv(
            destination / "annotator_disagreements.csv",
            ["sample_id", "annotator_a_label", "annotator_b_label", "text"],
            disagreements,
        )

    aspect_rows = [
        {
            "primary_aspect": aspect,
            "evaluated_matched_messages": counts["evaluated"],
            "true_positive": counts["true_positive"],
            "false_positive": counts["false_positive"],
            "precision": safe_divide(
                counts["true_positive"],
                counts["true_positive"] + counts["false_positive"],
            ),
        }
        for aspect, counts in sorted(
            aspect_counts.items(), key=lambda item: (-item[1]["evaluated"], item[0])
        )
    ]
    term_rows = [
        {
            "dominant_term": term,
            "evaluated_matched_messages": counts["evaluated"],
            "true_positive": counts["true_positive"],
            "false_positive": counts["false_positive"],
            "precision": safe_divide(
                counts["true_positive"],
                counts["true_positive"] + counts["false_positive"],
            ),
        }
        for term, counts in sorted(
            term_counts.items(), key=lambda item: (-item[1]["evaluated"], item[0])
        )
    ]

    report_path = destination / "validation_metrics.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(
        destination / "precision_by_primary_aspect.csv",
        [
            "primary_aspect",
            "evaluated_matched_messages",
            "true_positive",
            "false_positive",
            "precision",
        ],
        aspect_rows,
    )
    write_csv(
        destination / "precision_by_term.csv",
        [
            "dominant_term",
            "evaluated_matched_messages",
            "true_positive",
            "false_positive",
            "precision",
        ],
        term_rows,
    )

    export_fields = list(dict.fromkeys([
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
        "primary_aspect_gold",
        "annotation_notes",
        "dictionary_prediction",
        "matched_terms",
        "dominant_term",
        "dominant_primary_aspect",
        "sampling_stratum",
        "sampling_weight",
        "confusion_cell",
    ]))
    write_csv(destination / "false_positives.csv", export_fields, false_positive_rows)
    write_csv(destination / "false_negatives.csv", export_fields, false_negative_rows)
    write_csv(destination / "evaluated_sample_with_key.csv", export_fields, merged_rows)

    print(f"Validation results: {destination}")
    return destination


def main() -> int:
    args = build_parser().parse_args()
    try:
        calculate(args)
    except (FileNotFoundError, ValueError, UnicodeError, json.JSONDecodeError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from pathlib import Path

from lexicon_common import read_csv_rows, write_csv

VERSION = "1.0.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a deterministic overlap subset for a second annotator."
    )
    parser.add_argument("--input", required=True, help="Blinded validation CSV.")
    parser.add_argument("--output", help="Output CSV path.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--percent", type=float, default=20.0)
    group.add_argument("--count", type=int)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    try:
        fields, iterator = read_csv_rows(input_path)
        rows = list(iterator)
    except (FileNotFoundError, ValueError, UnicodeError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if not rows:
        print("Error: input sample is empty.", file=sys.stderr)
        return 1
    if args.count is not None:
        target = args.count
    else:
        if args.percent <= 0 or args.percent > 100:
            print("Error: --percent must be greater than 0 and at most 100.", file=sys.stderr)
            return 1
        target = math.ceil(len(rows) * args.percent / 100)
    target = min(max(1, target), len(rows))

    rng = random.Random(args.seed)
    selected = rng.sample(rows, target)
    selected.sort(key=lambda row: row.get("sample_id", ""))
    output_path = (
        Path(args.output)
        if args.output
        else input_path.with_name("validation_sample_second_annotator.csv")
    )
    write_csv(output_path, fields, selected)
    print(f"Created {target} overlap items: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse

from src.export import export_all_tables, export_scrape_run, list_scrape_runs
from src.settings import load_dataset_export_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export one scrape run or a cumulative database snapshot."
    )
    parser.add_argument(
        "--run-id",
        help="Export a specific scrape run. The latest completed run is the default.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export a cumulative snapshot containing all database records.",
    )
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List recorded scrape runs without exporting.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    config = load_dataset_export_config("config.yaml")

    if args.list_runs:
        runs = list_scrape_runs(config.database_path)
        if not runs:
            print("No scrape runs found.")
            return

        for run in runs:
            print(
                f"{run['run_id']} | {run['status']} | "
                f"posts={run['posts']} | comments={run['comments']} | "
                f"started={run['started_at']}"
            )
        return

    if args.all:
        export_all_tables(
            database_path=config.database_path,
            output_dir=config.output_dir,
        )
        return

    export_scrape_run(
        database_path=config.database_path,
        output_dir=config.output_dir,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
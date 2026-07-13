from src.export import export_all_tables
from src.settings import load_config


def main() -> None:
    config = load_config("config.yaml")
    export_all_tables(
        database_path=config.database.path,
        output_dir=config.export.output_dir,
    )


if __name__ == "__main__":
    main()

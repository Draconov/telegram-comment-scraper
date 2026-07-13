import asyncio

from src.scraper import TelegramResearchScraper
from src.settings import load_config


async def main() -> None:
    config = load_config("config.yaml")
    scraper = TelegramResearchScraper(config)
    await scraper.run()


if __name__ == "__main__":
    asyncio.run(main())

from typing import Dict, Optional

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from src.db import (
    connect_database,
    init_database,
    save_comment,
    save_post,
    save_source,
)
from src.settings import AppConfig
from src.sources import load_sources
from src.utils import (
    hash_text,
    is_inside_date_range,
    parse_iso_date,
    polite_delay,
)


class TelegramResearchScraper:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.after_date = parse_iso_date(config.scraping.after_date)
        self.before_date = parse_iso_date(config.scraping.before_date)

    async def run(self) -> None:
        sources = load_sources(self.config.input.sources_file)

        if not sources:
            print("No active sources found. Check your sources CSV file.")
            return

        conn = connect_database(self.config.database.path)
        init_database(conn)

        async with TelegramClient(
            self.config.telegram.session_name,
            self.config.telegram.api_id,
            self.config.telegram.api_hash,
        ) as client:
            for source in sources:
                await self.scrape_source(client, conn, source)
                await polite_delay(
                    self.config.scraping.min_delay_seconds,
                    self.config.scraping.max_delay_seconds,
                )

        conn.close()

    async def scrape_source(
        self,
        client: TelegramClient,
        conn,
        source: Dict[str, str],
    ) -> None:
        channel_username = source["telegram_username"]

        print(f"\nScraping source: {channel_username}")

        save_source(conn, source)

        try:
            entity = await client.get_entity(channel_username)
        except ChannelPrivateError:
            print(f"Skipping private or inaccessible channel: {channel_username}")
            return
        except UsernameInvalidError:
            print(f"Invalid Telegram username: {channel_username}")
            return
        except UsernameNotOccupiedError:
            print(f"Telegram username does not exist: {channel_username}")
            return
        except Exception as error:
            print(f"Could not access {channel_username}: {error}")
            return

        collected_posts = 0

        try:
            async for post in client.iter_messages(
                entity,
                limit=None,
                search=self.config.scraping.keyword_filter,
            ):
                if collected_posts >= self.config.scraping.posts_per_channel:
                    break

                if not is_inside_date_range(post.date, self.after_date, self.before_date):
                    if self.after_date and post.date and post.date < self.after_date:
                        break

                    continue

                if not self.config.scraping.include_posts_without_text:
                    if not post.message:
                        continue

                post_uid = save_post(
                    conn=conn,
                    source=source,
                    channel_username=channel_username,
                    post=post,
                )

                collected_posts += 1

                print(
                    f"Saved post {collected_posts}/"
                    f"{self.config.scraping.posts_per_channel}: "
                    f"{channel_username}/{post.id}"
                )

                if self.config.scraping.scrape_comments:
                    await self.scrape_comments_for_post(
                        client=client,
                        conn=conn,
                        source=source,
                        entity=entity,
                        channel_username=channel_username,
                        post_uid=post_uid,
                        post_id=post.id,
                    )

                await polite_delay(
                    self.config.scraping.min_delay_seconds,
                    self.config.scraping.max_delay_seconds,
                )

        except FloodWaitError as error:
            await self.handle_flood_wait(error)
        except Exception as error:
            print(f"Error while scraping {channel_username}: {error}")

    async def scrape_comments_for_post(
        self,
        client: TelegramClient,
        conn,
        source: Dict[str, str],
        entity,
        channel_username: str,
        post_uid: str,
        post_id: int,
    ) -> None:
        collected_comments = 0

        try:
            async for comment in client.iter_messages(
                entity,
                reply_to=post_id,
                limit=self.config.scraping.comments_per_post,
            ):
                if not comment.message:
                    continue

                sender_id, sender_hash, sender_username = self.extract_sender_data(comment)

                save_comment(
                    conn=conn,
                    source=source,
                    channel_username=channel_username,
                    post_uid=post_uid,
                    post_id=post_id,
                    comment=comment,
                    sender_id=sender_id,
                    sender_hash=sender_hash,
                    sender_username=sender_username,
                )

                collected_comments += 1

        except FloodWaitError as error:
            await self.handle_flood_wait(error)
        except Exception as error:
            print(
                f"Could not scrape comments for "
                f"{channel_username}/{post_id}: {error}"
            )
            return

        print(
            f"Saved {collected_comments} comments for "
            f"{channel_username}/{post_id}"
        )

    def extract_sender_data(self, comment) -> tuple[Optional[str], Optional[str], Optional[str]]:
        raw_sender_id = getattr(comment, "sender_id", None)

        sender_id = None
        sender_hash = None
        sender_username = None

        if raw_sender_id is not None:
            raw_sender_id = str(raw_sender_id)

            if self.config.privacy.save_sender_ids:
                sender_id = raw_sender_id

            if self.config.privacy.hash_sender_ids:
                sender_hash = hash_text(raw_sender_id)

        if self.config.privacy.save_usernames:
            sender = getattr(comment, "sender", None)

            if sender is not None:
                sender_username = getattr(sender, "username", None)

        return sender_id, sender_hash, sender_username

    async def handle_flood_wait(self, error: FloodWaitError) -> None:
        print(f"Telegram returned FloodWait: wait {error.seconds} seconds.")

        if self.config.scraping.stop_on_flood_wait:
            raise error

        import asyncio

        await asyncio.sleep(error.seconds)
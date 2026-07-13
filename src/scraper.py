from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    MsgIdInvalidError,
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
    is_inside_date_range,
    parse_iso_date,
    polite_delay,
    pseudonymize,
)


class TelegramResearchScraper:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.after_date = parse_iso_date(config.scraping.after_date)
        self.before_date = parse_iso_date(config.scraping.before_date)

    async def run(self) -> None:
        sources = load_sources(self.config.input.sources_file)
        if not sources:
            print("No active sources found. Check your local sources.csv file.")
            return

        session_path = Path(self.config.telegram.session_name)
        if session_path.parent != Path("."):
            session_path.parent.mkdir(parents=True, exist_ok=True)

        connection = connect_database(self.config.database.path)
        init_database(connection)

        try:
            async with TelegramClient(
                self.config.telegram.session_name,
                self.config.telegram.api_id,
                self.config.telegram.api_hash,
            ) as client:
                if not await client.is_user_authorized():
                    raise RuntimeError(
                        "Telegram session is not authorized. Run: python login_qr.py"
                    )

                for source in sources:
                    await self.scrape_source(client, connection, source)
                    await polite_delay(
                        self.config.scraping.min_delay_seconds,
                        self.config.scraping.max_delay_seconds,
                    )
        finally:
            connection.close()

    async def scrape_source(
        self,
        client: TelegramClient,
        connection: sqlite3.Connection,
        source: dict[str, str],
    ) -> None:
        channel_username = source["telegram_username"]
        print(f"\nScraping source: {channel_username}")
        save_source(connection, source)

        try:
            entity = await client.get_entity(channel_username)
        except (ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError) as error:
            print(f"Skipping inaccessible source {channel_username}: {type(error).__name__}")
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

                if not is_inside_date_range(
                    post.date,
                    self.after_date,
                    self.before_date,
                ):
                    if self.after_date and post.date and post.date < self.after_date:
                        break
                    continue

                if (
                    not self.config.scraping.include_posts_without_text
                    and not post.message
                ):
                    continue

                post_uid = save_post(
                    connection=connection,
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
                        connection=connection,
                        source=source,
                        entity=entity,
                        channel_username=channel_username,
                        post=post,
                        post_uid=post_uid,
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
        connection: sqlite3.Connection,
        source: dict[str, str],
        entity: Any,
        channel_username: str,
        post: Any,
        post_uid: str,
    ) -> None:
        replies = getattr(post, "replies", None)
        if not replies or not getattr(replies, "comments", False):
            print(f"Comments are not enabled for {channel_username}/{post.id}.")
            return

        collected_comments = 0
        try:
            async for comment in client.iter_messages(
                entity,
                reply_to=post.id,
                limit=self.config.scraping.comments_per_post,
            ):
                if not comment.message:
                    continue

                sender_id, sender_hash, sender_username = (
                    await self.extract_sender_data(comment)
                )
                save_comment(
                    connection=connection,
                    source=source,
                    channel_username=channel_username,
                    post_uid=post_uid,
                    post_id=post.id,
                    comment=comment,
                    sender_id=sender_id,
                    sender_hash=sender_hash,
                    sender_username=sender_username,
                )
                collected_comments += 1
        except MsgIdInvalidError:
            print(
                f"Comments cannot be resolved for {channel_username}/{post.id}; "
                "the post may have no linked discussion thread."
            )
            return
        except FloodWaitError as error:
            await self.handle_flood_wait(error)
            return
        except Exception as error:
            print(
                f"Could not scrape comments for {channel_username}/{post.id}: "
                f"{type(error).__name__}: {error}"
            )
            return

        print(
            f"Saved {collected_comments} comments for "
            f"{channel_username}/{post.id}"
        )

    async def extract_sender_data(
        self,
        comment: Any,
    ) -> tuple[str | None, str | None, str | None]:
        raw_sender_id = getattr(comment, "sender_id", None)
        sender_id: str | None = None
        sender_hash: str | None = None
        sender_username: str | None = None

        if raw_sender_id is not None:
            raw_sender_id_text = str(raw_sender_id)
            if self.config.privacy.save_sender_ids:
                sender_id = raw_sender_id_text
            if self.config.privacy.hash_sender_ids:
                salt = self.config.privacy.anonymization_salt
                if salt is None:
                    raise RuntimeError("Missing anonymization salt.")
                sender_hash = pseudonymize(raw_sender_id_text, salt)

        if self.config.privacy.save_usernames:
            sender = getattr(comment, "sender", None)
            if sender is None:
                sender = await comment.get_sender()
            sender_username = getattr(sender, "username", None) if sender else None

        return sender_id, sender_hash, sender_username

    async def handle_flood_wait(self, error: FloodWaitError) -> None:
        print(f"Telegram requested a wait of {error.seconds} seconds.")
        if self.config.scraping.stop_on_flood_wait:
            raise error
        await asyncio.sleep(error.seconds)

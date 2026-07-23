from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import asdict
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
    create_scrape_run,
    finish_run_source,
    finish_scrape_run,
    init_database,
    save_comment,
    save_post,
    save_source,
    start_run_source,
)
from src.export import export_scrape_run
from src.login_qr import ensure_authorized
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

    def _safe_config_snapshot(self) -> dict[str, Any]:
        """Return reproducibility settings without credentials or local secrets."""

        return {
            "scraping": asdict(self.config.scraping),
            "privacy": {
                "hash_sender_ids": self.config.privacy.hash_sender_ids,
                "save_sender_ids": self.config.privacy.save_sender_ids,
                "save_usernames": self.config.privacy.save_usernames,
            },
            "input": {
                "sources_file": Path(self.config.input.sources_file).name,
            },
        }

    async def run(self) -> str | None:
        sources = load_sources(self.config.input.sources_file)

        if not sources:
            print("No active sources found. Check your local sources.csv file.")
            return None

        session_path = Path(self.config.telegram.session_name)
        if session_path.parent != Path("."):
            session_path.parent.mkdir(parents=True, exist_ok=True)

        client = TelegramClient(
            self.config.telegram.session_name,
            self.config.telegram.api_id,
            self.config.telegram.api_hash,
        )

        await client.connect()
        run_id: str | None = None
        run_completed = False

        try:
            await ensure_authorized(client)

            connection = connect_database(self.config.database.path)
            init_database(connection)
            run_id = create_scrape_run(
                connection,
                self._safe_config_snapshot(),
            )
            print(f"Scrape run ID: {run_id}")

            try:
                for source in sources:
                    await self.scrape_source(
                        client=client,
                        connection=connection,
                        source=source,
                        run_id=run_id,
                    )

                    await polite_delay(
                        self.config.scraping.min_delay_seconds,
                        self.config.scraping.max_delay_seconds,
                    )

                finish_scrape_run(connection, run_id, status="completed")
                run_completed = True
            except Exception as error:
                finish_scrape_run(
                    connection,
                    run_id,
                    status="failed",
                    error_message=f"{type(error).__name__}: {error}",
                )
                raise
            finally:
                connection.close()
        finally:
            await client.disconnect()

        if (
            run_completed
            and run_id is not None
            and self.config.export.auto_export_after_scrape
        ):
            export_scrape_run(
                database_path=self.config.database.path,
                output_dir=self.config.export.output_dir,
                run_id=run_id,
            )

        return run_id

    async def scrape_source(
        self,
        client: TelegramClient,
        connection: sqlite3.Connection,
        source: dict[str, str],
        run_id: str,
    ) -> None:
        channel_username = source["telegram_username"]
        source_id = source["source_id"]
        print(f"\nScraping source: {channel_username}")

        save_source(connection, source)
        start_run_source(connection, run_id, source_id)

        try:
            entity = await client.get_entity(channel_username)
        except (ChannelPrivateError, UsernameInvalidError, UsernameNotOccupiedError) as error:
            message = f"{type(error).__name__}: {error}"
            print(f"Skipping inaccessible source {channel_username}: {message}")
            finish_run_source(
                connection,
                run_id,
                source_id,
                status="skipped",
                posts_collected=0,
                comments_collected=0,
                error_message=message,
            )
            return
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            print(f"Could not access {channel_username}: {message}")
            finish_run_source(
                connection,
                run_id,
                source_id,
                status="failed",
                posts_collected=0,
                comments_collected=0,
                error_message=message,
            )
            return

        collected_posts = 0
        collected_comments = 0

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
                    run_id=run_id,
                )
                collected_posts += 1
                print(
                    f"Saved post {collected_posts}/"
                    f"{self.config.scraping.posts_per_channel}: "
                    f"{channel_username}/{post.id}"
                )

                if self.config.scraping.scrape_comments:
                    collected_comments += await self.scrape_comments_for_post(
                        client=client,
                        connection=connection,
                        source=source,
                        entity=entity,
                        channel_username=channel_username,
                        post=post,
                        post_uid=post_uid,
                        run_id=run_id,
                    )

                connection.commit()

                if collected_posts % 10 == 0:
                    await polite_delay(
                        self.config.scraping.min_delay_seconds,
                        self.config.scraping.max_delay_seconds,
                    )
        except FloodWaitError as error:
            try:
                await self.handle_flood_wait(error)
            except FloodWaitError:
                finish_run_source(
                    connection,
                    run_id,
                    source_id,
                    status="failed",
                    posts_collected=collected_posts,
                    comments_collected=collected_comments,
                    error_message=f"FloodWaitError: {error}",
                )
                raise

            finish_run_source(
                connection,
                run_id,
                source_id,
                status="partial",
                posts_collected=collected_posts,
                comments_collected=collected_comments,
                error_message=f"FloodWaitError: {error}",
            )
            return
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            print(f"Error while scraping {channel_username}: {message}")
            finish_run_source(
                connection,
                run_id,
                source_id,
                status="failed",
                posts_collected=collected_posts,
                comments_collected=collected_comments,
                error_message=message,
            )
            return

        finish_run_source(
            connection,
            run_id,
            source_id,
            status="completed",
            posts_collected=collected_posts,
            comments_collected=collected_comments,
        )

    async def scrape_comments_for_post(
        self,
        client: TelegramClient,
        connection: sqlite3.Connection,
        source: dict[str, str],
        entity: Any,
        channel_username: str,
        post: Any,
        post_uid: str,
        run_id: str,
    ) -> int:
        replies = getattr(post, "replies", None)
        if not replies or not getattr(replies, "comments", False):
            print(f"Comments are not enabled for {channel_username}/{post.id}.")
            return 0

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
                    run_id=run_id,
                )
                collected_comments += 1
        except MsgIdInvalidError:
            print(
                f"Comments cannot be resolved for {channel_username}/{post.id}; "
                "the post may have no linked discussion thread."
            )
            return collected_comments
        except FloodWaitError as error:
            await self.handle_flood_wait(error)
            return collected_comments
        except Exception as error:
            print(
                f"Could not scrape comments for {channel_username}/{post.id}: "
                f"{type(error).__name__}: {error}"
            )
            return collected_comments

        print(
            f"Saved {collected_comments} comments for "
            f"{channel_username}/{post.id}"
        )
        return collected_comments

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

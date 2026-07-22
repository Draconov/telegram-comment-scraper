from __future__ import annotations

import asyncio
import sys
from getpass import getpass
from pathlib import Path

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from src.settings import load_config


def _prepare_session_directory(session_name: str) -> None:
    session_path = Path(session_name)

    if session_path.parent != Path("."):
        session_path.parent.mkdir(parents=True, exist_ok=True)


def _print_terminal_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)

    print("\nNo authorized Telegram session was found.")
    print("Scan this QR code in Telegram:")
    print("Settings → Devices → Link Desktop Device\n")

    qr.print_ascii(out=sys.stdout, invert=True)


async def ensure_authorized(client: TelegramClient) -> None:
    """Authorize an already connected Telegram client when necessary."""

    if await client.is_user_authorized():
        print("Existing Telegram session found.")
        return

    print("Telegram login is required.")

    while not await client.is_user_authorized():
        qr_login = await client.qr_login()
        _print_terminal_qr(qr_login.url)

        print("\nWaiting for QR scan...")
        print("The QR code will refresh automatically if it expires.")

        try:
            await qr_login.wait(timeout=120)

        except asyncio.TimeoutError:
            print("QR code expired. Generating a new one...")
            continue

        except SessionPasswordNeededError:
            password = getpass(
                "Enter your Telegram two-step verification password: "
            )
            await client.sign_in(password=password)

    print("Telegram login successful.")
    print("The session was saved locally. Starting the scraper...")


async def login_with_terminal_qr(
    config_path: str = "config.yaml",
) -> None:
    """Standalone login command kept as an optional utility."""

    config = load_config(config_path)
    _prepare_session_directory(config.telegram.session_name)

    client = TelegramClient(
        config.telegram.session_name,
        config.telegram.api_id,
        config.telegram.api_hash,
    )

    await client.connect()

    try:
        await ensure_authorized(client)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(login_with_terminal_qr())
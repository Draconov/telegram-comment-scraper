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
    print("\nScan this QR code in Telegram:")
    print("Settings → Devices → Link Desktop Device\n")
    qr.print_ascii(out=sys.stdout, invert=True)


async def login_with_terminal_qr(config_path: str = "config.yaml") -> None:
    config = load_config(config_path)
    _prepare_session_directory(config.telegram.session_name)

    client = TelegramClient(
        config.telegram.session_name,
        config.telegram.api_id,
        config.telegram.api_hash,
    )
    await client.connect()
    try:
        if await client.is_user_authorized():
            print("Telegram session is already authorized.")
            return

        while not await client.is_user_authorized():
            qr_login = await client.qr_login()
            _print_terminal_qr(qr_login.url)
            print("Waiting for the scan. The QR code refreshes if it expires.")
            try:
                await qr_login.wait(timeout=120)
            except asyncio.TimeoutError:
                print("QR code expired. Generating a new one...")
                continue
            except SessionPasswordNeededError:
                password = getpass("Telegram two-step verification password: ")
                await client.sign_in(password=password)

        print("Login successful. The local session file was saved in sessions/.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(login_with_terminal_qr())

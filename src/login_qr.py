import asyncio
from getpass import getpass
from pathlib import Path

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from src.settings import load_config


QR_OUTPUT_PATH = Path("telegram_login_qr.png")


async def main() -> None:
    config = load_config("config.yaml")

    client = TelegramClient(
        config.telegram.session_name,
        config.telegram.api_id,
        config.telegram.api_hash,
    )

    await client.connect()

    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"Already logged in as: {me.first_name} / id={me.id}")
            return

        qr_login = await client.qr_login()

        image = qrcode.make(qr_login.url)
        image.save(QR_OUTPUT_PATH)

        print("\nQR login image created:")
        print(QR_OUTPUT_PATH.resolve())
        print("\nOpen this image and scan it from Telegram:")
        print("Telegram mobile app → Settings → Devices → Link Desktop Device")
        print("\nWaiting for QR scan...")

        try:
            await qr_login.wait()

        except SessionPasswordNeededError:
            password = getpass("Telegram 2FA password: ")
            await client.sign_in(password=password)

        me = await client.get_me()
        print(f"\nLogin successful: {me.first_name} / id={me.id}")
        print("Session file saved. Now you can run:")
        print("python run_scraper.py")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
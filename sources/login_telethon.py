"""Одноразовый интерактивный вход в Telegram для Telethon.

Запускать ВРУЧНУЮ и ЛОКАЛЬНО (не в docker-compose up -d) перед первым
запуском проекта — если планируешь использовать источник "Telegram-каналы".
Спросит номер телефона, код из смс и (если включена) 2FA-пароль.
Создаёт файл config/telethon_session.session, который дальше монтируется
в контейнер как volume и переиспользуется без повторного входа.

Запуск:
    python -m sources.login_telethon
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient

from sources.telegram_channels import SESSION_PATH


async def main() -> None:
    load_dotenv()
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit(
            "Заполни TELEGRAM_API_ID и TELEGRAM_API_HASH в .env перед запуском "
            "(получить на https://my.telegram.org -> API development tools)"
        )

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(SESSION_PATH), int(api_id), api_hash)
    await client.start()  # спросит телефон/код/2FA в консоли, если сессия ещё не авторизована
    me = await client.get_me()
    print(f"Успешно вошли как {me.first_name} (id={me.id}). "
          f"Session сохранён в {SESSION_PATH}.session")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

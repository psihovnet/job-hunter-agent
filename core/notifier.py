"""Отправка найденных вакансий в Telegram."""
from __future__ import annotations

import os

from telegram import Bot

PREVIEW_CHARS = 1000

MESSAGE_TEMPLATE = (
    "🔹 {source}\n"
    "Совпало: {matched}\n\n"
    "{preview}\n\n"
    "Пост: {url}"
)


async def send(bot: Bot, item: dict) -> None:
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    preview = item.get("snippet", "")
    if len(preview) > PREVIEW_CHARS:
        preview = preview[:PREVIEW_CHARS].rstrip() + "…"
    text = MESSAGE_TEMPLATE.format(
        source=item.get("source", ""),
        matched=", ".join(item.get("matched") or []) or "— (фильтр не задан)",
        preview=preview,
        url=item.get("url") or "—",
    )
    if item.get("external_url"):
        text += f"\nСсылка из поста: {item['external_url']}"
    await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)

"""Главный цикл: Telegram-каналы -> фильтр по ключевым словам -> state -> notifier."""
from __future__ import annotations

import asyncio
import logging

from telegram import Bot

from core import notifier, state
from core.storage import load_keywords
from sources import telegram_channels

logger = logging.getLogger(__name__)


async def run_search_cycle(bot: Bot) -> dict:
    keywords = load_keywords()
    try:
        items = await telegram_channels.search(keywords)
    except Exception:
        logger.exception("orchestrator: чтение Telegram-каналов упало")
        items = []

    sent_count = 0
    for item in items:
        if state.is_new(item):
            await notifier.send(bot, item)
            state.mark_sent(item)
            sent_count += 1

    stats = {"found": len(items), "sent": sent_count}
    logger.info("Цикл поиска завершён: найдено=%d, отправлено=%d", stats["found"], stats["sent"])
    return stats


async def _main() -> None:
    """Ручной запуск одного цикла: python -m orchestrator (без Telegram-бота,
    уведомления печатаются в лог, а не отправляются, и не помечаются в state.db
    как отправленные — чтобы потом их прислал настоящий бот)."""
    import os

    from dotenv import load_dotenv

    load_dotenv()
    os.environ.setdefault("TELEGRAM_CHAT_ID", "dry-run")
    keywords = load_keywords()
    items = await telegram_channels.search(keywords)
    for item in items:
        status = "новое" if state.is_new(item) else "уже отправлялось"
        logger.info("[%s] %s | %s | совпало: %s", status, item["source"], item["url"],
                    ", ".join(item["matched"]) or "—")
    logger.info("Всего подходящих постов: %d", len(items))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())

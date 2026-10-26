"""Точка входа контейнера: поднимает Telegram-бота (команды) и планировщик
циклов поиска в одном asyncio-процессе (через JobQueue бота)."""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import Application

from bot.bot_commands import register

LOG_PATH = Path(__file__).resolve().parent / "job-hunter.log"

BOT_COMMANDS = [
    BotCommand("keywords", "Показать ключевые слова"),
    BotCommand("add_keyword", "Добавить слова для поиска (через запятую)"),
    BotCommand("remove_keyword", "Убрать слова для поиска"),
    BotCommand("add_exclude", "Добавить стоп-слова (через запятую)"),
    BotCommand("remove_exclude", "Убрать стоп-слова"),
    BotCommand("groups", "Готовые группы каналов: СНГ / зарубеж, финтех, геймдев"),
    BotCommand("add_channel", "Добавить Telegram-канал"),
    BotCommand("remove_channel", "Убрать канал"),
    BotCommand("list_channels", "Показать список каналов"),
    BotCommand("my_channels", "Мои каналы (в т.ч. закрытые); можно с поиском"),
    BotCommand("search_now", "Запустить поиск прямо сейчас"),
    BotCommand("pause", "Приостановить поиск"),
    BotCommand("resume", "Возобновить поиск"),
    BotCommand("stats", "Сколько вакансий отправлено за 24 часа"),
]


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)


def _setup_logging() -> None:
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )
    # httpx на INFO логирует полный URL запроса, включая TELEGRAM_BOT_TOKEN в пути —
    # поднимаем порог, чтобы токен не оседал в логах на диске.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    load_dotenv()
    _setup_logging()

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    application = Application.builder().token(token).post_init(_post_init).build()
    register(application)

    logging.getLogger(__name__).info("job-hunter-agent запускается")
    application.run_polling()


if __name__ == "__main__":
    main()

"""Команды Telegram-бота: каналы, ключевые слова, пауза, статистика.

Все команды доступны только владельцу (TELEGRAM_CHAT_ID) — если написать
боту с другого аккаунта, команды молча игнорируются.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from functools import wraps
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot import groups
from core import state
from core.storage import load_channels, load_groups, load_keywords, save_channels, save_keywords
from orchestrator import run_search_cycle
from sources import telegram_channels

logger = logging.getLogger(__name__)

PAUSED_PATH = Path(__file__).resolve().parent.parent / "config" / "PAUSED"

# @name, name, t.me/name, https://t.me/name/123, https://t.me/s/name
CHANNEL_RE = re.compile(r"^(?:https?://)?(?:t\.me/|telegram\.me/)?(?:s/)?@?([A-Za-z][A-Za-z0-9_]{3,31})(?:/\d+)?/?$")
# Закрытый канал: id (как в /my_channels), -100<id>, или ссылка на пост t.me/c/<id>/123
PRIVATE_RE = re.compile(r"^(?:(?:https?://)?t\.me/c/(\d+)(?:/\d+)?/?|-100(\d+)|(\d+))$")


def _owner_only(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        owner_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if str(update.effective_chat.id) != str(owner_chat_id):
            logger.warning("Игнорирую команду от постороннего чата %s", update.effective_chat.id)
            return
        return await handler(update, context)
    return wrapper


def _parse_channel_ref(raw: str) -> str | int | None:
    """'@username' для публичного канала, int id для закрытого, None если не понятно."""
    raw = raw.strip()
    private = PRIVATE_RE.match(raw)
    if private:
        return int(next(g for g in private.groups() if g))
    found = CHANNEL_RE.match(raw)
    return f"@{found.group(1).lower()}" if found else None


def _parse_words(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    """Аргументы команды через запятую: '/add_keyword python, team lead'."""
    raw = " ".join(context.args or [])
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


# ---------- каналы ----------

async def _with_telegram(context: ContextTypes.DEFAULT_TYPE, coro_fn):
    """Команды, которым нужна Telethon-сессия, ждут окончания идущего поиска
    (см. _run_cycle_locked) — иначе sqlite-файл сессии будет занят."""
    async with context.bot_data["search_lock"]:
        return await coro_fn()


@_owner_only
async def cmd_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Использование: /add_channel @username (канал или бот, можно несколько через пробел)\n"
            "Закрытый/платный канал: /add_channel <id> — id смотри в /my_channels"
        )
        return
    config = load_channels()
    existing = {c.key for c in config.channels}
    lines = []
    for raw in context.args:
        ref = _parse_channel_ref(raw)
        if ref is None:
            lines.append(f"✗ {raw}: не понял — нужен @username, ссылка t.me/... или id из /my_channels")
            continue
        try:
            channel = await _with_telegram(context, lambda: telegram_channels.resolve_channel(ref))
        except telegram_channels.TelegramNotReady as exc:
            await update.message.reply_text(f"Telegram-аккаунт не подключён: {exc}")
            return
        except ValueError as exc:
            lines.append(f"✗ {raw}: {exc}")
            continue
        if channel.key in existing:
            lines.append(f"• {channel.display} — уже в списке")
            continue
        config.channels.append(channel)
        existing.add(channel.key)
        lines.append(f"✓ {channel.display} — добавлен")
    save_channels(config)
    await update.message.reply_text("\n".join(lines))


@_owner_only
async def cmd_remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /remove_channel @username или id")
        return
    targets = {str(_parse_channel_ref(raw) or raw) for raw in context.args}
    config = load_channels()
    removed = [c.display for c in config.channels if c.key in targets]
    if not removed:
        await update.message.reply_text("Таких каналов нет в списке. /list_channels — посмотреть список.")
        return
    config.channels = [c for c in config.channels if c.key not in targets]
    save_channels(config)
    await update.message.reply_text("Удалил: " + ", ".join(removed))


@_owner_only
async def cmd_list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = load_channels()
    if not config.channels:
        await update.message.reply_text("Список каналов пуст. Добавь: /add_channel @username")
        return
    group_titles = {g.id: g.title for g in load_groups().groups}
    lines = []
    for c in config.channels:
        tags = [group_titles.get(g, g) for g in c.groups]
        lines.append(f"- {c.display}" + (f" [группа: {', '.join(tags)}]" if tags else ""))
    await update.message.reply_text(f"Каналы ({len(lines)}):\n" + "\n".join(lines)
                                    + "\n\nУдалить: /remove_channel @username или id")


@_owner_only
async def cmd_my_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        found = await _with_telegram(context, telegram_channels.list_my_channels)
    except telegram_channels.TelegramNotReady as exc:
        await update.message.reply_text(f"Telegram-аккаунт не подключён: {exc}")
        return
    query = " ".join(context.args or []).lower()
    if query:
        found = [ch for ch in found if query in ch["title"].lower() or query in ch["username"]]
    if not found:
        await update.message.reply_text("Ничего не нашлось." if query else
                                        "Аккаунт не состоит ни в одном канале или группе.")
        return
    added = {c.key for c in load_channels().channels}
    lines = []
    for ch in found:
        ref = ch["username"] or str(ch["id"])
        mark = "✓ " if ref in added else ""
        kind = " 🤖" if ch["is_bot"] else ("" if ch["username"] else " 🔒")
        lines.append(f"{mark}{ch['title']}{kind}\n    /add_channel {ref}")
    header = ("Каналы, группы и боты твоего аккаунта (🔒 — закрытый, 🤖 — бот, ✓ — уже добавлен).\n"
              "Скопируй нужную команду и отправь. Поиск по названию: /my_channels вакансии\n\n")
    await _reply_long(update, header + "\n".join(lines))


async def _reply_long(update: Update, text: str, limit: int = 4000) -> None:
    """Telegram не принимает сообщения длиннее 4096 символов — режем по строкам."""
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > limit:
            await update.message.reply_text(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await update.message.reply_text(chunk)


# ---------- ключевые слова ----------

def _format_keywords() -> str:
    kw = load_keywords()
    include = ", ".join(kw.include) if kw.include else "— пусто (присылаются ВСЕ посты из каналов)"
    exclude = ", ".join(kw.exclude) if kw.exclude else "—"
    return f"Искать (любое из): {include}\nИсключать: {exclude}"


async def _change_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           field: str, add: bool, usage: str) -> None:
    words = _parse_words(context)
    if not words:
        await update.message.reply_text(usage)
        return
    kw = load_keywords()
    current: list[str] = getattr(kw, field)
    if add:
        current.extend(w for w in words if w not in current)
    else:
        missing = [w for w in words if w not in current]
        current[:] = [w for w in current if w not in words]
        if missing:
            await update.message.reply_text("Не было в списке: " + ", ".join(missing))
    save_keywords(kw)
    await update.message.reply_text("Готово.\n\n" + _format_keywords())


@_owner_only
async def cmd_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_format_keywords())


@_owner_only
async def cmd_add_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_keywords(update, context, "include", True,
                           "Использование: /add_keyword python, team lead, разработ*")


@_owner_only
async def cmd_remove_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_keywords(update, context, "include", False,
                           "Использование: /remove_keyword python, team lead")


@_owner_only
async def cmd_add_exclude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_keywords(update, context, "exclude", True,
                           "Использование: /add_exclude junior, стажёр")


@_owner_only
async def cmd_remove_exclude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_keywords(update, context, "exclude", False,
                           "Использование: /remove_exclude junior")


# ---------- управление поиском ----------

@_owner_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    PAUSED_PATH.touch()
    await update.message.reply_text("Поставлено на паузу. /resume — чтобы возобновить.")


@_owner_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    PAUSED_PATH.unlink(missing_ok=True)
    await update.message.reply_text("Возобновлено.")


@_owner_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = state.count_sent_last_24h()
    await update.message.reply_text(f"Отправлено вакансий за последние 24 часа: {count}")


async def _run_cycle_locked(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    """Telethon-сессия — это sqlite-файл, два клиента одновременно ловят
    'database is locked', поэтому ручной и плановый циклы не пересекаются."""
    lock: asyncio.Lock = context.bot_data["search_lock"]
    if lock.locked():
        return None
    async with lock:
        return await run_search_cycle(context.bot)


@_owner_only
async def cmd_search_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Ищу…")
    try:
        stats = await _run_cycle_locked(context)
    except Exception:
        logger.exception("Ручной цикл поиска упал")
        await update.message.reply_text("Поиск упал, подробности в job-hunter.log")
        return
    if stats is None:
        await update.message.reply_text("Поиск уже идёт, подожди немного.")
        return
    await update.message.reply_text(
        f"Готово: подходящих постов {stats['found']}, новых отправлено {stats['sent']}."
    )


async def scheduled_search_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if PAUSED_PATH.exists():
        logger.info("Пропуск цикла: стоит на паузе (PAUSED)")
        return
    try:
        if await _run_cycle_locked(context) is None:
            logger.info("Пропуск планового цикла: предыдущий ещё идёт")
    except Exception:
        logger.exception("Цикл поиска упал целиком")


def register(application: Application) -> None:
    application.bot_data["search_lock"] = asyncio.Lock()

    handlers = {
        "add_channel": cmd_add_channel,
        "remove_channel": cmd_remove_channel,
        "list_channels": cmd_list_channels,
        "my_channels": cmd_my_channels,
        "keywords": cmd_keywords,
        "add_keyword": cmd_add_keyword,
        "remove_keyword": cmd_remove_keyword,
        "add_exclude": cmd_add_exclude,
        "remove_exclude": cmd_remove_exclude,
        "search_now": cmd_search_now,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "stats": cmd_stats,
    }
    for name, handler in handlers.items():
        application.add_handler(CommandHandler(name, handler))
    groups.register(application, _owner_only)

    poll_minutes = int(os.environ.get("POLL_INTERVAL_MINUTES", "60"))
    application.job_queue.run_repeating(scheduled_search_job, interval=poll_minutes * 60, first=10)

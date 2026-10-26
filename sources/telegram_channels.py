"""Чтение Telegram-каналов через Telethon (юзер-аккаунт, read-only).

Требует уже авторизованный session-файл — см. sources/login_telethon.py.
Читает только каналы из config/tg_channels.json (их задаёт владелец через
/add_channel) и оставляет посты, подходящие под config/keywords.json.
Закрытые (платные) каналы тоже читаются — если аккаунт в них состоит.
Боты тоже: читаются сообщения, которые бот прислал в личку этому аккаунту.
"""
from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import Channel, MessageEntityTextUrl, PeerChannel, User

from core import matcher
from core.config_schema import Keywords, TgChannel
from core.storage import load_channels

logger = logging.getLogger(__name__)

SESSION_PATH = Path(__file__).resolve().parent.parent / "config" / "telethon_session"
URL_RE = re.compile(r"https?://\S+")


class TelegramNotReady(RuntimeError):
    """Не заданы API_ID/HASH или нет авторизованной сессии."""


@asynccontextmanager
async def connected_client():
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise TelegramNotReady("TELEGRAM_API_ID/TELEGRAM_API_HASH не заданы")
    if not SESSION_PATH.with_suffix(".session").exists():
        raise TelegramNotReady(
            f"session-файл не найден ({SESSION_PATH}) — запусти python -m sources.login_telethon"
        )
    client = TelegramClient(str(SESSION_PATH), int(api_id), api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise TelegramNotReady("session не авторизована — запусти python -m sources.login_telethon")
        yield client
    finally:
        await client.disconnect()


async def _entity(client: TelegramClient, ref: str | int):
    """ref — '@username' или числовой id канала. Для закрытого канала Telethon
    знает access_hash только после того, как увидел его в списке диалогов."""
    if isinstance(ref, str):
        return await client.get_entity(ref)
    try:
        return await client.get_entity(PeerChannel(ref))
    except ValueError:
        await client.get_dialogs()
        return await client.get_entity(PeerChannel(ref))


async def resolve_channel(ref: str | int) -> TgChannel:
    """Проверяет, что канал (или бот) существует и аккаунт его видит. Бросает
    ValueError с понятным текстом, если это обычный пользователь."""
    async with connected_client() as client:
        try:
            entity = await _entity(client, ref)
        except Exception as exc:
            raise ValueError("не найден или аккаунт не имеет к нему доступа") from exc
    if isinstance(entity, User):
        if not entity.bot:
            raise ValueError("это обычный пользователь, а не канал или бот")
        return TgChannel(
            username=f"@{entity.username.lower()}",
            title=entity.first_name or "",
            is_bot=True,
            added_at=datetime.now(timezone.utc).date(),
        )
    if not isinstance(entity, Channel):
        raise ValueError("это не канал, не группа и не бот")
    username = f"@{entity.username.lower()}" if entity.username else ""
    return TgChannel(
        username=username,
        channel_id=None if username else entity.id,
        title=entity.title or "",
        added_at=datetime.now(timezone.utc).date(),
    )


async def list_my_channels() -> list[dict]:
    """Все каналы, группы и боты из диалогов аккаунта — чтобы найти id закрытых."""
    result = []
    async with connected_client() as client:
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, Channel):
                result.append({
                    "id": entity.id,
                    "title": entity.title or "",
                    "username": f"@{entity.username.lower()}" if entity.username else "",
                    "is_bot": False,
                })
            elif isinstance(entity, User) and entity.bot and entity.username:
                result.append({
                    "id": entity.id,
                    "title": entity.first_name or "",
                    "username": f"@{entity.username.lower()}",
                    "is_bot": True,
                })
    return result


def _post_url(channel: TgChannel, message_id: int) -> str:
    if channel.is_bot:
        # У сообщений в личке с ботом нет ссылки на пост — ведём в сам чат.
        return f"https://t.me/{channel.username.lstrip('@')}"
    if channel.username:
        return f"https://t.me/{channel.username.lstrip('@')}/{message_id}"
    # Формат ссылки на пост закрытого канала — открывается у участников.
    return f"https://t.me/c/{channel.channel_id}/{message_id}"


def _extract_url(message) -> str:
    # Ссылка, спрятанная под текстом ("Откликнуться" -> https://...).
    for entity in message.entities or []:
        if isinstance(entity, MessageEntityTextUrl):
            return entity.url
    if message.raw_text:
        found = URL_RE.search(message.raw_text)
        if found:
            return found.group(0)
    if message.buttons:
        for row in message.buttons:
            for button in row:
                if getattr(button, "url", None):
                    return button.url
    return ""


async def search(keywords: Keywords) -> list[dict]:
    channels = load_channels().channels
    if not channels:
        logger.info("telegram_channels: список каналов пуст — добавь через /add_channel")
        return []

    lookback_hours = int(os.environ.get("TG_CHANNEL_LOOKBACK_HOURS", "24"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    items: list[dict] = []
    try:
        async with connected_client() as client:
            for channel in channels:
                checked = 0
                try:
                    entity = await _entity(client, channel.username or channel.channel_id)
                    async for message in client.iter_messages(entity, limit=200):
                        if message.date < cutoff:
                            break
                        if message.out:
                            continue  # свои сообщения в чате с ботом (/start и т.п.)
                        # raw_text — без markdown-разметки (**, [текст](url)).
                        text = message.raw_text or ""
                        if not text:
                            continue
                        checked += 1
                        matched = matcher.match(text, keywords)
                        if matched is None:
                            continue
                        items.append({
                            "title": text.splitlines()[0][:120],
                            # Ссылка на сам пост — уникальна, поэтому по ней же
                            # работает дедупликация в core/state.py.
                            "url": _post_url(channel, message.id),
                            # У бота url один на все сообщения — нужен свой ключ.
                            "dedup_key": f"tg:{channel.key}:{message.id}" if channel.is_bot else "",
                            "external_url": _extract_url(message),
                            "snippet": text,
                            "matched": matched,
                            "source": channel.title or channel.username or str(channel.channel_id),
                        })
                except Exception as exc:
                    logger.error("telegram_channels: ошибка чтения канала %s: %s", channel.display, exc)
                else:
                    logger.info("telegram_channels: %s — проверено постов: %d", channel.display, checked)
    except TelegramNotReady as exc:
        logger.error("telegram_channels: %s", exc)
        return []

    return items

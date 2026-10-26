"""Группы каналов (config/channel_groups.json): /groups показывает кнопки,
нажатие подключает или отключает группу целиком.

Подключение группы добавляет её каналы в tg_channels.json с пометкой группы;
отключение убирает пометку и удаляет каналы, которые больше ни в одной
подключённой группе не состоят и не были добавлены вручную.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from core.config_schema import ChannelGroup
from core.storage import load_channels, load_groups, save_channels
from sources import telegram_channels

logger = logging.getLogger(__name__)

REGIONS = {"cis": "🇷🇺 Россия и СНГ", "abroad": "🌍 Зарубежные"}


def _connected_ids() -> set[str]:
    return {g for c in load_channels().channels for g in c.groups}


def _keyboard() -> InlineKeyboardMarkup:
    connected = _connected_ids()
    rows = []
    groups = load_groups().groups
    for region, region_title in REGIONS.items():
        region_groups = [g for g in groups if g.region == region]
        if not region_groups:
            continue
        rows.append([InlineKeyboardButton(region_title, callback_data="grp:noop")])
        for g in region_groups:
            mark = "✅" if g.id in connected else "➕"
            rows.append([InlineKeyboardButton(f"{mark} {g.title} ({len(g.channels)})",
                                              callback_data=f"grp:toggle:{g.id}")])
    return InlineKeyboardMarkup(rows)


HELP_TEXT = ("Группы каналов. Нажми на группу, чтобы подключить ➕ или отключить ✅.\n"
             "Каналы, добавленные вручную через /add_channel, при отключении группы остаются.")


async def cmd_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, reply_markup=_keyboard())


async def _connect(group: ChannelGroup) -> list[str]:
    config = load_channels()
    by_key = {c.key: c for c in config.channels}
    report = []
    for username in group.channels:
        username = username.lower()
        if username in by_key:
            if group.id not in by_key[username].groups:
                by_key[username].groups.append(group.id)
            continue
        try:
            channel = await telegram_channels.resolve_channel(username)
        except ValueError as exc:
            report.append(f"✗ {username}: {exc}")
            continue
        channel.manual = False
        channel.groups = [group.id]
        config.channels.append(channel)
        by_key[channel.key] = channel
    save_channels(config)
    return report


def _disconnect(group: ChannelGroup) -> int:
    config = load_channels()
    kept, removed = [], 0
    for c in config.channels:
        if group.id in c.groups:
            c.groups.remove(group.id)
            if not c.groups and not c.manual:
                removed += 1
                continue
        kept.append(c)
    config.channels = kept
    save_channels(config)
    return removed


async def on_group_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, *rest = query.data.split(":")
    if action != "toggle":
        await query.answer()
        return
    group = next((g for g in load_groups().groups if g.id == rest[0]), None)
    if group is None:
        await query.answer("Группа не найдена", show_alert=True)
        return

    if group.id in _connected_ids():
        removed = _disconnect(group)
        await query.answer(f"Отключено: {group.title}")
        status = f"Отключил «{group.title}», убрал каналов: {removed}."
    else:
        await query.answer("Подключаю, проверяю каналы…")
        try:
            async with context.bot_data["search_lock"]:
                report = await _connect(group)
        except telegram_channels.TelegramNotReady as exc:
            await query.message.reply_text(f"Telegram-аккаунт не подключён: {exc}")
            return
        status = f"Подключил «{group.title}»."
        if report:
            status += "\n" + "\n".join(report)
    await query.edit_message_text(f"{HELP_TEXT}\n\n{status}", reply_markup=_keyboard())


def register(application, owner_only) -> None:
    application.add_handler(CommandHandler("groups", owner_only(cmd_groups)))
    application.add_handler(CallbackQueryHandler(owner_only(on_group_button), pattern=r"^grp:"))

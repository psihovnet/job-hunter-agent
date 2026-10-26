"""Pydantic-схемы для config/tg_channels.json и config/keywords.json."""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class TgChannel(BaseModel):
    # У публичного канала есть username ("@name"). У закрытого (платного,
    # по инвайту) его нет — такой канал хранится по channel_id, и читать его
    # можно, только если аккаунт Telethon-сессии в нём состоит.
    username: str = ""
    channel_id: Optional[int] = None
    title: str = ""
    # Бот, который пишет владельцу в личку: читаем его сообщения в этом чате.
    is_bot: bool = False
    # Добавлен вручную (/add_channel) — такой канал не удаляется при
    # отключении группы, даже если он в неё входит.
    manual: bool = True
    # Подключённые группы (config/channel_groups.json), в которые входит канал.
    groups: list[str] = Field(default_factory=list)
    added_at: date
    note: str = ""

    @property
    def key(self) -> str:
        return str(self.channel_id) if self.channel_id is not None else self.username

    @property
    def display(self) -> str:
        if self.username:
            name = f"{self.title} ({self.username})" if self.title else self.username
            return f"🤖 {name}" if self.is_bot else name
        return f"{self.title or 'без названия'} (закрытый, id {self.channel_id})"


class TgChannelsConfig(BaseModel):
    channels: list[TgChannel] = Field(default_factory=list)


class ChannelGroup(BaseModel):
    id: str
    region: str  # "cis" | "abroad"
    title: str
    channels: list[str]


class ChannelGroupsConfig(BaseModel):
    groups: list[ChannelGroup] = Field(default_factory=list)


class Keywords(BaseModel):
    # Пост проходит, если в нём есть ХОТЯ БЫ ОДНО слово из include
    # (пустой include = присылать все посты из каналов).
    include: list[str] = Field(default_factory=list)
    # Пост отбрасывается, если в нём есть ЛЮБОЕ слово из exclude.
    exclude: list[str] = Field(default_factory=list)

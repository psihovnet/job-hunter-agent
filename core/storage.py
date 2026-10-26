"""Чтение/запись config/tg_channels.json и config/keywords.json — в одном
месте, чтобы бот и источник не дублировали пути и валидацию."""
from __future__ import annotations

import json
from pathlib import Path

from core.config_schema import ChannelGroupsConfig, Keywords, TgChannelsConfig

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
TG_CHANNELS_PATH = CONFIG_DIR / "tg_channels.json"
KEYWORDS_PATH = CONFIG_DIR / "keywords.json"
GROUPS_PATH = CONFIG_DIR / "channel_groups.json"


def load_channels() -> TgChannelsConfig:
    if not TG_CHANNELS_PATH.exists():
        return TgChannelsConfig()
    return TgChannelsConfig.model_validate(json.loads(TG_CHANNELS_PATH.read_text(encoding="utf-8")))


def save_channels(config: TgChannelsConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TG_CHANNELS_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")


def load_groups() -> ChannelGroupsConfig:
    if not GROUPS_PATH.exists():
        return ChannelGroupsConfig()
    return ChannelGroupsConfig.model_validate(json.loads(GROUPS_PATH.read_text(encoding="utf-8")))


def load_keywords() -> Keywords:
    if not KEYWORDS_PATH.exists():
        return Keywords()
    return Keywords.model_validate(json.loads(KEYWORDS_PATH.read_text(encoding="utf-8")))


def save_keywords(keywords: Keywords) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    KEYWORDS_PATH.write_text(keywords.model_dump_json(indent=2), encoding="utf-8")

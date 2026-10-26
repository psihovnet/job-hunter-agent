"""Фильтрация постов по ключевым словам из config/keywords.json.

Слово ищется целиком, без учёта регистра: "java" не совпадёт с "javascript".
Звёздочка заменяет любое окончание слова — "разработ*" найдёт
"разработчик", "разработчика", "разработка" (удобно для русских окончаний).
Фразы из нескольких слов тоже работают, звёздочка — в любом из слов:
"руководител* проект*" найдёт "руководителя проектов".
"""
from __future__ import annotations

import re
from functools import lru_cache

from core.config_schema import Keywords


@lru_cache(maxsize=512)
def _pattern(keyword: str) -> re.Pattern:
    body = re.escape(keyword.strip().lower()).replace(r"\*", r"\w*")
    # \w в Python-регулярках понимает и кириллицу.
    return re.compile(rf"(?<!\w){body}(?!\w)")


def _contains(text: str, keyword: str) -> bool:
    return bool(_pattern(keyword).search(text))


def match(text: str, keywords: Keywords) -> list[str] | None:
    """Возвращает список совпавших include-слов, если пост подходит, иначе None.

    Если include пуст — подходит любой пост без exclude-слов (список будет пустым).
    """
    text_lower = text.lower()
    if any(_contains(text_lower, kw) for kw in keywords.exclude):
        return None
    if not keywords.include:
        return []
    matched = [kw for kw in keywords.include if _contains(text_lower, kw)]
    return matched or None

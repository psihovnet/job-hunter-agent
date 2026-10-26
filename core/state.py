"""SQLite-обёртка для дедупликации вакансий."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DB_PATH = Path(__file__).resolve().parent.parent / "state.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    item_hash TEXT UNIQUE NOT NULL,
    title TEXT,
    url TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def _normalize_url(url: str) -> str:
    """Убирает query-строку и fragment, чтобы одна и та же вакансия с
    разными трекинг-параметрами (?utm=...) не считалась разной."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def compute_hash(item: dict) -> str:
    if item.get("dedup_key"):
        basis = item["dedup_key"]
    elif item.get("url"):
        basis = _normalize_url(item["url"])
    else:
        basis = f"{item.get('source', '')}:{item.get('title', '')}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def is_new(item: dict) -> bool:
    item_hash = compute_hash(item)
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_items WHERE item_hash = ?", (item_hash,)
        ).fetchone()
    return row is None


def mark_sent(item: dict) -> None:
    item_hash = compute_hash(item)
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_items (source, item_hash, title, url) "
            "VALUES (?, ?, ?, ?)",
            (item.get("source"), item_hash, item.get("title"), item.get("url")),
        )


def count_sent_last_24h() -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM sent_items WHERE sent_at >= ?",
            (since.strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchone()
    return row[0] if row else 0

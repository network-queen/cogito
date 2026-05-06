from __future__ import annotations

import sqlite3


DEFAULT_MEMORY_MODEL = "ollama:qwen3:0.6b"
DEFAULT_EMBEDDING_MODEL = "ollama:nomic-embed-text"


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> str:
    conn.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """,
        (key, value),
    )
    conn.commit()
    return value


def get_memory_model(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "memory_model", DEFAULT_MEMORY_MODEL) or DEFAULT_MEMORY_MODEL


def set_memory_model(conn: sqlite3.Connection, value: str) -> str:
    return set_setting(conn, "memory_model", normalize_memory_model(value))


def get_embedding_model(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "embedding_model", DEFAULT_EMBEDDING_MODEL) or DEFAULT_EMBEDDING_MODEL


def set_embedding_model(conn: sqlite3.Connection, value: str) -> str:
    return set_setting(conn, "embedding_model", normalize_memory_model(value))


def normalize_memory_model(value: str) -> str:
    model = value.strip()
    if not model:
        return DEFAULT_MEMORY_MODEL
    if model in {"heuristic", "off"}:
        return model
    if ":" not in model:
        return f"ollama:{model}"
    if model.startswith("hf:"):
        return model
    if model.startswith("ollama:"):
        return model
    return f"ollama:{model}"

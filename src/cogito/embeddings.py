from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from .local_extractor import ollama_embed
from .settings import get_embedding_model


def embed_text(text: str, model_spec: str) -> tuple[list[float], str]:
    if model_spec == "off":
        raise RuntimeError("embedding model disabled")
    if model_spec.startswith("ollama:"):
        model = model_spec.removeprefix("ollama:")
        return ollama_embed(model, text), f"ollama:{model}"
    raise RuntimeError(f"unsupported embedding model: {model_spec}")


def embed_query(conn: sqlite3.Connection, query: str) -> tuple[list[float], str]:
    return embed_text(query, get_embedding_model(conn))


def ensure_memory_embedding(conn: sqlite3.Connection, memory: dict[str, Any]) -> dict[str, Any]:
    model = get_embedding_model(conn)
    if model == "off":
        return memory
    if memory.get("embedding") and memory.get("embedding_model") == model:
        return memory
    vector, model_name = embed_text(memory["text"], model)
    conn.execute(
        """
        UPDATE memories
        SET embedding = ?, embedding_model = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (json.dumps(vector), model_name, memory["id"]),
    )
    conn.commit()
    return memory | {"embedding": vector, "embedding_model": model_name}


def decode_embedding(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [float(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return [float(item) for item in parsed]
    return None


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)

from __future__ import annotations

import json
import sqlite3
import urllib.parse
import urllib.request
from typing import Any

from .db import row_to_dict, rows_to_dicts
from .embeddings import cosine_similarity, decode_embedding, embed_query, embed_text
from .ids import new_id
from .memory import score_memory
from .personas import get_persona
from .settings import get_embedding_model


def add_persona_knowledge(
    conn: sqlite3.Connection,
    *,
    persona_name: str,
    text: str,
    knowledge_type: str = "fact",
    source_url: str | None = None,
    confidence: float = 0.8,
) -> dict[str, Any]:
    persona = get_persona(conn, persona_name)
    item_id = new_id("pkg")
    conn.execute(
        """
        INSERT INTO persona_knowledge (id, persona_id, text, type, source_url, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_id, persona["id"], text.strip(), knowledge_type, source_url, confidence),
    )
    conn.commit()
    item = get_persona_knowledge(conn, item_id)
    try:
        item = ensure_persona_knowledge_embedding(conn, item)
    except Exception:
        pass
    return item


def get_persona_knowledge(conn: sqlite3.Connection, item_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM persona_knowledge WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"persona knowledge not found: {item_id}")
    return row_to_dict(row)


def list_persona_knowledge(conn: sqlite3.Connection, *, persona_name: str) -> list[dict[str, Any]]:
    persona = get_persona(conn, persona_name)
    rows = conn.execute(
        """
        SELECT * FROM persona_knowledge
        WHERE persona_id = ? AND state != 'deleted'
        ORDER BY created_at DESC
        """,
        (persona["id"],),
    ).fetchall()
    return rows_to_dicts(rows)


def delete_persona_knowledge(conn: sqlite3.Connection, item_id: str) -> dict[str, Any]:
    conn.execute(
        "UPDATE persona_knowledge SET state = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (item_id,),
    )
    conn.commit()
    return get_persona_knowledge(conn, item_id)


def search_persona_knowledge(
    conn: sqlite3.Connection,
    *,
    persona_name: str,
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    items = list_persona_knowledge(conn, persona_name=persona_name)
    vector_results = search_persona_knowledge_by_embedding(conn, query=query, items=items, limit=limit)
    if vector_results:
        return vector_results
    scored = [(score_memory(query, item | {"contexts": []}), item) for item in items]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item | {"score": score} for score, item in scored[:limit] if score > 0]


def search_persona_knowledge_by_embedding(
    conn: sqlite3.Connection,
    *,
    query: str,
    items: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if not any(item.get("embedding") for item in items):
        return []
    try:
        query_vector, model = embed_query(conn, query)
    except Exception:
        return []
    scored = []
    for item in items:
        if item.get("embedding_model") != model or not item.get("embedding"):
            continue
        vector = decode_embedding(item.get("embedding"))
        if vector is None:
            continue
        score = cosine_similarity(query_vector, vector)
        if score > 0.2:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item | {"score": score, "score_source": "embedding"} for score, item in scored[:limit]]


def ensure_persona_knowledge_embedding(conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
    model = get_embedding_model(conn)
    if model == "off":
        return item
    if item.get("embedding") and item.get("embedding_model") == model:
        return item
    vector, model_name = embed_text(item["text"], model)
    conn.execute(
        """
        UPDATE persona_knowledge
        SET embedding = ?, embedding_model = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (json.dumps(vector), model_name, item["id"]),
    )
    conn.commit()
    return item | {"embedding": vector, "embedding_model": model_name}


def build_persona_knowledge_context(
    conn: sqlite3.Connection,
    *,
    persona_name: str,
    query: str,
    limit: int = 8,
) -> str:
    items = search_persona_knowledge(conn, persona_name=persona_name, query=query, limit=limit)
    if not items:
        return ""
    lines = ["Persona knowledge:"]
    for item in items:
        source = f" ({item['source_url']})" if item.get("source_url") else ""
        lines.append(f"- [{item['type']}] {item['text']}{source}")
    return "\n".join(lines)


def research_persona_from_wikipedia(
    conn: sqlite3.Connection,
    *,
    persona_name: str,
    subject: str,
    limit: int = 24,
) -> list[dict[str, Any]]:
    page = fetch_wikipedia_extract(subject)
    chunks = chunk_text(page["extract"], max_chars=700)[:limit]
    created = []
    if page.get("description"):
        created.append(
            add_persona_knowledge(
                conn,
                persona_name=persona_name,
                text=page["description"],
                knowledge_type="summary",
                source_url=page["url"],
                confidence=0.75,
            )
        )
    for chunk in chunks:
        created.append(
            add_persona_knowledge(
                conn,
                persona_name=persona_name,
                text=chunk,
                knowledge_type="research",
                source_url=page["url"],
                confidence=0.7,
            )
        )
    return created


def fetch_wikipedia_extract(subject: str) -> dict[str, str]:
    title = urllib.parse.quote(subject.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    req = urllib.request.Request(url, headers={"User-Agent": "cogito-ergo-sum/0.1"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    extract = str(data.get("extract") or "").strip()
    if not extract:
        raise RuntimeError(f"no Wikipedia extract found for {subject}")
    page_url = data.get("content_urls", {}).get("desktop", {}).get("page") or f"https://en.wikipedia.org/wiki/{title}"
    return {
        "extract": extract,
        "description": str(data.get("description") or "").strip(),
        "url": str(page_url),
    }


def chunk_text(text: str, *, max_chars: int) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [text]:
        if len(current) + len(paragraph) + 1 <= max_chars:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        current = paragraph[:max_chars]
    if current:
        chunks.append(current)
    return chunks

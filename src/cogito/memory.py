from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from .db import init_db, row_to_dict, rows_to_dicts
from .ids import new_id
from .policy import ContextRequest, memory_allowed


def ensure_db(conn: sqlite3.Connection) -> None:
    init_db(conn)


def add_event(
    conn: sqlite3.Connection,
    *,
    source: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_id = new_id("evt")
    conn.execute(
        """
        INSERT INTO events (id, source, role, content, metadata)
        VALUES (?, ?, ?, ?, ?)
        """,
        (event_id, source, role, content, json.dumps(metadata or {}, sort_keys=True)),
    )
    conn.commit()
    return get_event(conn, event_id)


def get_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise KeyError(f"event not found: {event_id}")
    return row_to_dict(row)


def add_memory(
    conn: sqlite3.Connection,
    *,
    text: str,
    memory_type: str = "fact",
    sensitivity: str = "professional",
    contexts: list[str] | None = None,
    confidence: float = 0.8,
    source_event_id: str | None = None,
    state: str = "active",
) -> dict[str, Any]:
    memory_id = new_id("mem")
    conn.execute(
        """
        INSERT INTO memories
          (id, text, type, sensitivity, contexts, confidence, source_event_id, state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            memory_id,
            text,
            memory_type,
            sensitivity,
            json.dumps(contexts or ["professional"], sort_keys=True),
            confidence,
            source_event_id,
            state,
        ),
    )
    conn.commit()
    return get_memory(conn, memory_id)


def get_memory(conn: sqlite3.Connection, memory_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None:
        raise KeyError(f"memory not found: {memory_id}")
    return row_to_dict(row)


def list_memories(conn: sqlite3.Connection, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM memories"
    params: tuple[Any, ...] = ()
    if not include_deleted:
        sql += " WHERE state != ?"
        params = ("deleted",)
    sql += " ORDER BY created_at DESC"
    return rows_to_dicts(conn.execute(sql, params).fetchall())


def delete_memory(conn: sqlite3.Connection, memory_id: str) -> dict[str, Any]:
    conn.execute(
        "UPDATE memories SET state = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (memory_id,),
    )
    conn.commit()
    return get_memory(conn, memory_id)


def search_memories(
    conn: sqlite3.Connection,
    *,
    query: str,
    request: ContextRequest,
    limit: int = 8,
) -> list[dict[str, Any]]:
    memories = list_memories(conn)
    filtered = [memory for memory in memories if memory_allowed(memory, request)]
    scored = [(score_memory(query, memory), memory) for memory in filtered]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory | {"score": score} for score, memory in scored[:limit] if score > 0]


def score_memory(query: str, memory: dict[str, Any]) -> float:
    query_tokens = tokenize(query)
    text_tokens = tokenize(memory["text"])
    if not query_tokens:
        return 1.0
    overlap = sum((query_tokens & text_tokens).values())
    semantic_hint = 0.1 if any(ctx in query.lower() for ctx in memory.get("contexts", [])) else 0.0
    return overlap + semantic_hint + float(memory.get("confidence", 0.0)) * 0.2


def tokenize(value: str) -> Counter[str]:
    words = [part.strip(".,:;!?()[]{}\"'").lower() for part in value.split()]
    return Counter(word for word in words if len(word) > 2)


def create_receipt(
    conn: sqlite3.Connection,
    *,
    action: str,
    request: ContextRequest,
    memory_ids: list[str],
    decision: str,
    reason: str,
) -> dict[str, Any]:
    receipt_id = new_id("rcpt")
    conn.execute(
        """
        INSERT INTO receipts (id, action, agent, purpose, lens, memory_ids, decision, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            receipt_id,
            action,
            request.agent,
            request.purpose,
            request.lens,
            json.dumps(memory_ids, sort_keys=True),
            decision,
            reason,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    return row_to_dict(row)


def context_pack(
    conn: sqlite3.Connection,
    *,
    query: str,
    request: ContextRequest,
    limit: int = 8,
) -> dict[str, Any]:
    memories = search_memories(conn, query=query, request=request, limit=limit)
    memory_ids = [memory["id"] for memory in memories]
    receipt = create_receipt(
        conn,
        action="context_pack",
        request=request,
        memory_ids=memory_ids,
        decision="allowed",
        reason=f"{request.lens} lens with max sensitivity {request.max_sensitivity}",
    )
    lines = [
        f"Lens: {request.lens}",
        f"Purpose: {request.purpose}",
        "Relevant user context:",
    ]
    if memories:
        lines.extend(f"- {memory['text']}" for memory in memories)
    else:
        lines.append("- No relevant permitted memory found.")
    lines.extend(
        [
            "",
            "Access policy:",
            f"- Max sensitivity: {request.max_sensitivity}",
            "- Secrets and disallowed lenses are not included.",
        ]
    )
    return {"context": "\n".join(lines), "memories": memories, "receipt": receipt}


def explain_memory(conn: sqlite3.Connection, memory_id: str) -> dict[str, Any]:
    memory = get_memory(conn, memory_id)
    source_event = None
    if memory.get("source_event_id"):
        source_event = get_event(conn, memory["source_event_id"])
    receipts = rows_to_dicts(
        conn.execute(
            "SELECT * FROM receipts WHERE memory_ids LIKE ? ORDER BY created_at DESC",
            (f"%{memory_id}%",),
        ).fetchall()
    )
    return {"memory": memory, "source_event": source_event, "receipts": receipts}


from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any

from .agent_bridge import build_enriched_prompt, run_agent_capture
from .db import connect, row_to_dict, rows_to_dicts
from .ids import new_id
from .local_extractor import extract_with_model
from .memory import add_event, add_memory, context_pack
from .embeddings import ensure_memory_embedding
from .policy import ContextRequest
from .settings import get_memory_model


SUPPORTED_AGENTS = ["codex", "codex-exec", "claude", "opencode"]


def create_session(
    conn: sqlite3.Connection,
    *,
    title: str,
    agent: str = "codex",
    lens: str = "coding",
    max_sensitivity: str = "professional",
    cwd: str | None = None,
) -> dict[str, Any]:
    validate_agent(agent)
    session_id = new_id("ses")
    conn.execute(
        """
        INSERT INTO sessions (id, title, cwd, active_agent, lens, max_sensitivity)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, title, cwd or os.getcwd(), agent, lens, max_sensitivity),
    )
    conn.commit()
    return get_session(conn, session_id)


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise KeyError(f"session not found: {session_id}")
    return row_to_dict(row)


def list_sessions(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    return rows_to_dicts(
        conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    )


def set_session_agent(conn: sqlite3.Connection, *, session_id: str, agent: str) -> dict[str, Any]:
    validate_agent(agent)
    conn.execute(
        "UPDATE sessions SET active_agent = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (agent, session_id),
    )
    conn.commit()
    return get_session(conn, session_id)


def add_turn(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    agent: str,
    role: str,
    content: str,
    prompt: str = "",
    exit_code: int | None = None,
) -> dict[str, Any]:
    turn_id = new_id("turn")
    conn.execute(
        """
        INSERT INTO session_turns (id, session_id, agent, role, content, prompt, exit_code)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (turn_id, session_id, agent, role, content, prompt, exit_code),
    )
    conn.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
    conn.commit()
    return get_turn(conn, turn_id)


def get_turn(conn: sqlite3.Connection, turn_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM session_turns WHERE id = ?", (turn_id,)).fetchone()
    if row is None:
        raise KeyError(f"turn not found: {turn_id}")
    return row_to_dict(row)


def get_turns(conn: sqlite3.Connection, *, session_id: str, limit: int = 12) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM session_turns
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    return list(reversed(rows_to_dicts(rows)))


def ask_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    user_prompt: str,
    agent: str | None = None,
    limit: int = 8,
    execute: bool = True,
    auto_memory: bool = True,
    memory_mode: str = "sync",
    stream: bool = True,
    yolo: bool = False,
    model: str | None = None,
    persona: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = get_session(conn, session_id)
    selected_agent = agent or session["active_agent"]
    validate_agent(selected_agent)
    if selected_agent != session["active_agent"]:
        session = set_session_agent(conn, session_id=session_id, agent=selected_agent)
    request = ContextRequest(
        lens=session["lens"],
        max_sensitivity=session["max_sensitivity"],
        agent=selected_agent,
        purpose="session_context",
    )
    event = add_event(
        conn,
        source=f"session:{session_id}",
        role="user",
        content=user_prompt,
        metadata={"agent": selected_agent},
    )
    add_turn(conn, session_id=session_id, agent=selected_agent, role="user", content=user_prompt)
    pack = context_pack(conn, query=user_prompt, request=request, limit=limit)
    prompt = build_session_prompt(
        session=session,
        turns=get_turns(conn, session_id=session_id),
        context=pack["context"],
        user_prompt=user_prompt,
        persona=persona,
    )
    stored_memories: list[dict[str, Any]] = []
    if auto_memory:
        if memory_mode == "background":
            start_background_memory_extraction(conn, event_id=event["id"], text=user_prompt)
        elif memory_mode == "sync":
            stored_memories = extract_and_store_memories(conn, event_id=event["id"], text=user_prompt)
        elif memory_mode != "off":
            raise ValueError(f"unsupported memory mode: {memory_mode}")
    exit_code = None
    output = ""
    if execute:
        result = run_agent_capture(selected_agent, prompt, stream=stream, yolo=yolo, model=model)
        exit_code = int(result["exit_code"])
        output = str(result["output"])
        if output and not stream:
            print(output)
        add_turn(
            conn,
            session_id=session_id,
            agent=selected_agent,
            role="agent",
            content=output or f"Agent process exited with code {exit_code}.",
            prompt=prompt,
            exit_code=exit_code,
        )
    return {
        "session": get_session(conn, session_id),
        "agent": selected_agent,
        "prompt": prompt,
        "context_pack": pack,
        "stored_memories": stored_memories,
        "exit_code": exit_code,
        "output": output,
    }


def build_session_prompt(
    *,
    session: dict[str, Any],
    turns: list[dict[str, Any]],
    context: str,
    user_prompt: str,
    persona: dict[str, Any] | None = None,
) -> str:
    recent = "\n".join(
        f"- {turn['role']} via {turn['agent']}: {compact(turn['content'], 240)}"
        for turn in turns[-8:]
        if turn["content"] != user_prompt or turn["role"] != "user"
    )
    session_block = [
        f"Cogito session: {session['id']}",
        f"Session title: {session['title']}",
    ]
    if session.get("summary"):
        session_block.append(f"Session summary: {session['summary']}")
    if recent:
        session_block.extend(["Recent session turns:", recent])
    if persona:
        session_block.extend(
            [
                "",
                f"Active persona: {persona['name']}",
                f"Persona tool: {persona['agent']}",
                f"Persona model: {persona.get('model') or 'default'}",
                "Persona instructions:",
                persona["description"],
            ]
        )
    session_context = "\n".join(session_block)
    return build_enriched_prompt(f"{session_context}\n\n{context}", user_prompt)


def compact(value: str, max_chars: int) -> str:
    one_line = " ".join(value.split())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[: max_chars - 3] + "..."


def validate_agent(agent: str) -> None:
    if agent not in SUPPORTED_AGENTS:
        raise ValueError(f"unsupported agent: {agent}")


def extract_and_store_memories(conn: sqlite3.Connection, *, event_id: str, text: str) -> list[dict[str, Any]]:
    memories = []
    candidates, source = extract_with_model(text, get_memory_model(conn))
    for candidate in candidates:
        if memory_text_exists(conn, candidate["text"]):
            continue
        memory = add_memory(
            conn,
            text=candidate["text"],
            memory_type=candidate["type"],
            sensitivity=candidate["sensitivity"],
            contexts=candidate["contexts"],
            confidence=candidate["confidence"],
            source_event_id=event_id,
        )
        try:
            memory = ensure_memory_embedding(conn, memory)
        except Exception:
            pass
        memories.append(memory)
    if memories:
        for memory in memories:
            memory["extractor"] = source
    return memories


def memory_text_exists(conn: sqlite3.Connection, text: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM memories WHERE text = ? AND state != 'deleted' LIMIT 1",
        (text,),
    ).fetchone()
    return row is not None


def start_background_memory_extraction(conn: sqlite3.Connection, *, event_id: str, text: str) -> None:
    job = enqueue_memory_job(conn, event_id=event_id, text=text)
    db_path = current_db_path(conn)
    if not db_path:
        return
    thread = threading.Thread(
        target=background_memory_worker,
        kwargs={"db_path": db_path, "job_id": job["id"]},
        daemon=True,
    )
    thread.start()


def background_memory_worker(*, db_path: str, job_id: str | None = None) -> None:
    try:
        bg_conn = connect(db_path)
        if job_id:
            process_memory_job(bg_conn, job_id=job_id)
        process_pending_memory_jobs(bg_conn, limit=3)
    except Exception:
        return


def current_db_path(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None:
        return None
    path = row["file"] if isinstance(row, sqlite3.Row) else row[2]
    return str(path) if path else None


def enqueue_memory_job(conn: sqlite3.Connection, *, event_id: str, text: str) -> dict[str, Any]:
    job_id = new_id("mjob")
    conn.execute(
        """
        INSERT INTO memory_jobs (id, event_id, content)
        VALUES (?, ?, ?)
        """,
        (job_id, event_id, text),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM memory_jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_dict(row)


def process_memory_job(conn: sqlite3.Connection, *, job_id: str) -> None:
    row = conn.execute("SELECT * FROM memory_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return
    job = row_to_dict(row)
    if job["state"] == "done":
        return
    try:
        conn.execute(
            "UPDATE memory_jobs SET state = 'processing', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (job_id,),
        )
        conn.commit()
        extract_and_store_memories(conn, event_id=job["event_id"], text=job["content"])
        conn.execute(
            "UPDATE memory_jobs SET state = 'done', error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (job_id,),
        )
        conn.commit()
    except Exception as exc:
        conn.execute(
            "UPDATE memory_jobs SET state = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (str(exc), job_id),
        )
        conn.commit()


def process_pending_memory_jobs(conn: sqlite3.Connection, *, limit: int = 5) -> None:
    rows = conn.execute(
        """
        SELECT id FROM memory_jobs
        WHERE state IN ('pending', 'failed')
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for row in rows:
        process_memory_job(conn, job_id=row["id"])

from __future__ import annotations

import os
import sqlite3
from typing import Any

from .agent_bridge import build_enriched_prompt, run_agent_capture
from .db import row_to_dict, rows_to_dicts
from .extraction import extract_candidate_memories
from .ids import new_id
from .memory import add_event, add_memory, context_pack
from .policy import ContextRequest


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
    stream: bool = True,
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
    stored_memories = extract_and_store_memories(conn, event_id=event["id"], text=user_prompt) if auto_memory else []
    add_turn(conn, session_id=session_id, agent=selected_agent, role="user", content=user_prompt)
    pack = context_pack(conn, query=user_prompt, request=request, limit=limit)
    prompt = build_session_prompt(session=session, turns=get_turns(conn, session_id=session_id), context=pack["context"], user_prompt=user_prompt)
    exit_code = None
    output = ""
    if execute:
        result = run_agent_capture(selected_agent, prompt, stream=stream)
        exit_code = int(result["exit_code"])
        output = str(result["output"])
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
    for candidate in extract_candidate_memories(text):
        if memory_text_exists(conn, candidate["text"]):
            continue
        memories.append(
            add_memory(
                conn,
                text=candidate["text"],
                memory_type=candidate["type"],
                sensitivity=candidate["sensitivity"],
                contexts=candidate["contexts"],
                confidence=candidate["confidence"],
                source_event_id=event_id,
            )
        )
    return memories


def memory_text_exists(conn: sqlite3.Connection, text: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM memories WHERE text = ? AND state != 'deleted' LIMIT 1",
        (text,),
    ).fetchone()
    return row is not None

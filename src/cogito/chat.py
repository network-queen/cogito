from __future__ import annotations

import sqlite3
import sys
from typing import TextIO

from .memory import list_memories
from .settings import get_memory_model, set_memory_model
from .sessions import ask_session, create_session, get_session, process_pending_memory_jobs, set_session_agent


def run_chat(
    conn: sqlite3.Connection,
    *,
    agent: str = "codex",
    session_id: str | None = None,
    title: str = "Cogito chat",
    lens: str = "coding",
    max_sensitivity: str = "professional",
    execute: bool = True,
    memory_mode: str = "background",
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    session = (
        get_session(conn, session_id)
        if session_id
        else create_session(conn, title=title, agent=agent, lens=lens, max_sensitivity=max_sensitivity)
    )
    process_pending_memory_jobs(conn, limit=3)
    write(output_stream, f"Cogito chat. Session: {session['id']}. Tool: {session['active_agent']}.")
    write(output_stream, "Commands: /tool codex|claude|opencode, /memory-model [model], /memories, /session, /help, /exit")

    while True:
        try:
            if input_stream is sys.stdin:
                line = input(f"cogito[{session['active_agent']}]> ")
            else:
                line = input_stream.readline()
                if line == "":
                    break
                line = line.rstrip("\n")
        except (EOFError, KeyboardInterrupt):
            write(output_stream, "")
            break

        text = line.strip()
        if not text:
            continue
        if text.startswith("/"):
            should_continue, session = handle_command(conn, text, session=session, output_stream=output_stream)
            if not should_continue:
                break
            continue

        result = ask_session(
            conn,
            session_id=session["id"],
            user_prompt=text,
            execute=execute,
            memory_mode=memory_mode,
            stream=execute,
        )
        session = result["session"]
        if not execute:
            write(output_stream, result["prompt"])

    write(output_stream, "Cogito session closed.")
    return 0


def handle_command(
    conn: sqlite3.Connection,
    command: str,
    *,
    session: dict,
    output_stream: TextIO,
) -> tuple[bool, dict]:
    parts = command.split()
    name = parts[0]
    if name in {"/exit", "/quit", "/q"}:
        return False, session
    if name == "/help":
        write(output_stream, "Commands: /tool AGENT, /memory-model [MODEL], /memories, /session, /exit")
        return True, session
    if name == "/session":
        write(output_stream, format_session(session))
        return True, session
    if name == "/memories":
        memories = list_memories(conn)[:10]
        if not memories:
            write(output_stream, "No memories stored.")
        else:
            for memory in memories:
                write(output_stream, f"- {memory['text']} [{memory['type']}, {memory['sensitivity']}]")
        return True, session
    if name == "/tool":
        if len(parts) != 2:
            write(output_stream, "Usage: /tool codex|claude|opencode")
            return True, session
        updated = set_session_agent(conn, session_id=session["id"], agent=parts[1])
        write(output_stream, f"Tool: {updated['active_agent']}")
        return True, updated
    if name == "/memory-model":
        if len(parts) == 1:
            write(output_stream, f"Memory model: {get_memory_model(conn)}")
            return True, session
        model = set_memory_model(conn, " ".join(parts[1:]))
        write(output_stream, f"Memory model: {model}")
        return True, session
    write(output_stream, f"Unknown command: {name}. Use /help.")
    return True, session


def format_session(session: dict) -> str:
    return (
        f"Session: {session['id']}\n"
        f"Title: {session['title']}\n"
        f"Tool: {session['active_agent']}\n"
        f"Lens: {session['lens']}\n"
        f"Max sensitivity: {session['max_sensitivity']}"
    )


def write(stream: TextIO, text: str) -> None:
    stream.write(text + "\n")
    stream.flush()

from __future__ import annotations

import sqlite3
import sys
from typing import TextIO

from .memory import list_memories
from .personas import add_persona, delete_persona, get_persona, list_personas, maybe_extract_persona_call
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
    yolo: bool = False,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    session = (
        get_session(conn, session_id)
        if session_id
        else create_session(conn, title=title, agent=agent, lens=lens, max_sensitivity=max_sensitivity)
    )
    process_pending_memory_jobs(conn, limit=3)
    active_persona: dict | None = None
    write(output_stream, f"Cogito chat. Session: {session['id']}. Tool: {session['active_agent']}.")
    write(output_stream, "Commands: /tool, /persona, /memory-model, /memories, /session, /help, /exit")

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
            should_continue, session, active_persona = handle_command(
                conn,
                text,
                session=session,
                active_persona=active_persona,
                output_stream=output_stream,
            )
            if not should_continue:
                break
            continue
        called_persona, routed_text = maybe_extract_persona_call(conn, text)
        turn_persona = called_persona or active_persona
        turn_agent = turn_persona["agent"] if turn_persona else session["active_agent"]
        turn_model = turn_persona.get("model") if turn_persona else None
        turn_yolo = yolo or bool(turn_persona.get("yolo")) if turn_persona else yolo

        result = ask_session(
            conn,
            session_id=session["id"],
            user_prompt=routed_text,
            agent=turn_agent,
            execute=execute,
            memory_mode=memory_mode,
            stream=execute,
            yolo=turn_yolo,
            model=turn_model,
            persona=turn_persona,
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
    active_persona: dict | None,
    output_stream: TextIO,
) -> tuple[bool, dict, dict | None]:
    parts = command.split()
    name = parts[0]
    if name in {"/exit", "/quit", "/q"}:
        return False, session, active_persona
    if name == "/help":
        write(output_stream, "Commands: /tool AGENT, /persona add|use|list|show|delete|clear, /memory-model [MODEL], /memories, /session, /exit")
        write(output_stream, "Persona call: @name your request")
        return True, session, active_persona
    if name == "/session":
        write(output_stream, format_session(session))
        return True, session, active_persona
    if name == "/memories":
        memories = list_memories(conn)[:10]
        if not memories:
            write(output_stream, "No memories stored.")
        else:
            for memory in memories:
                write(output_stream, f"- {memory['text']} [{memory['type']}, {memory['sensitivity']}]")
        return True, session, active_persona
    if name == "/tool":
        if len(parts) != 2:
            write(output_stream, "Usage: /tool codex|claude|opencode")
            return True, session, active_persona
        updated = set_session_agent(conn, session_id=session["id"], agent=parts[1])
        write(output_stream, f"Tool: {updated['active_agent']}")
        return True, updated, active_persona
    if name == "/persona":
        return handle_persona_command(conn, parts, session=session, active_persona=active_persona, output_stream=output_stream)
    if name == "/memory-model":
        if len(parts) == 1:
            write(output_stream, f"Memory model: {get_memory_model(conn)}")
            return True, session, active_persona
        model = set_memory_model(conn, " ".join(parts[1:]))
        write(output_stream, f"Memory model: {model}")
        return True, session, active_persona
    write(output_stream, f"Unknown command: {name}. Use /help.")
    return True, session, active_persona


def handle_persona_command(
    conn: sqlite3.Connection,
    parts: list[str],
    *,
    session: dict,
    active_persona: dict | None,
    output_stream: TextIO,
) -> tuple[bool, dict, dict | None]:
    if len(parts) == 1 or parts[1] == "list":
        personas = list_personas(conn)
        if not personas:
            write(output_stream, "No personas.")
        for persona in personas:
            model = persona.get("model") or "default"
            write(output_stream, f"- {persona['name']}: {persona['agent']} {model}")
        return True, session, active_persona
    action = parts[1]
    if action == "add":
        if len(parts) < 6:
            write(output_stream, "Usage: /persona add NAME AGENT MODEL DESCRIPTION")
            return True, session, active_persona
        name, agent, model = parts[2], parts[3], parts[4]
        description = " ".join(parts[5:])
        persona = add_persona(conn, name=name, agent=agent, model=None if model == "-" else model, description=description)
        write(output_stream, f"Persona saved: {persona['name']}")
        return True, session, active_persona
    if action == "use":
        if len(parts) != 3:
            write(output_stream, "Usage: /persona use NAME")
            return True, session, active_persona
        persona = get_persona(conn, parts[2])
        updated = set_session_agent(conn, session_id=session["id"], agent=persona["agent"])
        write(output_stream, f"Persona: {persona['name']} ({persona['agent']})")
        return True, updated, persona
    if action == "show":
        if len(parts) != 3:
            write(output_stream, "Usage: /persona show NAME")
            return True, session, active_persona
        write(output_stream, format_persona(get_persona(conn, parts[2])))
        return True, session, active_persona
    if action in {"delete", "del", "rm"}:
        if len(parts) != 3:
            write(output_stream, "Usage: /persona delete NAME")
            return True, session, active_persona
        delete_persona(conn, parts[2])
        write(output_stream, f"Persona deleted: {parts[2]}")
        return True, session, None if active_persona and active_persona["name"] == parts[2] else active_persona
    if action == "clear":
        write(output_stream, "Persona cleared.")
        return True, session, None
    write(output_stream, "Usage: /persona add|use|list|show|delete|clear")
    return True, session, active_persona


def format_session(session: dict) -> str:
    return (
        f"Session: {session['id']}\n"
        f"Title: {session['title']}\n"
        f"Tool: {session['active_agent']}\n"
        f"Lens: {session['lens']}\n"
        f"Max sensitivity: {session['max_sensitivity']}"
    )


def format_persona(persona: dict) -> str:
    return (
        f"Persona: {persona['name']}\n"
        f"Tool: {persona['agent']}\n"
        f"Model: {persona.get('model') or 'default'}\n"
        f"Yolo: {persona['yolo']}\n"
        f"{persona['description']}"
    )


def write(stream: TextIO, text: str) -> None:
    stream.write(text + "\n")
    stream.flush()

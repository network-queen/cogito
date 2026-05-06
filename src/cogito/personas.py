from __future__ import annotations

import sqlite3
from typing import Any

from .db import row_to_dict, rows_to_dicts
from .ids import new_id
from .tool_manager import infer_agent_for_model


SUPPORTED_PERSONA_AGENTS = {"local", "codex", "codex-exec", "claude", "opencode"}


def add_persona(
    conn: sqlite3.Connection,
    *,
    name: str,
    agent: str,
    description: str,
    model: str | None = None,
    yolo: bool = False,
) -> dict[str, Any]:
    validate_persona_name(name)
    if agent not in SUPPORTED_PERSONA_AGENTS:
        raise ValueError(f"unsupported persona agent: {agent}")
    persona_id = new_id("per")
    conn.execute(
        """
        INSERT INTO personas (id, name, agent, model, description, yolo)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
          agent = excluded.agent,
          model = excluded.model,
          description = excluded.description,
          yolo = excluded.yolo,
          updated_at = CURRENT_TIMESTAMP
        """,
        (persona_id, name, agent, model, description, int(yolo)),
    )
    conn.commit()
    return get_persona(conn, name)


def add_persona_for_model(
    conn: sqlite3.Connection,
    *,
    name: str,
    model: str,
    description: str,
    yolo: bool = False,
) -> dict[str, Any]:
    return add_persona(
        conn,
        name=name,
        agent=infer_agent_for_model(None if model == "-" else model),
        model=None if model == "-" else model,
        description=description,
        yolo=yolo,
    )


def get_persona(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM personas WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise KeyError(f"persona not found: {name}")
    return normalize_persona(row_to_dict(row))


def get_self_persona() -> dict[str, Any]:
    return {
        "id": "__self__",
        "name": "me",
        "agent": "local",
        "model": None,
        "description": (
            "Act as the user's self-persona. Use only the permitted Cogito user context "
            "provided for this turn; do not invent biographical facts."
        ),
        "yolo": False,
        "virtual": True,
    }


def list_personas(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM personas ORDER BY name ASC").fetchall()
    return [normalize_persona(item) for item in rows_to_dicts(rows)]


def delete_persona(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM personas WHERE name = ?", (name,))
    conn.commit()


def maybe_extract_persona_call(conn: sqlite3.Connection, text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = text.strip()
    if not stripped.startswith("@"):
        return None, text
    head, _, rest = stripped.partition(" ")
    name = head.removeprefix("@")
    if not name:
        return None, text
    if name == "me":
        return get_self_persona(), rest.strip() or text
    try:
        return get_persona(conn, name), rest.strip() or text
    except KeyError:
        return None, text


def normalize_persona(persona: dict[str, Any]) -> dict[str, Any]:
    return persona | {"yolo": bool(persona.get("yolo"))}


def validate_persona_name(name: str) -> None:
    cleaned = name.replace("-", "").replace("_", "")
    if not cleaned or not cleaned.isalnum():
        raise ValueError("persona name must contain only letters, numbers, '-' or '_'")

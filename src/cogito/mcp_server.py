from __future__ import annotations

import json
import sqlite3
from typing import Any, TextIO

from .memory import add_memory, context_pack, delete_memory, explain_memory, search_memories
from .policy import ContextRequest


TOOLS = [
    {
        "name": "store_memory",
        "description": "Store a user memory with type, sensitivity, and context labels.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "type": {"type": "string", "default": "fact"},
                "sensitivity": {"type": "string", "default": "professional"},
                "contexts": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number", "default": 0.8},
            },
            "required": ["text"],
        },
    },
    {
        "name": "search_memory",
        "description": "Search user memories permitted by lens and sensitivity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "lens": {"type": "string", "default": "coding"},
                "max_sensitivity": {"type": "string", "default": "professional"},
                "agent": {"type": "string", "default": "mcp"},
                "purpose": {"type": "string", "default": "context_retrieval"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_context_pack",
        "description": "Return a compact policy-filtered user context pack.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "lens": {"type": "string", "default": "coding"},
                "max_sensitivity": {"type": "string", "default": "professional"},
                "agent": {"type": "string", "default": "mcp"},
                "purpose": {"type": "string", "default": "context_retrieval"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "explain_memory",
        "description": "Show provenance and access receipts for one memory.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "delete_memory",
        "description": "Mark a memory deleted.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
]


def run_mcp_server(conn: sqlite3.Connection, stdin: TextIO, stdout: TextIO) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle_request(conn, request)
        except Exception as exc:  # Keep server alive for malformed client calls.
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(exc)},
            }
        if response is not None:
            stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            stdout.flush()


def handle_request(conn: sqlite3.Connection, request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return result(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", "2025-03-26"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "cogito", "version": "0.1.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        return result(request_id, call_tool(conn, name, args))
    return error(request_id, -32601, f"method not found: {method}")


def call_tool(conn: sqlite3.Connection, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "store_memory":
        payload = add_memory(
            conn,
            text=args["text"],
            memory_type=args.get("type", "fact"),
            sensitivity=args.get("sensitivity", "professional"),
            contexts=args.get("contexts") or ["professional"],
            confidence=float(args.get("confidence", 0.8)),
        )
    elif name == "search_memory":
        payload = search_memories(
            conn,
            query=args["query"],
            request=context_request(args),
            limit=int(args.get("limit", 8)),
        )
    elif name == "get_context_pack":
        payload = context_pack(
            conn,
            query=args["query"],
            request=context_request(args),
            limit=int(args.get("limit", 8)),
        )
    elif name == "explain_memory":
        payload = explain_memory(conn, args["memory_id"])
    elif name == "delete_memory":
        payload = delete_memory(conn, args["memory_id"])
    else:
        raise ValueError(f"unknown tool: {name}")
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}]}


def context_request(args: dict[str, Any]) -> ContextRequest:
    return ContextRequest(
        lens=args.get("lens", "coding"),
        max_sensitivity=args.get("max_sensitivity", "professional"),
        agent=args.get("agent", "mcp"),
        purpose=args.get("purpose", "context_retrieval"),
    )


def result(request_id: Any, payload: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


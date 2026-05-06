from __future__ import annotations

import argparse
import json
import sys

from .db import connect, default_db_path
from .extraction import extract_candidate_memories
from .mcp_server import run_mcp_server
from .memory import (
    add_event,
    add_memory,
    context_pack,
    delete_memory,
    ensure_db,
    explain_memory,
    list_memories,
    search_memories,
)
from .policy import ContextRequest


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = connect(args.db)
    ensure_db(conn)
    return args.func(conn, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cogito")
    parser.add_argument("--db", help="SQLite DB path. Defaults to COGITO_DB or ~/.local/share/cogito/cogito.db")
    sub = parser.add_subparsers(required=True)

    init_cmd = sub.add_parser("init", help="Initialize local vault")
    init_cmd.set_defaults(func=cmd_init)

    remember = sub.add_parser("remember", help="Store one memory")
    remember.add_argument("text")
    remember.add_argument("--type", default="fact")
    remember.add_argument("--sensitivity", default="professional")
    remember.add_argument("--contexts", default="professional")
    remember.add_argument("--confidence", type=float, default=0.8)
    remember.set_defaults(func=cmd_remember)

    ingest = sub.add_parser("ingest", help="Store event and optionally extract candidate memories")
    ingest.add_argument("text", nargs="?", help="Text to ingest. Reads stdin when omitted.")
    ingest.add_argument("--source", default="manual")
    ingest.add_argument("--role", default="user")
    ingest.add_argument("--extract", action="store_true")
    ingest.add_argument("--auto-accept", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    list_cmd = sub.add_parser("list", help="List memories")
    list_cmd.add_argument("--include-deleted", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    search = sub.add_parser("search", help="Search permitted memories")
    search.add_argument("query")
    add_policy_args(search)
    search.add_argument("--limit", type=int, default=8)
    search.set_defaults(func=cmd_search)

    pack = sub.add_parser("context-pack", help="Build policy-filtered context pack")
    pack.add_argument("query")
    add_policy_args(pack)
    pack.add_argument("--limit", type=int, default=8)
    pack.add_argument("--json", action="store_true")
    pack.set_defaults(func=cmd_context_pack)

    explain = sub.add_parser("explain", help="Show provenance and receipts for memory")
    explain.add_argument("memory_id")
    explain.set_defaults(func=cmd_explain)

    forget = sub.add_parser("forget", help="Mark memory deleted")
    forget.add_argument("memory_id")
    forget.set_defaults(func=cmd_forget)

    mcp = sub.add_parser("mcp", help="Run MCP-compatible stdio server")
    mcp.set_defaults(func=cmd_mcp)

    return parser


def add_policy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lens", default="coding")
    parser.add_argument("--max-sensitivity", default="professional")
    parser.add_argument("--agent", default="local")
    parser.add_argument("--purpose", default="context_retrieval")


def request_from_args(args: argparse.Namespace) -> ContextRequest:
    return ContextRequest(
        lens=args.lens,
        max_sensitivity=args.max_sensitivity,
        agent=args.agent,
        purpose=args.purpose,
    )


def cmd_init(conn, args: argparse.Namespace) -> int:
    print(f"Initialized Cogito vault: {args.db or default_db_path()}")
    return 0


def cmd_remember(conn, args: argparse.Namespace) -> int:
    memory = add_memory(
        conn,
        text=args.text,
        memory_type=args.type,
        sensitivity=args.sensitivity,
        contexts=split_csv(args.contexts),
        confidence=args.confidence,
    )
    print(json.dumps(memory, indent=2, sort_keys=True))
    return 0


def cmd_ingest(conn, args: argparse.Namespace) -> int:
    text = args.text if args.text is not None else sys.stdin.read()
    event = add_event(conn, source=args.source, role=args.role, content=text)
    result = {"event": event, "candidates": []}
    if args.extract:
        candidates = extract_candidate_memories(text)
        result["candidates"] = candidates
        if args.auto_accept:
            result["memories"] = [
                add_memory(
                    conn,
                    text=candidate["text"],
                    memory_type=candidate["type"],
                    sensitivity=candidate["sensitivity"],
                    contexts=candidate["contexts"],
                    confidence=candidate["confidence"],
                    source_event_id=event["id"],
                )
                for candidate in candidates
            ]
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_list(conn, args: argparse.Namespace) -> int:
    print(json.dumps(list_memories(conn, include_deleted=args.include_deleted), indent=2, sort_keys=True))
    return 0


def cmd_search(conn, args: argparse.Namespace) -> int:
    memories = search_memories(conn, query=args.query, request=request_from_args(args), limit=args.limit)
    print(json.dumps(memories, indent=2, sort_keys=True))
    return 0


def cmd_context_pack(conn, args: argparse.Namespace) -> int:
    pack = context_pack(conn, query=args.query, request=request_from_args(args), limit=args.limit)
    if args.json:
        print(json.dumps(pack, indent=2, sort_keys=True))
    else:
        print(pack["context"])
    return 0


def cmd_explain(conn, args: argparse.Namespace) -> int:
    print(json.dumps(explain_memory(conn, args.memory_id), indent=2, sort_keys=True))
    return 0


def cmd_forget(conn, args: argparse.Namespace) -> int:
    print(json.dumps(delete_memory(conn, args.memory_id), indent=2, sort_keys=True))
    return 0


def cmd_mcp(conn, args: argparse.Namespace) -> int:
    run_mcp_server(conn, sys.stdin, sys.stdout)
    return 0


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


if __name__ == "__main__":
    raise SystemExit(main())

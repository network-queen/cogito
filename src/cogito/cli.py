from __future__ import annotations

import argparse
import json
import sys

from .agent_bridge import get_prompt, run_agent, setup_agent
from .chat import run_chat
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
from .settings import (
    get_chat_model,
    get_embedding_model,
    get_memory_model,
    set_chat_model,
    set_embedding_model,
    set_memory_model,
)
from .sessions import SUPPORTED_AGENTS, ask_session, create_session, list_sessions, set_session_agent, set_session_model
from .tool_manager import install_for_model, model_catalog, update_for_model


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["chat"]
    elif argv[0] in {"--yolo", "--verbose", "--print-prompt", "--memory-mode"}:
        argv = ["chat", *argv]
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

    prompt = sub.add_parser("prompt", help="Print an agent prompt enriched with permitted Cogito context")
    prompt.add_argument("query")
    add_policy_args(prompt)
    prompt.add_argument("--limit", type=int, default=8)
    prompt.set_defaults(func=cmd_prompt)

    ask = sub.add_parser("ask", help="Run an agent with Cogito context prepended to your prompt")
    ask.add_argument("agent", choices=SUPPORTED_AGENTS)
    ask.add_argument("query")
    add_policy_args(ask)
    ask.add_argument("--limit", type=int, default=8)
    ask.add_argument("--yolo", action="store_true", help="Bypass underlying agent permission prompts where supported")
    ask.set_defaults(func=cmd_ask)

    run = sub.add_parser("run", help="Start or continue a Cogito-owned session with selected agent")
    run.add_argument("agent", choices=SUPPORTED_AGENTS)
    run.add_argument("query")
    run.add_argument("--session", help="Existing session id. Creates a session when omitted.")
    run.add_argument("--title", help="Title for new session")
    run.add_argument("--lens", default="coding")
    run.add_argument("--max-sensitivity", default="professional")
    run.add_argument("--limit", type=int, default=8)
    run.add_argument("--print-prompt", action="store_true", help="Print enriched prompt instead of executing agent")
    run.add_argument("--yolo", action="store_true", help="Bypass underlying agent permission prompts where supported")
    run.set_defaults(func=cmd_run)

    chat = sub.add_parser("chat", help="Enter a Cogito terminal chat that routes turns to selected agent")
    chat.add_argument("--agent", default="local", choices=SUPPORTED_AGENTS)
    chat.add_argument("--model", help="Active model. Cogito infers the adapter from this.")
    chat.add_argument("--session", help="Existing session id")
    chat.add_argument("--title", default="Cogito chat")
    chat.add_argument("--lens", default="coding")
    chat.add_argument("--max-sensitivity", default="professional")
    chat.add_argument("--print-prompt", action="store_true", help="Print enriched prompts instead of executing agents")
    chat.add_argument("--memory-mode", choices=["background", "sync", "off"], default="background")
    chat.add_argument("--yolo", action="store_true", help="Bypass underlying agent permission prompts where supported")
    chat.add_argument("--verbose", action="store_true", help="Show Cogito metadata and command confirmations")
    chat.set_defaults(func=cmd_chat)

    models = sub.add_parser("models", help="List detected models from installed adapters")
    models.set_defaults(func=cmd_models)

    install = sub.add_parser("install", help="Install the adapter needed for MODEL")
    install.add_argument("model")
    install.set_defaults(func=cmd_install)

    update = sub.add_parser("update", help="Update the adapter needed for MODEL")
    update.add_argument("model")
    update.set_defaults(func=cmd_update)

    chat_model = sub.add_parser("chat-model", help="Show or change local model used for default chat")
    chat_model.add_argument("model", nargs="?", help="Example: qwen3:0.6b or ollama:llama3.2")
    chat_model.set_defaults(func=cmd_chat_model)

    memory_model = sub.add_parser("memory-model", help="Show or change local model used for memory extraction")
    memory_model.add_argument("model", nargs="?", help="Example: qwen3:0.6b or ollama:qwen3:1.7b")
    memory_model.set_defaults(func=cmd_memory_model)

    embedding_model = sub.add_parser("embedding-model", help="Show or change local model used for memory relevance")
    embedding_model.add_argument("model", nargs="?", help="Example: nomic-embed-text or ollama:mxbai-embed-large")
    embedding_model.set_defaults(func=cmd_embedding_model)

    session = sub.add_parser("session", help="Manage Cogito sessions")
    session_sub = session.add_subparsers(required=True)
    session_new = session_sub.add_parser("new", help="Create a session")
    session_new.add_argument("--title", default="Untitled Cogito session")
    session_new.add_argument("--agent", default="local", choices=SUPPORTED_AGENTS)
    session_new.add_argument("--model", help="Active model. Cogito infers the adapter from this.")
    session_new.add_argument("--lens", default="coding")
    session_new.add_argument("--max-sensitivity", default="professional")
    session_new.set_defaults(func=cmd_session_new)
    session_list = session_sub.add_parser("list", help="List sessions")
    session_list.add_argument("--limit", type=int, default=20)
    session_list.set_defaults(func=cmd_session_list)
    session_tool = session_sub.add_parser("tool", help="Change session active agent")
    session_tool.add_argument("session_id")
    session_tool.add_argument("agent", choices=SUPPORTED_AGENTS)
    session_tool.set_defaults(func=cmd_session_tool)
    session_model = session_sub.add_parser("model", help="Change session active model")
    session_model.add_argument("session_id")
    session_model.add_argument("model")
    session_model.set_defaults(func=cmd_session_model)
    session_ask = session_sub.add_parser("ask", help="Ask within existing session")
    session_ask.add_argument("session_id")
    session_ask.add_argument("query")
    session_ask.add_argument("--agent", choices=SUPPORTED_AGENTS)
    session_ask.add_argument("--limit", type=int, default=8)
    session_ask.add_argument("--print-prompt", action="store_true")
    session_ask.set_defaults(func=cmd_session_ask)

    setup = sub.add_parser("setup-agent", help="Register Cogito as an MCP server for an agent")
    setup.add_argument("agent", choices=["codex", "claude", "opencode"])
    setup.add_argument("--cogito-bin", help="Path to cogito executable")
    setup.set_defaults(func=cmd_setup_agent)

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


def cmd_prompt(conn, args: argparse.Namespace) -> int:
    print(get_prompt(conn, user_prompt=args.query, request=request_from_args(args), limit=args.limit))
    return 0


def cmd_ask(conn, args: argparse.Namespace) -> int:
    prompt = get_prompt(conn, user_prompt=args.query, request=request_from_args(args), limit=args.limit)
    return run_agent(args.agent, prompt, yolo=args.yolo)


def cmd_run(conn, args: argparse.Namespace) -> int:
    session = (
        create_session(
            conn,
            title=args.title or args.query[:80],
            agent=args.agent,
            lens=args.lens,
            max_sensitivity=args.max_sensitivity,
        )
        if not args.session
        else set_session_agent(conn, session_id=args.session, agent=args.agent)
    )
    result = ask_session(
        conn,
        session_id=session["id"],
        user_prompt=args.query,
        agent=args.agent,
        limit=args.limit,
        execute=not args.print_prompt,
        yolo=args.yolo,
    )
    if args.print_prompt:
        print(result["prompt"])
    else:
        print(f"Cogito session: {session['id']}")
    return result["exit_code"] or 0


def cmd_chat(conn, args: argparse.Namespace) -> int:
    return run_chat(
        conn,
        agent=args.agent,
        model=args.model,
        session_id=args.session,
        title=args.title,
        lens=args.lens,
        max_sensitivity=args.max_sensitivity,
        execute=not args.print_prompt,
        memory_mode=args.memory_mode,
        yolo=args.yolo,
        verbose=args.verbose,
    )


def cmd_models(conn, args: argparse.Namespace) -> int:
    print(json.dumps(model_catalog(), indent=2, sort_keys=True))
    return 0


def cmd_install(conn, args: argparse.Namespace) -> int:
    return print_command_result(install_for_model(args.model))


def cmd_update(conn, args: argparse.Namespace) -> int:
    return print_command_result(update_for_model(args.model))


def print_command_result(result) -> int:
    print("$ " + " ".join(result.command))
    if result.output:
        print(result.output)
    return int(result.code)


def cmd_chat_model(conn, args: argparse.Namespace) -> int:
    if args.model:
        print(set_chat_model(conn, args.model))
    else:
        print(get_chat_model(conn))
    return 0


def cmd_memory_model(conn, args: argparse.Namespace) -> int:
    if args.model:
        print(set_memory_model(conn, args.model))
    else:
        print(get_memory_model(conn))
    return 0


def cmd_embedding_model(conn, args: argparse.Namespace) -> int:
    if args.model:
        print(set_embedding_model(conn, args.model))
    else:
        print(get_embedding_model(conn))
    return 0


def cmd_session_new(conn, args: argparse.Namespace) -> int:
    print(
        json.dumps(
            create_session(
                conn,
                title=args.title,
                agent=args.agent,
                model=args.model,
                lens=args.lens,
                max_sensitivity=args.max_sensitivity,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_session_list(conn, args: argparse.Namespace) -> int:
    print(json.dumps(list_sessions(conn, limit=args.limit), indent=2, sort_keys=True))
    return 0


def cmd_session_tool(conn, args: argparse.Namespace) -> int:
    print(json.dumps(set_session_agent(conn, session_id=args.session_id, agent=args.agent), indent=2, sort_keys=True))
    return 0


def cmd_session_model(conn, args: argparse.Namespace) -> int:
    print(json.dumps(set_session_model(conn, session_id=args.session_id, model=args.model), indent=2, sort_keys=True))
    return 0


def cmd_session_ask(conn, args: argparse.Namespace) -> int:
    result = ask_session(
        conn,
        session_id=args.session_id,
        user_prompt=args.query,
        agent=args.agent,
        limit=args.limit,
        execute=not args.print_prompt,
        memory_mode="sync",
    )
    if args.print_prompt:
        print(result["prompt"])
    return result["exit_code"] or 0


def cmd_setup_agent(conn, args: argparse.Namespace) -> int:
    code, output = setup_agent(args.agent, args.cogito_bin)
    if output:
        print(output)
    if code == 0:
        print(f"Cogito MCP configured for {args.agent}.")
    return code


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

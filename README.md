# Cogito Ergo Sum

Local-first personal context kernel for AI agents.

Cogito stores user memories from agent interactions, applies deterministic access policy, and returns compact context packs through CLI or MCP.

## MVP Features

- SQLite local vault.
- Append-only interaction event log.
- Structured memory store.
- Lenses and sensitivity filtering.
- Context pack generation.
- Access receipts.
- MCP-compatible JSON-RPC stdio server with memory tools.
- No runtime dependencies.

## Quick Start

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cogito init
cogito remember "User is building Cogito Ergo Sum, a local-first personal context kernel for AI agents." --type goal --sensitivity professional --contexts coding,professional
cogito context-pack "software architecture" --lens coding --max-sensitivity professional
```

Run an agent with Cogito context prepended:

```sh
cogito ask codex "help me design the next Cogito feature"
cogito ask claude "summarize what this project does"
cogito ask opencode "inspect this repo"
```

Keep one Cogito session while switching tools:

```sh
cogito session new --title "Cogito build" --agent codex
cogito session ask <session-id> --agent codex "review the current architecture"
cogito session ask <session-id> --agent claude "explain the tradeoffs"
cogito session ask <session-id> --agent opencode "inspect implementation gaps"
```

Register Cogito as MCP:

```sh
cogito setup-agent codex
cogito setup-agent claude
```

Default DB path:

```text
~/.local/share/cogito/cogito.db
```

Override with:

```sh
export COGITO_DB=/path/to/cogito.db
```

## MCP Server

Run:

```sh
cogito mcp
```

Exposed tools:

- `store_memory`
- `search_memory`
- `get_context_pack`
- `explain_memory`
- `delete_memory`

## Design Rule

Facts stay private. Intents travel.

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
python3 -m pip install -e .
cogito init
cogito remember "User is building Cogito Ergo Sum, a local-first personal context kernel for AI agents." --type goal --sensitivity professional --contexts coding,professional
cogito context-pack "software architecture" --lens coding --max-sensitivity professional
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


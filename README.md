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
sh scripts/bootstrap.sh
.venv/bin/cogito
```

Manual native setup:

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
cogito
cogito chat
cogito ask local "talk to the default local model"
cogito ask codex "help me design the next Cogito feature"
cogito ask claude "summarize what this project does"
cogito ask opencode "inspect this repo"
```

Inside `cogito chat`, normal turns go to the local Ollama model. Use `@persona` or `/tool` when you want Codex, Claude Code, or opencode:

```text
> think through this idea with me
> @architect review this repo
> /tool claude
> explain the tradeoffs
> /chat-model
> /chat-model qwen3:1.7b
> /memory-model
> /memory-model qwen3:1.7b
> /memories
> /exit
```

By default, chat hides Cogito metadata. Use verbose mode when you want command confirmations and session details:

```sh
cogito --verbose
```

Inside chat:

```text
/verbose on
/verbose off
```

Skip underlying tool permission prompts where supported:

```sh
cogito chat --yolo
```

Create personas:

```text
> /persona add architect codex gpt-5.5 Senior pragmatic software architect.
> /persona add explainer claude sonnet Patient teacher who explains tradeoffs.
> @architect review this design
> @explainer explain what architect suggested
```

Slash commands and `@persona` names autocomplete with Tab in an interactive terminal.
Typing `/` or `/per` and pressing Enter shows matching commands. `/help` shows full command reference. Prompts, personas, and metadata lists use terminal colors.

Default memory extractor:

```text
ollama:qwen3:0.6b
```

Default local chat model:

```text
ollama:qwen3:0.6b
```

Default relevance model:

```text
ollama:nomic-embed-text
```

Cogito auto-starts Ollama and pulls these models when possible. If Ollama is unavailable, memory extraction and retrieval fall back to local heuristics.
During chat, memory extraction runs silently in the background through a durable SQLite job queue. Plain user prompts are routed to the local chat model by default without waiting for the memory model. `@persona` routes a single turn to that persona's configured tool/model.

Docker Compose runs the local model service:

```sh
docker compose up -d ollama
```

Cogito itself runs on the host so it can launch your installed Codex, Claude Code, and opencode CLIs with their existing auth.

Keep one Cogito session while switching tools:

```sh
cogito session new --title "Cogito build" --agent codex
cogito session ask <session-id> --agent local "think locally"
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

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

Inside `cogito chat`, normal turns go to the active model. Cogito infers the needed adapter from the model:

```text
> think through this idea with me
> @architect review this repo
> /model sonnet
> explain the tradeoffs
> /models
> /chat-model
> /chat-model qwen3:1.7b
> /memory-model
> /memory-model qwen3:1.7b
> /memories
> /exit
```

Interactive terminals use a split TUI:

- Left pane: Cogito conversation and command input.
- Right pane: recent persona calls, status, and live underlying adapter output.
- `@persona ...` calls are queued in the background, so the left pane remains usable.
- External personas keep a persistent PTY process per persona, so later calls go to the same live Codex, Claude Code, or opencode session.
- Calls to the same persona are queued and sent to that persona's PTY in order.
- Use `/persona restart NAME` if a persona process gets stuck or you want a clean session.

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
> /persona add aristotle gpt-5.5
> /persona add architect gpt-5.5 Senior pragmatic software architect.
> /persona add explainer sonnet Patient teacher who explains tradeoffs.
> /persona research architect Martin Fowler
> /persona knowledge architect Prefers evolutionary architecture over large speculative rewrites.
> @architect review this design
> @explainer explain what architect suggested
> @me decide based on what you know about me
```

Persona descriptions stay in the persona table. Persona knowledge is separate RAG data in `persona_knowledge` and is injected only when that persona is called and the fact is relevant to the prompt. If you omit DESCRIPTION in `/persona add NAME MODEL`, Cogito automatically researches `NAME` from the internet and stores compact background chunks. `/persona research NAME SUBJECT` imports or refreshes public background manually; `/persona knowledge NAME TEXT` adds your own curated facts. `@me` is a built-in self-persona that uses permitted user memories from Cogito's normal access policy rather than a separate public-character RAG store.

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
During chat, memory extraction runs silently in the background through a durable SQLite job queue. Plain user prompts are routed to the active model without waiting for the memory model. `@persona` routes a single turn to that persona's configured model.

Docker Compose runs the local model service:

```sh
docker compose up -d ollama
```

Cogito itself runs on the host so it can launch your installed Codex, Claude Code, and opencode CLIs with their existing auth.
When `cogito chat --model MODEL` starts, Cogito checks the inferred adapter and installs it if it is missing. Manual startup/bootstrap commands are also available:

```sh
cogito install gpt-5.5
cogito update sonnet
```

Keep one Cogito session while switching models:

```sh
cogito session new --title "Cogito build" --model gpt-5.5
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

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
- Right pane: recent persona calls, status, and adapter output.
- `@persona ...` calls are queued in the background, so the left pane remains usable.
- Calls to the same persona are queued in order.
- External persona calls run non-interactively and return plain text into both panes.

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
> /persona historical aristotle gpt-5.5
> /persona create architect gpt-5.5 Senior pragmatic software architect.
> /persona create explainer sonnet Patient teacher who explains tradeoffs.
> /persona list
> /persona delete explainer
> /research @me https://www.linkedin.com/in/ruslan-klymenko-927a6b67/
> /research-browser @me https://www.linkedin.com/in/ruslan-klymenko-927a6b67/
> /research @architect Martin Fowler evolutionary architecture
> @architect review this design
> @explainer explain what architect suggested
> @me decide based on what you know about me
```

Persona descriptions stay in the persona table. Persona knowledge is separate RAG data in `persona_knowledge` and is injected only when that persona is called and the fact is relevant to the prompt. `/persona historical NAME MODEL [SUBJECT]` researches a public or historical personality from the internet and stores compact background chunks. `/persona create NAME MODEL DESCRIPTION` creates a persona directly from your description. `@me` is a built-in self-persona that uses permitted user memories from Cogito's normal access policy rather than a separate public-character RAG store.

Use `/research @TARGET URL_OR_QUERY` to enrich `@me` or any persona from open web research. Cogito fetches the provided URL when possible, derives a generic search query, follows search results from relevant sources, extracts readable text, and stores compact chunks into user memory for `@me` or persona RAG for other targets. It does not hardcode social platforms; LinkedIn, personal sites, GitHub, publications, interviews, and other public pages are discovered through the web search results that are available.

Use `/research-browser @TARGET URL_OR_QUERY` when a page needs your logged-in browser, such as LinkedIn. Cogito opens a persistent local browser profile at `~/.local/share/cogito/browser-profile`; log in there once, then rerun the command. It extracts visible page text from that browser session and stores it into the same memory/RAG stores.

Slash commands and `@persona` names autocomplete with Tab in an interactive terminal.
Typing `/` or `/per` and pressing Enter shows matching commands. `/help` shows full command reference. Prompts, personas, and metadata lists use terminal colors. Up and Down traverse a shared history file at `~/.local/share/cogito/history`, so previous prompts are available after restarting Cogito.

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

# Integrations

Cogito MVP integrates with agents through the CLI or the MCP stdio server. Use the CLI for scripts and manual checks; use `cogito mcp` when an agent client can launch a local MCP server and call tools.

## Fast Path

One-shot run with Cogito context injected into the prompt:

```sh
cogito ask codex "help me design the next Cogito feature"
cogito ask claude "summarize this repo"
cogito ask opencode "inspect this project"
```

Manual copy/paste prompt:

```sh
cogito prompt "help me design the next Cogito feature"
```

## MCP

Configure your agent tool runner to start Cogito as a stdio MCP server:

```sh
cogito mcp
```

Or let Cogito register itself:

```sh
cogito setup-agent codex
cogito setup-agent claude
```

Conceptually, the agent sends tool calls to Cogito instead of reading the database directly:

- `store_memory`: save a durable user fact, preference, goal, or instruction.
- `search_memory`: retrieve matching memories allowed by `lens` and `max_sensitivity`.
- `get_context_pack`: retrieve a compact, policy-filtered context block for prompt use.
- `explain_memory`: inspect provenance and access receipts for a memory.
- `delete_memory`: mark a memory deleted.

Recommended flow for agent tools:

1. Store only explicit, useful user context.
2. Search or request a context pack before tasks that need prior user context.
3. Pass `lens`, `max_sensitivity`, `agent`, and `purpose` so Cogito can apply access policy and write receipts.

## CLI Examples

Initialize the local vault:

```sh
cogito init
```

Store a memory:

```sh
cogito remember "User prefers concise implementation notes." \
  --type preference \
  --sensitivity professional \
  --contexts coding,professional
```

Search permitted memories:

```sh
cogito search "implementation notes" \
  --lens coding \
  --max-sensitivity professional \
  --agent codex \
  --purpose context_retrieval
```

Build a context pack:

```sh
cogito context-pack "working on CLI docs" \
  --lens coding \
  --max-sensitivity professional \
  --agent codex \
  --purpose prompt_context
```

Return the full JSON payload, including memories and receipt:

```sh
cogito context-pack "working on CLI docs" --json
```

## Database Path

By default, Cogito uses:

```text
~/.local/share/cogito/cogito.db
```

Override it per shell or process with `COGITO_DB`:

```sh
export COGITO_DB=/path/to/cogito.db
cogito init
cogito search "project preferences"
```

You can also pass `--db` for a single command:

```sh
cogito --db /tmp/cogito-test.db init
```

## Current Limitations

- Local SQLite only; no sync, remote storage, or multi-device merge.
- MCP runs over stdio and has no built-in authentication layer.
- Search is simple local ranking, not vector or embedding retrieval.
- Policy is deterministic but coarse: `lens` and `max_sensitivity` are the main controls.
- Memory extraction is basic; agents should avoid storing guesses as facts.
- Deletes mark memories inactive; this is not a secure erase guarantee.

# Cogito Ergo Sum Research Brief

Last updated: 2026-05-06

## Executive Summary

Build Cogito as a local-first personal context kernel for AI agents:

1. Store private human memory locally by default.
2. Split raw events, structured memories, and vector indexes.
3. Put deterministic policy enforcement before retrieval output.
4. Expose memory through MCP first because agent tools already understand MCP-style resources/tools/prompts.
5. Build protocol/federation around signed intents and grants, not around raw profile facts.
6. Avoid blockchain for private data. Use ledgers only for identity, schemas, revocation, receipts, reputation, escrow, or payment settlement.

Most important design rule:

> Facts stay private. Intents travel.

## Requirements As Understood

Cogito should:

- Continuously learn facts that a person exposes during interactions with agents like Codex, Claude Code, opencode, and future agent tools.
- Store those facts in appropriate datastores.
- Retrieve relevant facts as RAG/context for later agent sessions.
- Respect different access rights for different contexts.
- Keep professional conversations limited to professional/context-relevant memory.
- Allow intimate/personal agent contexts to access broader memory only when permitted.
- Support future interaction between Cogito nodes so agents can discover compatible people, common interests, collaboration opportunities, and negotiate introductions.
- Possibly use blockchain or another protocol if it helps interoperability/trust.

## Core Product Model

Cogito should model human context as governed memory, not as documents.

Recommended memory classes:

- `fact`: stable claim about user.
- `preference`: communication style, tools, workflow, habits.
- `goal`: active or long-term objective.
- `relationship`: person, organization, project, role.
- `episode`: summarized interaction or event.
- `belief`: worldview, taste, technical judgment.
- `intent`: what user wants now and is willing to reveal.
- `secret`: credentials, private/sensitive material.
- `receipt`: evidence that memory was accessed, updated, shared, or deleted.

Recommended memory fields:

```json
{
  "id": "mem_...",
  "subject": "did:key:...",
  "type": "goal",
  "text": "User is building Cogito Ergo Sum, a personal context kernel for AI agents.",
  "contexts": ["coding", "professional", "creative"],
  "sensitivity": "professional",
  "confidence": 0.93,
  "source_event_id": "evt_...",
  "provenance": "codex session on 2026-05-06",
  "state": "active",
  "created_at": "2026-05-06T...",
  "expires_at": null
}
```

## Architecture

Recommended stores:

1. Event log
   - Append-only source of truth.
   - Stores raw/sanitized interaction events, ingestion metadata, source tool, timestamp, hash.
   - Start with SQLite; migrate to Postgres if needed.

2. Structured memory store
   - Canonical facts, preferences, goals, relationships, policies, receipts.
   - SQL is better than vector DB for truth, permissions, lifecycle, and auditability.

3. Vector index
   - Retrieval accelerator only.
   - Store embeddings with minimal payload pointers and policy metadata.
   - Qdrant or pgvector are suitable.

Flow:

```text
agent interaction
  -> capture event
  -> extract candidate memories
  -> classify type/sensitivity/context
  -> user/policy approval
  -> structured store
  -> vector index
  -> later context request
  -> policy-scoped retrieval
  -> context pack
  -> access receipt
```

Important retrieval rule:

```text
policy scope -> candidate retrieval -> final policy filter -> rank -> compact context pack
```

Never:

```text
raw vector search -> prompt says "do not reveal private stuff"
```

## Policy Model

Each context request should include:

```json
{
  "agent_id": "did:key:agent...",
  "agent_name": "codex",
  "task": "software architecture discussion",
  "purpose": "coding_assistance",
  "lens": "professional",
  "max_sensitivity": "professional",
  "requested_memory_types": ["fact", "preference", "goal"],
  "token_budget": 1200
}
```

Policy result:

```json
{
  "allow": true,
  "filters": {
    "contexts": ["coding", "professional"],
    "sensitivity_lte": "professional",
    "state": ["active"]
  },
  "redactions": ["secrets", "intimate", "medical", "financial"]
}
```

Use deterministic enforcement in application code. Consider OPA/Rego later if policies become complex across remote agents, organizations, and grants. OPA is a general-purpose policy engine for structured authorization decisions.

## Lenses

Lenses are named projections of user memory:

- `coding`: technical projects, tools, style, repo preferences.
- `professional`: work history, skills, business goals, communication preferences.
- `creative`: artistic taste, writing style, creative projects.
- `personal`: life context and preferences.
- `intimate`: private emotional/relationship context.
- `public_profile`: safe public bio and opt-in interests.

Agents receive lens output, not the database.

Example context pack:

```text
Lens: coding/professional
User context:
- Building Cogito Ergo Sum, a local-first personal context kernel for AI agents.
- Prefers direct, pragmatic engineering advice.
- Wants protocol-ready design but local-first MVP.
- Current timezone: Europe/Zurich.

Forbidden in this lens:
- intimate facts
- medical/financial/legal details
- secrets
```

## Protocol And Federation

Recommended protocol stance:

```text
Private memory vault stays local.
Signed claims and intents can be shared.
Remote agents ask questions under purpose-bound grants.
User node answers with minimum disclosure.
```

Remote agents should not "read facts". They should submit governed requests:

```json
{
  "requester": "did:key:agent_alice",
  "purpose": "collaboration_matching",
  "question": "Does this user want to collaborate on local-first AI memory tools?",
  "requested_disclosure": "boolean_plus_short_summary"
}
```

Response:

```json
{
  "answer": true,
  "summary": "Interested in building local-first personal context infrastructure for AI agents.",
  "contact_allowed": false,
  "next_action": "intro_request"
}
```

Protocol objects:

- `Person`: user-owned identity.
- `Agent`: delegated software actor.
- `Memory`: private local record.
- `Claim`: signed statement, usually shareable or verifiable.
- `Intent`: time-bound opt-in desire to find/connect/negotiate.
- `Lens`: projection/access mode.
- `Grant`: object-capability permission.
- `Request`: remote query.
- `Introduction`: mutually approved connection.
- `Agreement`: negotiated outcome.
- `Receipt`: audit record.
- `Revocation`: invalidation of key, grant, claim, or receipt.

## Matching And Discovery

Best product primitive: Intent.

Users publish current, revocable, scoped intents:

```json
{
  "type": "find_collaborator",
  "topic": "local-first AI memory protocol",
  "constraints": {
    "timezone_overlap": true,
    "professional_only": true
  },
  "disclosure": {
    "anonymous_until_mutual_match": true,
    "share_summary": true,
    "share_contact_after_approval": true
  },
  "expires_at": "2026-06-06T00:00:00Z"
}
```

Discovery flow:

```text
Alice creates intent
Alice Cogito publishes sanitized matchable intent to relay
Matcher finds Bob intent compatibility
Alice agent sends intro request to Bob Cogito
Bob Cogito policy evaluates request
Bob agent summarizes proposal
Bob approves/rejects/auto-approves
Only then contact details or richer context are exchanged
```

Matching levels:

1. MVP: tags, keywords, structured constraints.
2. V1: embeddings over sanitized intent summaries.
3. V2: agent-mediated negotiation with rate limits and reputation.
4. Research: private set intersection or secure computation for overlap without full disclosure.

## Blockchain Assessment

Do not store private memory on-chain.

Reasons:

- Human facts are mutable and contextual.
- Some facts are wrong or inferred.
- Deletion/right-to-erasure conflicts with immutable ledgers.
- Metadata leaks relationships, interests, and timing even when content is encrypted.
- Keys and encryption age; permanent ciphertext can become future plaintext risk.

Possible useful ledger roles:

- DID/key registry.
- Agent/service registry.
- Schema registry.
- Public revocation list.
- Hash notarization of consent receipts.
- Matcher/agent reputation attestations.
- Escrow for paid introductions or work agreements.
- Payment settlement.

Recommended sequence:

1. Build chainless signed JSON receipts.
2. Add DID-compatible identifiers.
3. Add revocation registry in normal database.
4. Only add blockchain adapter after there is real multi-party trust problem.

## Standards And Current Research Anchors

MCP:

- Use MCP for local and remote agent integrations.
- Official MCP docs describe tools/resources/prompts and OAuth-based authorization for HTTP transports.
- For local stdio MCP, credentials should come from environment/local config; for HTTP MCP, use OAuth 2.1-style flows, PKCE, HTTPS, token expiration/rotation, resource/audience binding where available.

DID:

- W3C DID Core v1.0 is a Recommendation.
- DIDs are useful as long-lived identifiers resolving to verification material and service endpoints.
- For MVP, `did:key` or simple local key IDs are enough.

Verifiable Credentials:

- W3C VC Data Model v2.0 became a W3C Recommendation on 2025-05-15.
- Useful for portable signed claims and attestations, not for raw memory.

ActivityPub:

- W3C Recommendation for decentralized social/federated server-to-server exchange.
- Useful inspiration for inbox/outbox, activities, and federation.
- Might be too social-content-oriented for private agent negotiation; borrow patterns rather than implementing full compatibility immediately.

Solid:

- Strong conceptual fit: personal online data stores where users control app/agent access.
- Good inspiration for Pods, access control, interoperability, and user-owned data.
- Cogito can be "Solid for agent memory", but optimized for structured memory, RAG, policy, and agent negotiation.

DIDComm:

- Good reference for encrypted agent-to-agent/person-to-person messages using DID-based identities.
- Useful later for secure remote request/intro flows.

Policy engines:

- OPA/Rego can handle structured authorization.
- Start with simple deterministic policy code; add OPA when policies need externalized governance.

Vector DB:

- Qdrant supports JSON payloads and filtering over payload conditions.
- Use payload filters for lens/sensitivity/user/state scoping, but keep SQL as source of truth.

Privacy/security:

- GDPR defines personal data broadly, including identifiers, location, online identifiers, preferences, and social identity factors.
- This product creates profiles and therefore must be designed around privacy from day one.
- OWASP LLM Top 10 2025 risks relevant to Cogito include prompt injection, sensitive information disclosure, vector/embedding weakness, excessive agency, and data poisoning.
- NIST Privacy Framework is useful as a privacy risk management model.

## Creative Product Ideas

### Memory Firewall

Dedicated service that decides what memory can leave the vault.

Inputs:

- requester
- agent identity
- task purpose
- lens
- memory sensitivity
- user grants
- current risk score

Output:

- allow/deny/redact
- returned fields
- receipt

### Consent Receipts

Every disclosure writes a receipt:

```json
{
  "agent": "codex",
  "purpose": "coding_assistance",
  "memory_ids": ["mem_1", "mem_9"],
  "decision": "allowed",
  "reason": "professional lens permits coding/project preferences",
  "timestamp": "2026-05-06T..."
}
```

User can ask:

- Why did agent know this?
- When was this memory created?
- Who accessed it?
- How can I delete or restrict it?

### Contradiction Engine

Humans change. Cogito should detect conflicting memories:

```text
Old: user wants long detailed answers
New: user wants caveman terse mode
Resolution: context-specific preference, not global overwrite
```

### Memory Inbox

Agents propose new facts, but user can accept/edit/reject.

Low-risk facts can be auto-accepted. Sensitive facts should require explicit approval.

### Intention Marketplace Without Creepiness

Users do not publish profiles. They publish temporary intents.

Examples:

- Find collaborator for local-first AI memory.
- Find Zurich coffee chat about agent tooling.
- Find Rust MCP engineer.
- Find someone with overlapping reading interests.

Discovery reveals common point only after threshold and policy pass.

### Agent Diplomat

Each user has an agent that negotiates with other agents:

- determine compatibility
- exchange minimum facts
- draft intro
- schedule call
- negotiate terms
- ask human for approval at decision boundaries

### Context Simulator

Before granting an agent access, user sees exactly:

```text
This agent will know:
- X
- Y
- Z

This agent will not know:
- A
- B
```

### Personal Memory Diff

Show what changed this week:

- new facts learned
- facts marked stale
- sensitive memories added
- agents that accessed memory
- external intro requests received

## Implementation Recommendation

Start with:

```text
Python FastAPI or Rust/TypeScript daemon
SQLite source of truth
Qdrant optional vector index
MCP stdio server
local web UI
signed JSON messages
simple deterministic policy engine
```

Avoid first:

- blockchain
- complex zero-knowledge protocols
- global social graph
- cloud sync
- fully automatic sensitive memory capture

Build first vertical slice:

1. Ingest transcript manually.
2. Extract candidate memories.
3. Approve memories.
4. Query coding/professional context pack via MCP.
5. Log access receipt.
6. Preview/edit/delete memories in UI.

Then add:

1. Agent wrappers.
2. Remote intent publishing.
3. Intro request flow.
4. Signed claims/grants.
5. Optional federation relay.

## Research Sources

- W3C DID Core v1.0: https://www.w3.org/TR/did/
- W3C Verifiable Credentials Data Model v2.0: https://www.w3.org/TR/vc-data-model/
- W3C Verifiable Credentials 2.0 press release: https://www.w3.org/press-releases/2025/verifiable-credentials-2-0/
- MCP authorization spec: https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization
- MCP authorization current/draft context: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- MCP prompts/resources concepts: https://modelcontextprotocol.io/docs/concepts/prompts
- MCP security best practices: https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
- Qdrant payload/filtering docs: https://qdrant.tech/documentation/concepts/payload/
- Qdrant filtering docs: https://qdrant.tech/documentation/concepts/filtering/
- Open Policy Agent docs: https://www.openpolicyagent.org/docs
- ActivityPub W3C Recommendation: https://www.w3.org/TR/activitypub/
- Solid Project overview: https://solidproject.org/about.html
- DIDComm Messaging v2 spec: https://identity.foundation/didcomm-messaging/spec/
- GDPR Article 4 via EUR-Lex: https://eur-lex.europa.eu/legal-content/EN-ES/TXT/?from=EN&uri=CELEX%3A32016R0679
- NIST Privacy Framework: https://www.nist.gov/privacy-framework
- OWASP Top 10 for LLM Applications 2025 PDF: https://owasp.org/www-project-top-10-for-large-language-model-applications/assets/PDF/OWASP-Top-10-for-LLMs-v2025.pdf


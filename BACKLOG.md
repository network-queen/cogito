# Cogito Ergo Sum Backlog

Last updated: 2026-05-06

## Product Thesis

Cogito Ergo Sum is a local-first personal context kernel for AI agents. It captures facts, preferences, goals, relationships, memories, and intents that a human exposes while using agentic tools, then exposes only the right subset to each agent under explicit context, sensitivity, purpose, and consent rules.

The product is not "RAG over chat logs". It is user-owned memory, permissioned context retrieval, auditable agent access, and optional consent-based discovery between humans through their agents.

## North Star

An agent should be able to ask:

> Who is this user, for this task, under this trust level, and what am I allowed to know?

Cogito should answer with a compact, policy-filtered context pack, plus provenance and access receipt.

## P0: Foundation MVP

- [ ] Define repository structure and implementation language.
- [ ] Create local `cogito` daemon.
- [ ] Add local SQLite database as source of truth.
- [ ] Add append-only event log for user-agent interactions.
- [ ] Add memory schema for facts, preferences, goals, relationships, episodes, secrets, and intents.
- [ ] Add basic CLI:
  - [ ] `cogito ingest`
  - [ ] `cogito remember`
  - [ ] `cogito search`
  - [ ] `cogito context-pack`
  - [ ] `cogito forget`
- [ ] Add MCP server exposing:
  - [ ] `store_memory`
  - [ ] `search_memory`
  - [ ] `get_context_pack`
  - [ ] `explain_memory`
  - [ ] `delete_memory`
- [ ] Add simple memory extraction pipeline using LLM.
- [ ] Add manual review queue for extracted candidate memories.
- [ ] Add import path for existing session transcripts.

## P0: Access Control And Safety

- [ ] Define sensitivity levels:
  - [ ] public
  - [ ] professional
  - [ ] personal
  - [ ] intimate
  - [ ] financial
  - [ ] medical
  - [ ] legal
  - [ ] secret
- [ ] Define lenses:
  - [ ] coding
  - [ ] professional
  - [ ] creative
  - [ ] friend
  - [ ] intimate
  - [ ] public_profile
- [ ] Implement deterministic policy filter before any memory reaches an agent.
- [ ] Never rely on prompts alone for privacy.
- [ ] Add context request object:
  - [ ] agent identity
  - [ ] task purpose
  - [ ] requested lens
  - [ ] max sensitivity
  - [ ] token budget
  - [ ] reason for access
- [ ] Add access receipts for every memory disclosure.
- [ ] Add `why_did_agent_know_this` provenance command.
- [ ] Add sensitive memory confirmation before storage.
- [ ] Add delete/export flows.

## P1: Retrieval And Memory Quality

- [ ] Add vector index with Qdrant or pgvector.
- [ ] Store structured memory in SQL; use vector DB only as retrieval index.
- [ ] Enforce metadata filters by user, lens, sensitivity, and lifecycle state.
- [ ] Add hybrid retrieval:
  - [ ] structured filters
  - [ ] semantic search
  - [ ] recency boost
  - [ ] confidence boost
  - [ ] contradiction/staleness penalty
- [ ] Add memory lifecycle:
  - [ ] candidate
  - [ ] accepted
  - [ ] active
  - [ ] stale
  - [ ] archived
  - [ ] deleted
- [ ] Add contradiction detection.
- [ ] Add decay and expiration.
- [ ] Add fact confidence and provenance.
- [ ] Add context pack compression.

## P1: Agent Integrations

- [ ] Implement MCP stdio server for local agent tools.
- [ ] Implement MCP HTTP server with OAuth later.
- [ ] Add Codex integration docs.
- [ ] Add Claude Code integration docs.
- [ ] Add opencode integration docs.
- [ ] Add shell wrappers:
  - [ ] `cogito run codex`
  - [ ] `cogito run claude`
  - [ ] `cogito run opencode`
- [ ] Add session capture adapters where possible.
- [ ] Add explicit per-tool limitations because some tools may not expose full transcript hooks.

## P1: User Control UI

- [ ] Build local web UI.
- [ ] Add memory inbox for candidate facts.
- [ ] Add searchable memory graph/list.
- [ ] Add lens editor.
- [ ] Add policy editor.
- [ ] Add access receipt timeline.
- [ ] Add redaction and deletion UX.
- [ ] Add "what agents know about me" preview by lens.
- [ ] Add "simulate context pack" screen.

## P2: Cogito Protocol

- [ ] Define signed JSON message envelope.
- [ ] Add DID-style user identity key.
- [ ] Add agent identity and capability keys.
- [ ] Define protocol objects:
  - [ ] Person
  - [ ] Agent
  - [ ] Claim
  - [ ] Intent
  - [ ] Lens
  - [ ] Grant
  - [ ] Request
  - [ ] Introduction
  - [ ] Agreement
  - [ ] Receipt
  - [ ] Revocation
- [ ] Add remote request endpoint:
  - [ ] ask boolean question
  - [ ] request short summary
  - [ ] request intro
  - [ ] request scoped grant
- [ ] Add object-capability grants:
  - [ ] scope
  - [ ] purpose
  - [ ] expiry
  - [ ] revocation
  - [ ] audit log
- [ ] Add public/matchable intent publishing.
- [ ] Add relay server prototype.
- [ ] Add agent-to-agent negotiation protocol.

## P2: Consent-Based Matching

- [ ] Define Intent object for "what user wants now".
- [ ] Support anonymous matchable intents.
- [ ] Add matching engine over sanitized intents.
- [ ] Add mutual approval intro flow.
- [ ] Add "facts stay private, intents travel" rule.
- [ ] Add intersection finder:
  - [ ] simple keyword/tag MVP
  - [ ] embedding similarity
  - [ ] thresholded common-point disclosure
  - [ ] optional private set intersection research spike
- [ ] Add anti-spam/rate-limit design.
- [ ] Add reputation/attestation model.

## P3: Blockchain / Ledger Optional Layer

- [ ] Do not store raw memories, private facts, relationships, or interests on-chain.
- [ ] Research ledger only for:
  - [ ] DID/key registry
  - [ ] schema registry
  - [ ] public revocation list
  - [ ] consent receipt hashes
  - [ ] agent registry
  - [ ] matcher reputation
  - [ ] escrow/payment settlement
- [ ] Prototype chainless signed receipts first.
- [ ] Add ledger adapter only after real product need appears.

## P3: Advanced Privacy

- [ ] Add envelope encryption for local vault.
- [ ] Add per-memory encryption keys for high sensitivity classes.
- [ ] Add OS keychain integration.
- [ ] Add local-only embedding option.
- [ ] Add cloud sync threat model.
- [ ] Research secure enclaves for matching.
- [ ] Research zero-knowledge proofs for claims.
- [ ] Research private set intersection for interest overlap.

## Open Product Questions

- [ ] Should memory extraction be automatic, semi-automatic, or manual by default?
- [ ] What is the default lens for coding agents?
- [ ] How much raw transcript should be retained locally?
- [ ] What should be impossible to store without explicit consent?
- [ ] How should Cogito handle memories inferred incorrectly?
- [ ] How should users publish "find me for X" intents without creating a creepy search engine?
- [ ] What is the minimum useful protocol before federation?
- [ ] Which integrations can capture enough context legally and technically?


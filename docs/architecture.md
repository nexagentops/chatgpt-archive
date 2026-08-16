# Local-first archive and memory architecture

## Current architecture

V1 uses an authenticated, loopback-only browser boundary to discover and
capture ChatGPT conversations. Provider-shaped responses and DOM fallback are
normalized into versioned canonical JSON files. SQLite holds rebuildable
operational metadata; Markdown and CSV are derived exports. Sync is bounded,
incremental, atomic at individual-file replacement boundaries, and retains
locally archived conversations when a complete remote listing no longer sees
them. Browser credentials, cookies, and response headers are not archived.

Strong existing boundaries are browser acquisition, normalisation, canonical
filesystem storage, operational indexing, and derived export operations.
Current architectural debt is that the operational index originally had no
full-text content projection and CLI commands directly assemble some service
calls. The canonical JSON contract must remain authoritative during evolution;
an SQLite projection cannot become an implicit destructive migration.

## Target architecture

The migration path keeps canonical JSON portable while placing reusable
services above storage:

```text
providers -> normalization -> canonical archive store -> SQLite projections
                                              |                 |
                                              +-> history        +-> search
                                                                   |
CLI / future loopback API / future MCP / future local UI -> ArchiveService
                                                        -> SearchService
                                                        -> HistoryService
                                                        -> IntegrityService
                                                        -> MemoryService
```

Provider adapters remain responsible for acquisition and normalisation only.
The domain/store layer remains provider-neutral as fields become observable;
the present ChatGPT source is reported as `chatgpt` by the service layer rather
than embedded in FTS records. API and MCP are intentionally not implemented:
they must be thin, read-only clients of the same services, and any future HTTP
server defaults to `127.0.0.1`.

## Phased roadmap

| Phase | Objective and scope | Done when |
| --- | --- | --- |
| 0 | Preserve v1 baseline; record archive, sync, privacy, and compatibility constraints. | Existing tests and quality gates have an evidence-backed baseline. |
| 1 | Add migration-backed SQLite FTS projection and service boundary. Affected: `index`, `storage`, services, CLI, tests. No JSON schema change. | Reindexable deterministic search works without network access and verification detects a stale projection. |
| 2 | Expand `SearchService` filters and ranking tests for provider/workspace/project metadata once canonical data exists. | Search remains streaming SQL, deterministic, and usable by non-CLI clients. |
| 3 | Add append-only revision records and changes/diff/log services. | Sync can state added/changed observations without duplicating full bodies unnecessarily. |
| 4 | Expand integrity reporting and explicit repair planning. | Verification is read-only, deterministic, and reports database, asset, revision, and index invariants. |
| 5 | Introduce `MemoryService` retrieval and raw, traceable context packs. | Returned content remains data with source IDs, not trusted instructions. |
| 6 | Add a loopback-only, read-only HTTP adapter. | It delegates to services and never listens off-loopback by default. |
| 7 | Add a read-only MCP adapter over `MemoryService`. | Archived text is labelled untrusted data and destructive tools do not exist. |
| 8 | Add a minimal local UI over the same API/services. | No hosted account, analytics, or telemetry is required. |
| 9 | Add optional, explicitly configured local semantic retrieval and traceable context-pack summarisation. | FTS works independently and cloud embeddings are never implicit. |
| 10 | Add provider adapters only when acquisition semantics and fixtures exist. | Provider-specific data normalizes without weakening canonical invariants. |

Every phase requires migration tests where schema changes, compatibility tests
against existing JSON, privacy review, and the project quality gates.

## Decision records

### ADR-0001: Retain canonical JSON while adding a rebuildable FTS projection

- **Decision:** Keep v1 JSON as the portable authoritative record. Add SQLite
  FTS5 as a versioned, rebuildable search projection and expose it through
  `SearchService`.
- **Why:** This follows the explicit product requirements for local ownership,
  deterministic indexing, incremental processing, and backwards compatibility.
  It is not a reconstruction of unstated historical human rationale.
- **Alternatives:** Make SQLite authoritative now; build CLI-only search; defer
  search until vector retrieval.
- **Tradeoffs:** JSON plus SQLite duplicates searchable text, but preserves the
  proven export/recovery contract and avoids a destructive archive conversion.
- **Evidence:** v1 already atomically persists JSON and rebuilds SQLite through
  `reindex`; its regression suite covers recovery and conservative sync.
- **Revisit conditions:** Revisit if real archive scale shows JSON reindexing
  is not operationally acceptable, or if a portable canonical database format
  has migration, recovery, and independent validation evidence.

### ADR-0002: Archived conversation content is untrusted retrieval data

- **Decision:** Future API, MCP, and memory interfaces remain read-only and
  return archive content as data with source identifiers.
- **Why:** This directly preserves the supplied security boundary around
  prompt injection, local privacy, and destructive actions.
- **Alternatives:** Permit agent write operations; treat retrieved instructions
  as executable prompts; expose a remote API early.
- **Tradeoffs:** Agents need an explicit, separately authorised write path in a
  future phase, which is deliberately slower but safer.
- **Evidence:** The current repository already fails closed around browser
  authentication and remote disappearance.
- **Revisit conditions:** Only after a dedicated threat model, authentication
  design, and tests demonstrate constrained, auditable write authority.

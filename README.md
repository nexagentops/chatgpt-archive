# chatgpt-archive

`chatgpt-archive` is a local-first archive tool for conversations owned by the
currently authenticated ChatGPT user. Authentication remains entirely in a
browser profile; the archive tool never asks for, copies, prints, or exports
passwords, cookies, tokens, headers, or browser storage.

## Archive contract

- **JSON** is the canonical, portable archive representation.
- **SQLite** is transactional operational/index state and is rebuildable from
  canonical JSON.
- **Markdown** and **CSV** are deterministic derived exports.

Successful storage does not imply every content type is complete. Each JSON
record carries explicit completeness fields, capture method, branch scope, and
unsupported-content classifications. V1 does not download attachment/image
binaries or tool payloads; such captures remain `partial` when detected.

## Browser boundary

For an existing isolated Chrome Beta session, start Chrome Beta yourself with
an archive-owned user-data directory and loopback-only CDP, then attach:

```bash
chatgpt-archive discover --cdp-url http://127.0.0.1:9222
chatgpt-archive sync --cdp-url http://127.0.0.1:9222
```

The endpoint must be an unauthenticated loopback URL. The CLI refuses remote
or credential-bearing CDP URLs, disconnects without closing the browser, and
never automates a login. Keep the browser profile outside the repository.
`login` is available only for a separate persistent local profile and waits for
manual sign-in; it never handles credentials.

## Discovery and sync

`discover` first observes ordinary browser responses for structured history
data and paginates its offset/limit batches through the authenticated browser
context. It falls back to the virtualized sidebar only when structured history
is unavailable. Runs record requested limit, counts, source methods, batches,
and an explicit termination reason: `limit_reached`, `history_exhausted`,
`pagination_stalled`, `authentication_required`, `structured_unavailable`, or
`fatal_error`.

Structured batches checkpoint-merge stable conversation IDs into the manifest,
so interruption can resume without duplicate entries. `sync` writes canonical
JSON and Markdown atomically, then indexes the result. `--refresh` recaptures
completed conversations; unchanged hashes preserve existing files and changed
validated content replaces them atomically. Failures retain a structured record
and are retryable. Use `--limit N` or `--conversation ID` for bounded work.

Conversation acquisition prefers structured browser responses (including
alternate branches when present), normalized into the same schema as DOM
fallback acquisition. DOM remains a bounded, safe fallback. Debug screenshot
and rendered-HTML capture is opt-in via `--debug-dir`; it is disabled by
default because it can contain private content.

## Remote/local reconciliation

Discovery records operational remote presence in SQLite:

- `remote_present` with first/last remote-seen timestamps;
- `remote_missing` only after a complete structured history run; and
- `remote_unknown` when completeness is unavailable.

Remote disappearance never deletes canonical JSON, Markdown, CSV, or archive
rows. A `remote_missing` archive remains retained and verifiable locally.

## Operations

```bash
chatgpt-archive discover --limit 100
chatgpt-archive sync --limit 100
chatgpt-archive status
chatgpt-archive inspect <conversation-id>
chatgpt-archive render-markdown
chatgpt-archive export-csv
chatgpt-archive reindex
chatgpt-archive verify
chatgpt-archive backup /safe/empty/destination
chatgpt-archive migrate
chatgpt-archive doctor --cdp-url http://127.0.0.1:9222
```

`render-markdown` and `export-csv` regenerate derived files from canonical
JSON without browser access. `verify` checks JSON/schema parsing, IDs,
message ordering and parents, hashes, Markdown linkage, SQLite consistency,
and existing CSV exports. `backup` copies archive material only—never browser
profiles—and can be verified after restore into a clean directory. `migrate`
is explicit and only supports known canonical schema transitions.

If authentication expires, the CLI fails closed. Reauthenticate manually in
the isolated browser, then rerun discovery or sync; completed IDs and atomic
writes make recovery deterministic.

## Local layout and Git safety

```text
data/
  manifest.json
  raw/                 # canonical JSON
  markdown/            # derived
  exports/             # derived CSV
  archive.db           # operational index
```

`data/`, `.playwright-profile/`, and `debug/` are Git-ignored. Never commit
real conversations, debug artifacts, browser profiles, or authentication
material.

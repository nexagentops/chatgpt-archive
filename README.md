# chatgpt-archive

`chatgpt-archive` is a local-first archive tool for conversations owned by the
currently authenticated ChatGPT user. Authentication remains entirely in a
browser profile; the archive tool never asks for, copies, prints, or exports
passwords, cookies, tokens, headers, or browser storage.

## Install

Requires Python 3.12 or newer. Playwright is a runtime dependency; browser
binaries are required only for browser-backed commands.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install .
chatgpt-archive --help
```

For development, install deterministic test and lint tools with:

```bash
pip install -e '.[dev]'
```

Runtime dependencies are Pydantic (schema validation), Typer (CLI), and
Playwright (browser attachment). Development dependencies are pytest and Ruff.

## Deterministic quality gates

The automated suite uses synthetic fixtures and does not require a ChatGPT
account, browser profile, or credentials. Run:

```bash
ruff check .
pytest
python -m compileall -q src
```

GitHub Actions runs these deterministic checks on Python 3.12 and 3.13. Live
account validation remains opt-in/manual and is never run in CI. Mypy is not
configured for v1.0; adding useful static typing coverage is a future
engineering improvement rather than a release gate.

## Architecture

```text
isolated authenticated browser
→ structured history discovery
→ structured conversation acquisition / DOM fallback
→ canonical JSON
→ SQLite operational index
→ Markdown / CSV derived exports
```

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
or credential-bearing CDP URLs, verifies that `localhost` resolves only to
loopback, disconnects without closing the browser, and never automates a login.
By default, persistent browser state is stored outside the repository: macOS
uses `~/Library/Application Support/chatgpt-archive/browser-profile`; other
Unix environments use `$XDG_STATE_HOME/chatgpt-archive/browser-profile` or
`~/.local/state/chatgpt-archive/browser-profile`. `login` prints the resolved
path and waits for manual sign-in; it never handles credentials. Existing users
who deliberately need their old local checkout profile can continue to pass
`--profile-dir .playwright-profile` explicitly.

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

## Privacy and responsible use

Archive contents, debug artifacts, and browser profiles are sensitive. Keep
them local and outside Git. Browser profiles are excluded from backups by
default. The tool has no telemetry, does not send content to an external LLM or
API, and does not automatically delete or modify ChatGPT conversations. It is
intended for archival of conversations belonging to the authenticated user.

Keep CDP/debugging localhost-only. See [SECURITY.md](SECURITY.md) for the full
security and privacy model.

When choosing `--data-dir`, `--debug-dir`, or `--profile-dir`, prefer a
location outside a Git checkout. The repository ignores known local runtime
locations—including archive, export, profile, session, debug, database, log,
and environment-file patterns—but Git ignore rules are a safeguard, not a
publication boundary. Never force-add those artifacts; check a custom path with
`git check-ignore -v <path>` before staging it.

## Tested scale

The architecture uses incremental, bounded processing and is designed for
large archives. Full live validation was performed against a complete
real-world accessible account archive. This project has **not** been empirically
live-tested against 1,000 conversations.

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

Known runtime locations such as `data/`, archive/export directories,
browser/session state, `.playwright-profile/`, and `debug/` are Git-ignored.
Never commit real conversations, debug artifacts, browser profiles,
authentication material, local databases, logs, or environment files.

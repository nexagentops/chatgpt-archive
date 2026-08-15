# chatgpt-archive

`chatgpt-archive` is a local-first, browser-automation proof of concept for archiving ChatGPT conversations that belong to the currently authenticated user. It does not rely on an assumed public consumer API or ChatGPT's account Data Export workflow.

## Security and privacy

The CLI never asks for or stores an OpenAI password, never prints cookies/tokens, has no telemetry, makes no LLM/API calls during extraction, and never sends conversation content to another service. Browser session state lives only in `.playwright-profile/`; archives live under `data/`; both are ignored by Git. Do not commit real archive content.

## Install

Requires Python 3.12+.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
playwright install chromium
```

The initial POC declares its runtime dependencies in `pyproject.toml`; install pytest separately if it is not already available: `pip install pytest`.

## Use

```bash
chatgpt-archive login
chatgpt-archive discover
chatgpt-archive sync
chatgpt-archive status
chatgpt-archive inspect <conversation-id>
chatgpt-archive reindex
chatgpt-archive verify
chatgpt-archive export-csv
chatgpt-archive stats
chatgpt-archive doctor --cdp-url http://127.0.0.1:9222
chatgpt-archive backup /safe/empty/destination
```

`login` opens a persistent Chromium profile for manual sign-in only. `discover` scans the visible history sidebar, scrolls it, deduplicates `/c/<id>` links, and checkpoint-merges them into `data/manifest.json`. `sync` processes all entries that are not completed, writes JSON first and Markdown second using atomic replacement, then marks each entry completed. Failed items retain a structured error and will be retried by a later sync; a failure does not stop subsequent entries.

For bounded validation, use `discover --limit 25`, `sync --limit 25`, or `sync --conversation <id>`. `inspect <id>` reports only visible-turn counts and sanitized relevant response endpoint metadata; it does not print conversation text, headers, or browser storage. `--debug-dir debug` on `sync` is opt-in and saves screenshot/HTML failure artifacts locally. Those artifacts can contain conversation content and are Git-ignored; debugging is off by default.

To reuse an already-running browser without copying its profile, the commands that access ChatGPT accept `--cdp-url http://127.0.0.1:<port>`. The endpoint must be an unauthenticated loopback Chrome DevTools connection; the tool refuses remote or credential-bearing URLs. The browser must already have been started by the user with that endpoint. The tool only attaches and disconnects—it never closes that Chrome instance or reads cookies, storage, or credentials.

## Architecture

`browser → discovery → extractor → normalizer/models → storage`

The Playwright adapter is isolated in `browser.py` and `extractor.py`; `ConversationAcquirer` permits a future acquisition mechanism without changing canonical `Conversation`/`Message` JSON. Selectors are centralized in `discovery.py` and use semantic attributes and ARIA/structural selectors before generic CSS. The current DOM assumption is that history links contain `/c/<id>` and visible turns have `data-message-author-role`.

## Archive layout

```text
data/
  manifest.json
  raw/<conversation-id>.json
  markdown/<conversation-id>.md
```

JSON is canonical and Markdown is derived. File names are deterministic, ID-derived safe stems (with a short ID hash), never titles. Each JSON record explicitly marks capture as `full`, `partial`, or `failed`, and records unsupported content/branch limitations; successful storage does not imply all rich content was captured.

`archive.db` is a SQLite operational index rebuilt from JSON with `reindex`; it supports fast totals and integrity cross-checks but is never the sole archive copy. `exports/conversations.csv` and `exports/messages.csv` are deterministic derived files regenerated with `export-csv`. `verify` checks JSON parsing, message parent/order invariants, Markdown presence, content hashes, and index consistency. `backup` copies archive material only and deliberately excludes the browser profile.

## Limitations

DOM capture extracts only the current visible branch and visible text. It does not archive attachment/image binaries or tool output. Structured browser responses observed during ordinary navigation can normalize conversation mappings and alternate branches, but the response adapter is not yet enabled for live capture. ChatGPT UI changes can require selector updates. Live use needs an account the user is authorized to archive; synthetic fixtures cover automated tests, not the live service.

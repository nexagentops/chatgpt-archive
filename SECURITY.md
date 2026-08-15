# Security and privacy

`chatgpt-archive` is intended only for archives owned by the authenticated
user. Conversation archives and browser profiles are sensitive local data.

- Authenticate manually in an isolated, archive-owned browser profile. The
  default is outside the checkout: `~/Library/Application
  Support/chatgpt-archive/browser-profile` on macOS, or
  `$XDG_STATE_HOME/chatgpt-archive/browser-profile` (falling back to
  `~/.local/state/chatgpt-archive/browser-profile`) on other Unix systems. Do
  not point the tool at a normal browser profile. An existing checkout-local
  profile is used only when explicitly passed with `--profile-dir`.
- CDP control is accepted only on unauthenticated loopback endpoints. Never
  expose a debugging port to a network.
- The CLI does not accept passwords or copy, print, log, export, or back up
  cookies, tokens, headers, credentials, or browser storage.
- Browser profiles are excluded from backups. Keep archives, exports, browser
  state, debug artifacts, logs, databases, environment files, and validation
  outputs outside Git. Ignore rules cover common local paths but do not make a
  force-added or custom path safe for publication.
- There is no telemetry and no external LLM/API content processing.
- The tool does not automatically delete or modify ChatGPT conversations.

If authentication expires, reauthenticate manually in the isolated browser;
the CLI fails closed rather than attempting a login workflow.

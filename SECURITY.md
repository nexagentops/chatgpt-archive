# Security and privacy

`chatgpt-archive` is intended only for archives owned by the authenticated
user. Conversation archives and browser profiles are sensitive local data.

- Authenticate manually in an isolated, archive-owned browser profile such as
  `~/.chatgpt-archive/chrome-beta-data`; do not point the tool at a normal
  browser profile.
- CDP control is accepted only on unauthenticated loopback endpoints. Never
  expose a debugging port to a network.
- The CLI does not accept passwords or copy, print, log, export, or back up
  cookies, tokens, headers, credentials, or browser storage.
- Browser profiles are excluded from backups. Keep archives, debug artifacts,
  logs, and validation outputs outside Git.
- There is no telemetry and no external LLM/API content processing.
- The tool does not automatically delete or modify ChatGPT conversations.

If authentication expires, reauthenticate manually in the isolated browser;
the CLI fails closed rather than attempting a login workflow.

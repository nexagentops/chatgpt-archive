# Changelog

## 1.0.0 - 2026-08-15

- Structured history discovery with browser-mediated pagination and DOM fallback.
- Hybrid structured-response and DOM conversation acquisition.
- Atomic, resumable incremental sync with new, changed, and unchanged handling.
- Versioned canonical JSON archives, a rebuildable SQLite operational index, and
  derived Markdown and CSV exports.
- Archive verification, backup/restore, explicit schema migration, and
  remote/local reconciliation that retains remote-missing local archives.
- Explicit partial completeness for rich content and alternate-branch metadata.

### Limitations

Attachment, image, and tool binaries are not downloaded in v1.0. Their
presence is classified when observable and affected captures remain partial.

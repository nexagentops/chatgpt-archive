"""SQLite operational index. Canonical conversation JSON remains authoritative."""
from __future__ import annotations

import sqlite3
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Conversation

INDEX_SCHEMA_VERSION = 2


class ArchiveIndex:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT, updated_at TEXT,
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, last_captured_at TEXT NOT NULL,
                    capture_status TEXT NOT NULL, capture_method TEXT NOT NULL, message_count INTEGER NOT NULL,
                    current_branch_only INTEGER NOT NULL, json_path TEXT NOT NULL, markdown_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, last_error TEXT,
                    first_seen_remote_at TEXT, last_seen_remote_at TEXT,
                    remote_presence_status TEXT NOT NULL DEFAULT 'remote_unknown'
                );
                CREATE TABLE IF NOT EXISTS messages (
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    message_id TEXT NOT NULL, parent_id TEXT, sequence INTEGER NOT NULL, branch TEXT NOT NULL,
                    role TEXT NOT NULL, timestamp TEXT, model TEXT, content_type TEXT NOT NULL,
                    has_attachment INTEGER NOT NULL, has_tool_content INTEGER NOT NULL,
                    PRIMARY KEY (conversation_id, message_id), UNIQUE(conversation_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS sync_runs (
                    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, result TEXT,
                    discovered INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0, target_limit INTEGER, new_count INTEGER NOT NULL DEFAULT 0,
                    changed_count INTEGER NOT NULL DEFAULT 0, unchanged_count INTEGER NOT NULL DEFAULT 0,
                    retried INTEGER NOT NULL DEFAULT 0, structured_count INTEGER NOT NULL DEFAULT 0,
                    dom_count INTEGER NOT NULL DEFAULT 0, peak_rss_mb REAL, elapsed_seconds REAL,
                    starting_rss_mb REAL, ending_rss_mb REAL, longest_capture_seconds REAL,
                    structured_failures INTEGER NOT NULL DEFAULT 0, dom_failures INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS capture_errors (
                    id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL, stage TEXT NOT NULL,
                    category TEXT NOT NULL, occurred_at TEXT NOT NULL, message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    run_id TEXT PRIMARY KEY, requested_limit INTEGER, discovered_count INTEGER NOT NULL,
                    new_count INTEGER NOT NULL, existing_count INTEGER NOT NULL, duplicate_count INTEGER NOT NULL,
                    complete INTEGER NOT NULL, termination_reason TEXT NOT NULL, source_method_counts TEXT NOT NULL,
                    pages_or_batches INTEGER NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_captured ON conversations(last_captured_at);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
            """)
            existing_sync = {row[1] for row in connection.execute("PRAGMA table_info(sync_runs)")}
            for name, sql_type in {"target_limit": "INTEGER", "new_count": "INTEGER NOT NULL DEFAULT 0", "changed_count": "INTEGER NOT NULL DEFAULT 0", "unchanged_count": "INTEGER NOT NULL DEFAULT 0", "retried": "INTEGER NOT NULL DEFAULT 0", "structured_count": "INTEGER NOT NULL DEFAULT 0", "dom_count": "INTEGER NOT NULL DEFAULT 0", "peak_rss_mb": "REAL", "elapsed_seconds": "REAL", "starting_rss_mb": "REAL", "ending_rss_mb": "REAL", "longest_capture_seconds": "REAL", "structured_failures": "INTEGER NOT NULL DEFAULT 0", "dom_failures": "INTEGER NOT NULL DEFAULT 0"}.items():
                if name not in existing_sync:
                    connection.execute(f"ALTER TABLE sync_runs ADD COLUMN {name} {sql_type}")
            existing_conversations = {row[1] for row in connection.execute("PRAGMA table_info(conversations)")}
            for name, sql_type in {
                "first_seen_remote_at": "TEXT", "last_seen_remote_at": "TEXT",
                "remote_presence_status": "TEXT NOT NULL DEFAULT 'remote_unknown'",
            }.items():
                if name not in existing_conversations:
                    connection.execute(f"ALTER TABLE conversations ADD COLUMN {name} {sql_type}")
            current_version = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
            if current_version > INDEX_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Archive index schema {current_version} is newer than this version supports ({INDEX_SCHEMA_VERSION})."
                )
            if current_version < 1:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, datetime.now(timezone.utc).isoformat()),
                )
                current_version = 1
            if current_version < 2:
                # This is a rebuildable projection of canonical JSON, never an
                # authority for archive content. Existing archives are filled by
                # the explicit reindex command rather than a hidden full scan.
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS message_fts "
                    "USING fts5(conversation_id UNINDEXED, message_id UNINDEXED, title, text, "
                    "tokenize='unicode61 remove_diacritics 2')"
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (2, datetime.now(timezone.utc).isoformat()),
                )

    def start_run(self, target_limit: int | None, discovered: int) -> str:
        self.initialize(); run_id = str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute("INSERT INTO sync_runs(run_id, started_at, target_limit, discovered) VALUES (?, ?, ?, ?)", (run_id, datetime.now(timezone.utc).isoformat(), target_limit, discovered))
        return run_id

    def finish_run(self, run_id: str, result: str, **metrics: int | float | None) -> None:
        allowed = {"archived", "failed", "new_count", "changed_count", "unchanged_count", "retried", "structured_count", "dom_count", "peak_rss_mb", "elapsed_seconds", "starting_rss_mb", "ending_rss_mb", "longest_capture_seconds", "structured_failures", "dom_failures"}
        values = {key: value for key, value in metrics.items() if key in allowed}
        assignments = ", ".join(["ended_at=?", "result=?"] + [f"{key}=?" for key in values])
        with self.connect() as connection:
            connection.execute(f"UPDATE sync_runs SET {assignments} WHERE run_id=?", (datetime.now(timezone.utc).isoformat(), result, *values.values(), run_id))

    def record_discovery_run(
        self, *, requested_limit: int | None, discovered_count: int, new_count: int,
        existing_count: int, duplicate_count: int, complete: bool,
        termination_reason: str, source_method_counts: dict[str, int],
        pages_or_batches: int, started_at: datetime, elapsed_seconds: float,
    ) -> None:
        self.initialize()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO discovery_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), requested_limit, discovered_count, new_count, existing_count,
                    duplicate_count, int(complete), termination_reason,
                    json.dumps(source_method_counts, sort_keys=True), pages_or_batches,
                    started_at.isoformat(), datetime.now(timezone.utc).isoformat(), elapsed_seconds,
                ),
            )

    def upsert(self, conversation: Conversation, json_path: Path, markdown_path: Path, content_hash: str) -> None:
        self.initialize()
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("""
                INSERT INTO conversations (
                    conversation_id, title, created_at, updated_at, first_seen_at, last_seen_at,
                    last_captured_at, capture_status, capture_method, message_count,
                    current_branch_only, json_path, markdown_path, content_hash, schema_version,
                    last_error, first_seen_remote_at, last_seen_remote_at, remote_presence_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at,
                  last_seen_at=excluded.last_seen_at, last_captured_at=excluded.last_captured_at,
                  capture_status=excluded.capture_status, capture_method=excluded.capture_method,
                  message_count=excluded.message_count, current_branch_only=excluded.current_branch_only,
                  json_path=excluded.json_path, markdown_path=excluded.markdown_path, content_hash=excluded.content_hash,
                  schema_version=excluded.schema_version, last_error=NULL,
                  first_seen_remote_at=COALESCE(conversations.first_seen_remote_at, excluded.first_seen_remote_at),
                  last_seen_remote_at=excluded.last_seen_remote_at, remote_presence_status='remote_present'
            """, (conversation.conversation_id, conversation.title, _iso(conversation.created_at), _iso(conversation.updated_at), now, now, _iso(conversation.captured_at), conversation.capture_status.value, conversation.capture_method, len(conversation.messages), int(not conversation.conversation_tree_complete), str(json_path), str(markdown_path), content_hash, conversation.schema_version, None, now, now, "remote_present"))
            connection.execute("DELETE FROM messages WHERE conversation_id=?", (conversation.conversation_id,))
            connection.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                (conversation.conversation_id, message.id, message.parent_id, message.sequence, message.branch, message.role, _iso(message.timestamp), message.model, message.content_type, int(bool(message.attachments)), int(message.content_type == "tool"))
                for message in conversation.messages
            ])
            connection.execute("DELETE FROM message_fts WHERE conversation_id=?", (conversation.conversation_id,))
            connection.executemany(
                "INSERT INTO message_fts(conversation_id, message_id, title, text) VALUES (?, ?, ?, ?)",
                [
                    (conversation.conversation_id, message.id, conversation.title, message.text)
                    for message in conversation.messages
                ],
            )

    def search_messages(
        self, query: str, *, conversation_id: str | None = None, role: str | None = None, limit: int = 20,
    ) -> list[sqlite3.Row]:
        """Search the local FTS projection without reading archive files into memory."""
        self.initialize()
        clauses = ["message_fts MATCH ?"]
        values: list[object] = [_fts_query(query)]
        if conversation_id:
            clauses.append("message_fts.conversation_id=?")
            values.append(conversation_id)
        if role:
            clauses.append("messages.role=?")
            values.append(role)
        values.append(limit)
        with self.connect() as connection:
            return connection.execute(
                f"""SELECT message_fts.conversation_id, message_fts.message_id, conversations.title,
                           messages.timestamp, messages.role, messages.model,
                           snippet(message_fts, 3, '[', ']', '…', 16) AS snippet,
                           bm25(message_fts) AS rank
                    FROM message_fts
                    JOIN messages ON messages.conversation_id=message_fts.conversation_id
                                 AND messages.message_id=message_fts.message_id
                    JOIN conversations ON conversations.conversation_id=message_fts.conversation_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY rank, messages.timestamp, message_fts.conversation_id, message_fts.message_id
                    LIMIT ?""",
                values,
            ).fetchall()

    def fts_rows(self, conversation_id: str, message_id: str) -> list[sqlite3.Row]:
        self.initialize()
        with self.connect() as connection:
            return connection.execute(
                "SELECT title, text FROM message_fts WHERE conversation_id=? AND message_id=?",
                (conversation_id, message_id),
            ).fetchall()

    def totals(self) -> dict[str, int]:
        self.initialize()
        with self.connect() as connection:
            return {"conversations": connection.execute("SELECT count(*) FROM conversations").fetchone()[0], "messages": connection.execute("SELECT count(*) FROM messages").fetchone()[0]}

    def rows(self) -> list[sqlite3.Row]:
        self.initialize()
        with self.connect() as connection:
            return connection.execute("SELECT * FROM conversations ORDER BY conversation_id").fetchall()

    def get(self, conversation_id: str) -> sqlite3.Row | None:
        self.initialize()
        with self.connect() as connection:
            return connection.execute("SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()

    def latest_run(self) -> sqlite3.Row | None:
        self.initialize()
        with self.connect() as connection:
            return connection.execute("SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 1").fetchone()

    def reconcile_remote_presence(self, remote_ids: set[str], *, history_complete: bool) -> dict[str, int]:
        """Record discovery presence without changing canonical archive files.

        A non-complete discovery may establish positive presence but must never
        classify unseen rows as missing.
        """
        self.initialize()
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            for conversation_id in remote_ids:
                connection.execute(
                    """UPDATE conversations
                       SET first_seen_remote_at=COALESCE(first_seen_remote_at, ?),
                           last_seen_remote_at=?, remote_presence_status='remote_present'
                       WHERE conversation_id=?""",
                    (now, now, conversation_id),
                )
            if history_complete:
                placeholders = ", ".join("?" for _ in remote_ids) or "''"
                connection.execute(
                    f"UPDATE conversations SET remote_presence_status='remote_missing' "
                    f"WHERE conversation_id NOT IN ({placeholders})",
                    tuple(remote_ids),
                )
            rows = connection.execute(
                "SELECT remote_presence_status, count(*) AS count FROM conversations GROUP BY remote_presence_status"
            ).fetchall()
        return {row["remote_presence_status"]: row["count"] for row in rows}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _fts_query(query: str) -> str:
    """Treat user input as literal lexical terms, not FTS syntax."""
    terms = [term for term in query.split() if term]
    if not terms:
        raise ValueError("Search query must contain at least one non-whitespace term.")
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)

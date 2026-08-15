"""SQLite operational index. Canonical conversation JSON remains authoritative."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import Conversation

INDEX_SCHEMA_VERSION = 1


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
                    content_hash TEXT NOT NULL, schema_version INTEGER NOT NULL, last_error TEXT
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
                    dom_count INTEGER NOT NULL DEFAULT 0, peak_rss_mb REAL, elapsed_seconds REAL
                );
                CREATE TABLE IF NOT EXISTS capture_errors (
                    id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL, stage TEXT NOT NULL,
                    category TEXT NOT NULL, occurred_at TEXT NOT NULL, message TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_captured ON conversations(last_captured_at);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
            """)
            existing = {row[1] for row in connection.execute("PRAGMA table_info(sync_runs)")}
            for name, sql_type in {"target_limit": "INTEGER", "new_count": "INTEGER NOT NULL DEFAULT 0", "changed_count": "INTEGER NOT NULL DEFAULT 0", "unchanged_count": "INTEGER NOT NULL DEFAULT 0", "retried": "INTEGER NOT NULL DEFAULT 0", "structured_count": "INTEGER NOT NULL DEFAULT 0", "dom_count": "INTEGER NOT NULL DEFAULT 0", "peak_rss_mb": "REAL", "elapsed_seconds": "REAL"}.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE sync_runs ADD COLUMN {name} {sql_type}")
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)", (INDEX_SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()))

    def start_run(self, target_limit: int | None, discovered: int) -> str:
        self.initialize(); run_id = str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute("INSERT INTO sync_runs(run_id, started_at, target_limit, discovered) VALUES (?, ?, ?, ?)", (run_id, datetime.now(timezone.utc).isoformat(), target_limit, discovered))
        return run_id

    def finish_run(self, run_id: str, result: str, **metrics: int | float) -> None:
        allowed = {"archived", "failed", "new_count", "changed_count", "unchanged_count", "retried", "structured_count", "dom_count", "peak_rss_mb", "elapsed_seconds"}
        values = {key: value for key, value in metrics.items() if key in allowed}
        assignments = ", ".join(["ended_at=?", "result=?"] + [f"{key}=?" for key in values])
        with self.connect() as connection:
            connection.execute(f"UPDATE sync_runs SET {assignments} WHERE run_id=?", (datetime.now(timezone.utc).isoformat(), result, *values.values(), run_id))

    def upsert(self, conversation: Conversation, json_path: Path, markdown_path: Path, content_hash: str) -> None:
        self.initialize()
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("""
                INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at,
                  last_seen_at=excluded.last_seen_at, last_captured_at=excluded.last_captured_at,
                  capture_status=excluded.capture_status, capture_method=excluded.capture_method,
                  message_count=excluded.message_count, current_branch_only=excluded.current_branch_only,
                  json_path=excluded.json_path, markdown_path=excluded.markdown_path, content_hash=excluded.content_hash,
                  schema_version=excluded.schema_version, last_error=NULL
            """, (conversation.conversation_id, conversation.title, _iso(conversation.created_at), _iso(conversation.updated_at), now, now, _iso(conversation.captured_at), conversation.capture_status.value, conversation.capture_method, len(conversation.messages), int(not conversation.conversation_tree_complete), str(json_path), str(markdown_path), content_hash, conversation.schema_version, None))
            connection.execute("DELETE FROM messages WHERE conversation_id=?", (conversation.conversation_id,))
            connection.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                (conversation.conversation_id, message.id, message.parent_id, message.sequence, message.branch, message.role, _iso(message.timestamp), message.model, message.content_type, int(bool(message.attachments)), int(message.content_type == "tool"))
                for message in conversation.messages
            ])

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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None

"""Reusable local archive services shared by present and future interfaces."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .history import revisions_for
from .models import Conversation
from .storage import ArchiveStore


@dataclass(frozen=True)
class SearchResult:
    conversation_id: str
    message_id: str
    title: str
    timestamp: str | None
    role: str
    model: str | None
    snippet: str
    rank: float
    provider_id: str = "chatgpt"


class SearchService:
    """Read-only lexical retrieval over the archive's SQLite FTS projection."""

    def __init__(self, store: ArchiveStore):
        self.store = store

    def search(
        self, query: str, *, conversation_id: str | None = None, role: str | None = None, limit: int = 20,
    ) -> list[SearchResult]:
        if not 1 <= limit <= 100:
            raise ValueError("Search limit must be between 1 and 100.")
        return [
            SearchResult(
                conversation_id=row["conversation_id"], message_id=row["message_id"], title=row["title"],
                timestamp=row["timestamp"], role=row["role"], model=row["model"],
                snippet=row["snippet"], rank=float(row["rank"]),
            )
            for row in self.store.index.search_messages(query, conversation_id=conversation_id, role=role, limit=limit)
        ]


class ArchiveService:
    """Service entry point for local clients; no browser or network access."""

    def __init__(self, store: ArchiveStore):
        self.store = store
        self.search = SearchService(store)
        self.history = HistoryService(store)


class HistoryService:
    """Read-only revision lookup and semantic comparison over canonical files."""

    def __init__(self, store: ArchiveStore):
        self.store = store

    def conversation(self, conversation_id: str) -> Conversation:
        row = self.store.index.get(conversation_id)
        if row is None:
            raise KeyError(f"Unknown conversation: {conversation_id}")
        return Conversation.model_validate_json(Path(row["json_path"]).read_text(encoding="utf-8"))

    def log(self, conversation_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("History limit must be between 1 and 100.")
        conversation = self.conversation(conversation_id)
        return sorted(revisions_for(self.store.root, conversation.canonical_conversation_id), key=lambda item: item["observed_at"], reverse=True)[:limit]

    def diff(self, conversation_id: str, left: str, right: str) -> dict[str, Any]:
        revisions = {item["revision_id"]: item for item in self.log(conversation_id, limit=100)}
        if left not in revisions or right not in revisions:
            raise KeyError("Revision is not present for this conversation.")
        before, after = revisions[left]["state"], revisions[right]["state"]
        before_messages = {item["id"]: item for item in before["messages"]}
        after_messages = {item["id"]: item for item in after["messages"]}
        shared = sorted(set(before_messages) & set(after_messages))
        changed = [identifier for identifier in shared if before_messages[identifier] != after_messages[identifier]]
        return {
            "title_changed": before["title"] != after["title"],
            "project_changed": before.get("project_id") != after.get("project_id"),
            "workspace_changed": before.get("workspace_id") != after.get("workspace_id"),
            "messages_added": sorted(set(after_messages) - set(before_messages)),
            "messages_removed": sorted(set(before_messages) - set(after_messages)),
            "messages_changed": changed,
        }

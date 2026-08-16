"""Reusable local archive services shared by present and future interfaces."""
from __future__ import annotations

from dataclasses import dataclass

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

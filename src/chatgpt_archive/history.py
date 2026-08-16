"""Portable, append-only revision objects for canonical conversations."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Conversation


REVISION_SCHEMA_VERSION = 1
_OBSERVATION_FIELDS = {
    "captured_at", "first_observed_at", "last_observed_at", "capture_status", "capture_method",
    "capture_notes", "visible_messages_complete", "conversation_tree_complete", "attachments_complete",
    "images_complete", "tool_content_complete", "rich_content_complete", "richer_branch_data_available",
    "unsupported_content_types", "source_url", "source_kind", "current_revision_id",
}


def meaningful_state(conversation: Conversation) -> dict[str, Any]:
    """Return the documented state that participates in a content revision."""
    value = conversation.model_dump(mode="json")
    for field in _OBSERVATION_FIELDS:
        value.pop(field, None)
    return value


def revision_id(conversation: Conversation) -> str:
    encoded = json.dumps(meaningful_state(conversation), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def revision_path(root: Path, conversation: Conversation, identifier: str | None = None) -> Path:
    return root / "revisions" / conversation.canonical_conversation_id / f"{identifier or revision_id(conversation)}.json"


def record_revision(root: Path, conversation: Conversation, parent_revision_id: str | None, atomic_json: Any) -> str:
    """Create an immutable revision before exposing it as the canonical current state."""
    identifier = revision_id(conversation)
    path = revision_path(root, conversation, identifier)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("revision_id") != identifier or existing.get("state") != meaningful_state(conversation):
            raise ValueError("Revision ID collision or corrupted immutable revision object.")
    else:
        atomic_json(path, {
            "schema_version": REVISION_SCHEMA_VERSION,
            "revision_id": identifier,
            "canonical_conversation_id": conversation.canonical_conversation_id,
            "parent_revision_id": parent_revision_id,
            "first_observed_at": (conversation.first_observed_at or datetime.now(timezone.utc)).isoformat(),
            "state": meaningful_state(conversation),
        })
    return identifier


def revisions_for(root: Path, canonical_conversation_id: str) -> list[dict[str, Any]]:
    directory = root / "revisions" / canonical_conversation_id
    if not directory.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]

"""Normalization for conversation mappings observed during ordinary browser navigation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import CaptureCompleteness, Conversation, Message


def normalize_mapping(payload: dict[str, Any], source_url: str) -> Conversation:
    """Convert a browser-observed mapping response without assuming undocumented fields."""
    mapping = payload.get("mapping")
    if not isinstance(mapping, dict):
        raise ValueError("Structured response did not contain a conversation mapping.")
    current = _current_branch(mapping, payload.get("current_node"))
    messages: list[Message] = []
    for node_id, node in mapping.items():
        if not isinstance(node, dict) or not isinstance(node.get("message"), dict):
            continue
        raw = node["message"]
        content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
        parts = content.get("parts", [])
        text = "\n".join(part for part in parts if isinstance(part, str))
        content_type = str(content.get("content_type") or "unknown")
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        messages.append(Message(
            id=str(raw.get("id") or node_id), parent_id=node.get("parent"), children=[str(item) for item in node.get("children", []) if isinstance(item, str)],
            sequence=0, branch="current" if node_id in current else "alternate",
            role=str((raw.get("author") or {}).get("role") or "unknown"), content_type=content_type,
            text=text, timestamp=_timestamp(raw.get("create_time")), model=metadata.get("model_slug"), metadata=metadata,
        ))
    messages.sort(key=lambda item: (item.branch != "current", item.timestamp or datetime.min.replace(tzinfo=timezone.utc), item.id))
    for sequence, message in enumerate(messages): message.sequence = sequence
    unsupported = sorted({message.content_type for message in messages if message.content_type not in {"text", "code"}})
    return Conversation(
        conversation_id=str(payload.get("conversation_id") or payload.get("id") or "unknown"), title=str(payload.get("title") or "Untitled conversation"), source_url=source_url,
        created_at=_timestamp(payload.get("create_time")), updated_at=_timestamp(payload.get("update_time")),
        capture_status=CaptureCompleteness.PARTIAL, capture_method="structured_browser_response",
        visible_messages_complete=False, conversation_tree_complete=True, richer_branch_data_available=True,
        capture_notes=["structured_browser_response", "binary_content_not_archived"], unsupported_content_types=unsupported,
        messages=messages,
    )


def _current_branch(mapping: dict[str, Any], current_node: object) -> set[str]:
    branch: set[str] = set(); node_id = current_node
    while isinstance(node_id, str) and node_id in mapping and node_id not in branch:
        branch.add(node_id)
        node = mapping[node_id]
        node_id = node.get("parent") if isinstance(node, dict) else None
    return branch


def _timestamp(value: object) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if isinstance(value, (int, float)) else None

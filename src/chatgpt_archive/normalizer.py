"""Normalize acquisition-specific visible turns into the versioned canonical model."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import Message


def normalize_visible_turns(conversation_id: str, turns: Iterable[dict[str, Any]]) -> list[Message]:
    """Keep useful partial turns while defaulting absent, non-sensitive metadata."""
    messages: list[Message] = []
    for index, turn in enumerate(turns):
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        messages.append(Message(
            id=str(turn.get("id") or f"{conversation_id}:{index}"),
            parent_id=turn.get("parent_id"), sequence=len(messages), role=str(turn.get("role") or "unknown"),
            content_type=str(turn.get("content_type") or "text"), text=text,
            model=turn.get("model"), metadata=dict(turn.get("metadata") or {}),
        ))
    return messages

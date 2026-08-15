from __future__ import annotations

from .models import Conversation


def render_conversation(conversation: Conversation) -> str:
    lines = [f"# {conversation.title}", "", f"Source: {conversation.source_url}", f"Captured: {conversation.captured_at.isoformat()}", ""]
    for message in sorted((item for item in conversation.messages if item.branch == "current"), key=lambda item: item.sequence):
        heading = message.role.capitalize() if message.role else "Unknown"
        # Canonical text is already normalized by the acquisition adapter. Do
        # not strip it here: trailing line breaks can be significant in code.
        lines.extend([f"## {heading}", "", message.text, ""])
    return "\n".join(lines)

from __future__ import annotations

from .models import Conversation


def render_conversation(conversation: Conversation) -> str:
    lines = [f"# {conversation.title}", "", f"Source: {conversation.source_url}", f"Captured: {conversation.captured_at.isoformat()}", ""]
    for message in sorted(conversation.messages, key=lambda item: item.sequence):
        heading = message.role.capitalize() if message.role else "Unknown"
        lines.extend([f"## {heading}", "", message.text.rstrip(), ""])
    return "\n".join(lines).rstrip() + "\n"

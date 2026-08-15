"""Extract visible message turns only; unsupported rich content is recorded as metadata."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .models import Conversation
from .normalizer import normalize_visible_turns


class ConversationAcquirer(Protocol):
    def fetch(self, source_url: str, conversation_id: str, title: str) -> Conversation: ...


MESSAGE_SELECTORS = (
    "[data-message-author-role]",
    "article [data-message-author-role]",
)


def extract_visible_conversation(page: object, conversation_id: str, title: str, source_url: str) -> Conversation:
    page.goto(source_url, wait_until="domcontentloaded")
    page.wait_for_timeout(800)  # allow streamed UI to settle; no network interception
    locator = None
    for selector in MESSAGE_SELECTORS:
        candidate = page.locator(selector)
        if candidate.count():
            locator = candidate
            break
    if locator is None:
        raise RuntimeError("No visible message elements found; ChatGPT DOM may have changed.")
    turns = []
    for sequence in range(locator.count()):
        turn = locator.nth(sequence)
        role = turn.get_attribute("data-message-author-role") or "unknown"
        text = turn.inner_text(timeout=2000).strip()
        if not text:
            continue
        turns.append({"id": f"{conversation_id}:{sequence}", "role": role, "text": text})
    messages = normalize_visible_turns(conversation_id, turns)
    if not messages:
        raise RuntimeError("Conversation contained no extractable visible text.")
    return Conversation(
        conversation_id=conversation_id, title=title, source_url=source_url,
        captured_at=datetime.now(timezone.utc), messages=messages,
        visible_messages_complete=True,
        capture_notes=["visible_messages_only", "current_branch_only", "attachments_unsupported", "rich_content_not_extracted"],
        unsupported_content_types=["attachments", "images", "tool_output", "regenerated_branches"],
    )


class PlaywrightAcquirer:
    def __init__(self, page: object):
        self.page = page

    def fetch(self, source_url: str, conversation_id: str, title: str) -> Conversation:
        return extract_visible_conversation(self.page, conversation_id, title, source_url)

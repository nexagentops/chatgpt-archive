from datetime import datetime, timezone

from chatgpt_archive.markdown import render_conversation
from chatgpt_archive.models import Conversation, Message
from chatgpt_archive.normalizer import normalize_visible_turns
from chatgpt_archive.extractor import MESSAGE_SELECTORS


def test_unknown_model_fields_are_retained_and_optional_fields_default() -> None:
    message = Message.model_validate({"id": "one", "sequence": 0, "role": "user", "future_field": "safe"})
    assert message.text == ""
    assert message.model_extra == {"future_field": "safe"}


def test_markdown_preserves_multiline_fenced_code() -> None:
    conversation = Conversation(
        conversation_id="abc", title="Code", source_url="https://chatgpt.com/c/abc",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        messages=[Message(id="1", sequence=0, role="user", text="show code"), Message(id="2", sequence=1, role="assistant", text="```python\nprint(1)\n```")],
    )
    output = render_conversation(conversation)
    assert "## User" in output and "## Assistant" in output
    assert "```python\nprint(1)\n```" in output


def test_normalizer_keeps_partial_turns_and_skips_empty_malformed_ones() -> None:
    messages = normalize_visible_turns("abc", [{"role": "user", "text": "hi"}, {"role": "assistant"}, {"text": "partial"}])
    assert [(message.sequence, message.role, message.text) for message in messages] == [(0, "user", "hi"), (1, "unknown", "partial")]


def test_extractor_prioritizes_message_role_attribute() -> None:
    assert MESSAGE_SELECTORS[0] == "[data-message-author-role]"

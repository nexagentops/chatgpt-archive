from pathlib import Path

from chatgpt_archive.history import revision_id, revisions_for
from chatgpt_archive.markdown import render_conversation
from chatgpt_archive.models import Conversation, Message
from chatgpt_archive.operations import verify
from chatgpt_archive.storage import ArchiveStore


def _conversation(title: str = "Original", text: str = "one", role: str = "user", project: str | None = None) -> Conversation:
    return Conversation(
        conversation_id="history-id", source_url="https://chatgpt.com/c/history-id", title=title, project_id=project,
        messages=[Message(id="m", sequence=0, role=role, text=text)],
    )


def test_first_revision_is_content_addressed_and_verified(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    conversation = _conversation()
    store.save_conversation(conversation, render_conversation(conversation))
    revisions = revisions_for(store.root, conversation.canonical_conversation_id)
    assert len(revisions) == 1
    assert revisions[0]["revision_id"] == revision_id(conversation)
    assert conversation.current_revision_id == revision_id(conversation)
    assert verify(store)["errors"] == 0


def test_identical_repeat_does_not_duplicate_revision_and_changes_link_parent(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    first = _conversation()
    store.save_conversation(first, "first")
    store.save_conversation(_conversation(), "same")
    assert len(revisions_for(store.root, first.canonical_conversation_id)) == 1
    changed = _conversation(title="Renamed", text="edited", role="assistant", project="project-a")
    store.save_conversation(changed, "changed")
    revisions = revisions_for(store.root, changed.canonical_conversation_id)
    assert len(revisions) == 2
    current = next(item for item in revisions if item["revision_id"] == changed.current_revision_id)
    assert current["parent_revision_id"] == first.current_revision_id


def test_observation_only_state_does_not_change_revision_digest() -> None:
    first = _conversation()
    later = _conversation()
    later.captured_at = later.captured_at.replace(year=2027)
    later.last_observed_at = later.captured_at
    assert revision_id(first) == revision_id(later)

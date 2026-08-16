from datetime import datetime, timezone

from chatgpt_archive.models import Conversation, Message, canonical_conversation_id
from chatgpt_archive.storage import ArchiveStore


def _conversation(**changes: object) -> Conversation:
    values: dict[str, object] = {
        "conversation_id": "provider-1", "source_url": "https://chatgpt.com/c/provider-1",
        "title": "Original", "messages": [Message(id="m", sequence=0, role="user", text="one")],
    }
    values.update(changes)
    return Conversation(**values)


def test_canonical_identity_is_stable_across_title_message_and_project_changes() -> None:
    first = _conversation()
    changed = _conversation(title="Renamed", project_id="project-a", messages=[Message(id="m", sequence=0, role="assistant", text="changed")])
    assert first.canonical_conversation_id == changed.canonical_conversation_id
    assert first.canonical_conversation_id == canonical_conversation_id("chatgpt", "provider-1")


def test_missing_provider_metadata_is_explicitly_nullable() -> None:
    conversation = _conversation()
    assert conversation.provider == "chatgpt"
    assert conversation.provider_account_id is None
    assert conversation.workspace_id is None
    assert conversation.project_id is None
    assert conversation.source_kind == "browser"


def test_save_preserves_first_observation_and_updates_last_observation(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    first = _conversation(captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    store.save_conversation(first, "first")
    second = _conversation(captured_at=datetime(2026, 1, 2, tzinfo=timezone.utc), title="Changed")
    store.save_conversation(second, "second")
    raw = next(store.raw_dir.glob("*.json"))
    loaded = Conversation.model_validate_json(raw.read_text())
    assert loaded.first_observed_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert loaded.last_observed_at == datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_identity_collision_fails_closed(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    store.save_conversation(_conversation(), "first")
    collision = _conversation(canonical_conversation_id="cc_different")
    try:
        store.save_conversation(collision, "second")
    except ValueError as error:
        assert "collision" in str(error)
    else:  # pragma: no cover - assertion path
        raise AssertionError("identity collision was accepted")

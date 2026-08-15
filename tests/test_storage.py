import json

from chatgpt_archive.markdown import render_conversation
from chatgpt_archive.models import CaptureCompleteness, CaptureStatus, Conversation, FailureRecord, ManifestEntry, Message
from chatgpt_archive.storage import ArchiveStore


def test_manifest_merge_preserves_completed_and_deduplicates(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "data")
    store.merge_discovery([ManifestEntry(conversation_id="a", title="Old", source_url="https://chatgpt.com/c/a")])
    store.mark_complete("a")
    manifest = store.merge_discovery([ManifestEntry(conversation_id="a", title="New", source_url="https://chatgpt.com/c/a")])
    assert len(manifest.entries) == 1
    assert manifest.entries[0].status == CaptureStatus.COMPLETED
    assert manifest.entries[0].title == "Old"


def test_atomic_conversation_write_creates_json_and_markdown(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "data")
    conversation = Conversation(conversation_id="safe-id", title="Test", source_url="https://chatgpt.com/c/safe-id", messages=[Message(id="m", sequence=0, role="user", text="hello")])
    store.save_conversation(conversation, render_conversation(conversation))
    raw = store.raw_dir / f"{store.filename_stem('safe-id')}.json"
    assert json.loads(raw.read_text())["conversation_id"] == "safe-id"
    assert (store.markdown_dir / f"{store.filename_stem('safe-id')}.md").read_text().endswith("hello\n")
    assert not list(store.raw_dir.glob("tmp*"))


def test_failed_entry_remains_resumable(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "data")
    store.merge_discovery([ManifestEntry(conversation_id="a", source_url="https://chatgpt.com/c/a")])
    store.mark_failed("a", "synthetic failure")
    entry = store.load_manifest().entries[0]
    assert entry.status == CaptureStatus.FAILED
    assert entry.error == "synthetic failure"


def test_failure_record_is_structured_and_persisted(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "data")
    store.merge_discovery([ManifestEntry(conversation_id="a", source_url="https://chatgpt.com/c/a")])
    store.record_failure(FailureRecord(conversation_id="a", source_url="https://chatgpt.com/c/a", stage="extract", category="TimeoutError", message="synthetic timeout"))
    failure = store.load_manifest().entries[0].failures[0]
    assert (failure.conversation_id, failure.stage, failure.category) == ("a", "extract", "TimeoutError")


def test_capture_completeness_is_explicit() -> None:
    conversation = Conversation(conversation_id="a", source_url="https://chatgpt.com/c/a")
    assert conversation.capture_status == CaptureCompleteness.PARTIAL
    assert "current_branch_only" in conversation.capture_notes


def test_filename_is_deterministic_and_cannot_escape_archive() -> None:
    stem = ArchiveStore.filename_stem("../../unsafe/id")
    assert "/" not in stem and ".." not in stem
    assert stem == ArchiveStore.filename_stem("../../unsafe/id")

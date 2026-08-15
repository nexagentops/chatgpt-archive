from pathlib import Path

from chatgpt_archive.markdown import render_conversation
from chatgpt_archive.models import Conversation, Message
from chatgpt_archive.operations import backup, export_csv, reindex, verify
from chatgpt_archive.storage import ArchiveStore


def conversation() -> Conversation:
    return Conversation(
        conversation_id="csv-id", title='Comma, quote " and emoji 😀', source_url="https://chatgpt.com/c/csv-id",
        messages=[Message(id="one", sequence=0, role="user", text='line one\n"quoted", text'), Message(id="two", parent_id="one", sequence=1, role="assistant", text="reply")],
    )


def test_index_export_and_verify_round_trip(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    item = conversation()
    store.save_conversation(item, render_conversation(item))
    assert store.index.totals() == {"conversations": 1, "messages": 2}
    assert export_csv(store) == {"conversations": 1, "messages": 2}
    assert '"line one\n""quoted"", text"' in (store.root / "exports" / "messages.csv").read_text(encoding="utf-8")
    assert verify(store)["errors"] == 0


def test_reindex_recovers_operational_index_from_canonical_json(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    item = conversation()
    store.save_conversation(item, render_conversation(item))
    store.index.path.unlink()
    assert reindex(store) == 1
    assert verify(store)["errors"] == 0


def test_verify_detects_broken_parent(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    item = conversation()
    item.messages[1].parent_id = "missing"
    store.save_conversation(item, render_conversation(item))
    assert verify(store)["broken_parents"] == 1


def test_backup_excludes_browser_state_and_preserves_archive(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    item = conversation(); store.save_conversation(item, render_conversation(item))
    target = backup(store, tmp_path / "backup")
    assert (target / "raw").exists() and (target / "archive.db").exists()
    assert not (target / ".playwright-profile").exists()

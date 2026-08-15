from pathlib import Path

from chatgpt_archive.markdown import render_conversation
from chatgpt_archive.models import Conversation, ManifestEntry, Message
from chatgpt_archive.operations import backup, export_csv, migrate, reindex, verify
from chatgpt_archive.storage import ArchiveStore
from chatgpt_archive.models import FailureRecord


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
    item = conversation(); store.merge_discovery([ManifestEntry(conversation_id=item.conversation_id, title=item.title, source_url=item.source_url)]); store.save_conversation(item, render_conversation(item)); store.mark_complete(item.conversation_id)
    target = backup(store, tmp_path / "backup")
    assert (target / "raw").exists() and (target / "archive.db").exists()
    assert not (target / ".playwright-profile").exists()


def test_explicit_v1_to_v2_migration_is_idempotent(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    item = conversation(); item.schema_version = 1
    store.save_conversation(item, render_conversation(item))
    assert migrate(store) == 1
    assert migrate(store) == 0
    assert next(iter(__import__("chatgpt_archive.operations", fromlist=["conversations"]).conversations(store)))[1].schema_version == 2


def test_sync_run_metrics_are_persisted(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    run_id = store.index.start_run(10, 4)
    store.index.finish_run(run_id, "completed", archived=3, structured_count=2, dom_count=1, peak_rss_mb=12.5)
    with store.index.connect() as connection:
        row = connection.execute("SELECT * FROM sync_runs WHERE run_id=?", (run_id,)).fetchone()
    assert (row["archived"], row["structured_count"], row["dom_count"], row["peak_rss_mb"]) == (3, 2, 1, 12.5)


def test_failed_changed_candidate_preserves_previous_good_archive(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    item = conversation()
    store.merge_discovery([ManifestEntry(conversation_id=item.conversation_id, title=item.title, source_url=item.source_url)])
    store.save_conversation(item, render_conversation(item)); store.mark_complete(item.conversation_id)
    raw = store.raw_dir / f"{store.filename_stem(item.conversation_id)}.json"
    previous_bytes = raw.read_bytes(); previous_hash = store.index.get(item.conversation_id)["content_hash"]
    store.record_failure(FailureRecord(conversation_id=item.conversation_id, stage="normalize", category="ValueError", message="synthetic changed candidate failure"))
    assert raw.read_bytes() == previous_bytes
    assert store.index.get(item.conversation_id)["content_hash"] == previous_hash
    assert store.load_manifest().entries[0].failures[-1].category == "ValueError"

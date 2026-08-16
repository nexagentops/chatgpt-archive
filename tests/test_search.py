from pathlib import Path
import sqlite3

import pytest
from typer.testing import CliRunner

from chatgpt_archive.cli import app
from chatgpt_archive.markdown import render_conversation
from chatgpt_archive.models import Conversation, Message
from chatgpt_archive.operations import reindex, verify
from chatgpt_archive.services import ArchiveService
from chatgpt_archive.storage import ArchiveStore


def _store(tmp_path: Path) -> ArchiveStore:
    store = ArchiveStore(tmp_path / "archive")
    store.save_conversation(
        Conversation(
            conversation_id="unicode-code", title="Möbius retrieval", source_url="https://chatgpt.com/c/unicode-code",
            messages=[
                Message(id="u", sequence=0, role="user", text="Need mixture of experts for café search."),
                Message(id="a", sequence=1, role="assistant", text="```python\n# mixture of experts\nprint('café')\n```"),
            ],
        ),
        "placeholder",
    )
    store.save_conversation(
        Conversation(
            conversation_id="long", title="Long archive", source_url="https://chatgpt.com/c/long",
            messages=[Message(id="l", sequence=0, role="assistant", text=("prefix " * 2_000) + "needle")],
        ),
        "placeholder",
    )
    return store


def test_search_service_returns_unicode_code_and_filtered_results(tmp_path: Path) -> None:
    service = ArchiveService(_store(tmp_path)).search
    assert [result.message_id for result in service.search("mixture experts")] == ["a", "u"]
    assert [result.message_id for result in service.search("café", role="assistant")] == ["a"]
    assert [result.message_id for result in service.search("needle", conversation_id="long")] == ["l"]


def test_search_query_is_bounded_and_rejects_empty_input(tmp_path: Path) -> None:
    service = ArchiveService(_store(tmp_path)).search
    with pytest.raises(ValueError, match="non-whitespace"):
        service.search("   ")
    with pytest.raises(ValueError, match="between 1 and 100"):
        service.search("needle", limit=101)


def test_reindex_populates_fts_for_preexisting_archive(tmp_path: Path) -> None:
    store = ArchiveStore(tmp_path / "archive")
    item = Conversation(
        conversation_id="old", title="Old", source_url="https://chatgpt.com/c/old",
        messages=[Message(id="m", sequence=0, role="assistant", text="historical needle")],
    )
    store.save_conversation(item, render_conversation(item))
    with store.index.connect() as connection:
        connection.execute("DELETE FROM message_fts")
    assert ArchiveService(store).search.search("needle") == []
    assert verify(store)["search_index"] == 1
    assert reindex(store) == 1
    assert [result.message_id for result in ArchiveService(store).search.search("needle")] == ["m"]


def test_v1_operational_index_migrates_to_fts_schema_without_archive_rewrite(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    connection = sqlite3.connect(root / "archive.db")
    connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    connection.execute("INSERT INTO schema_migrations VALUES (1, '2026-01-01T00:00:00+00:00')")
    connection.commit()
    connection.close()
    store = ArchiveStore(root)
    store.initialize()
    with store.index.connect() as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='message_fts'").fetchone()[0] == "message_fts"


def test_cli_search_is_a_thin_local_service_client(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = CliRunner().invoke(app, ["search", "needle", "--data-dir", str(store.root)])
    assert result.exit_code == 0
    assert "conversation_id=long message_id=l provider=chatgpt" in result.stdout

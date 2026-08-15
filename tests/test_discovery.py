from chatgpt_archive.discovery import SELECTORS, _history_entry, _structured_history, conversation_id_from_url, normalize_links


def test_duplicate_links_become_one_manifest_entry() -> None:
    entries = normalize_links(
        [("/c/a-1", "First"), ("https://chatgpt.com/c/a-1", "Duplicate"), ("/c/b-2", "Second")],
        "https://chatgpt.com/",
    )
    assert [entry.conversation_id for entry in entries] == ["a-1", "b-2"]


def test_non_conversation_urls_are_ignored() -> None:
    assert conversation_id_from_url("https://chatgpt.com/share/abc") is None
    assert normalize_links([( "/", "Home")], "https://chatgpt.com/") == []


def test_normalized_entries_can_be_bounded() -> None:
    entries = normalize_links([(f"/c/{index}", str(index)) for index in range(3)], "https://chatgpt.com/")
    assert [entry.conversation_id for entry in entries[:2]] == ["0", "1"]


def test_sidebar_selector_excludes_attachment_navigation() -> None:
    assert "nav[aria-label='Sidebar']" in SELECTORS.sidebar_scroll_container
    assert "nav[aria-label]" not in SELECTORS.sidebar_scroll_container


def test_structured_history_entry_preserves_stable_metadata() -> None:
    entry = _history_entry({"id": "stable", "title": "Synthetic", "create_time": 1, "update_time": 2})
    assert entry and (entry.conversation_id, entry.source_method, entry.source_url) == ("stable", "structured_history", "https://chatgpt.com/c/stable")


def test_structured_history_paginates_and_persists_each_batch() -> None:
    class Page:
        def evaluate(self, _script: str, _url: str) -> dict:
            return {"status": 200, "payload": {"items": [{"id": "c", "title": "C"}], "total": 3, "offset": 2, "limit": 2}}

    persisted: list[list[str]] = []
    result = _structured_history(
        Page(), "https://chatgpt.com/backend-api/conversation?offset=0&limit=2",
        {"items": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}], "total": 3, "offset": 0, "limit": 2},
        None, lambda entries: persisted.append([entry.conversation_id for entry in entries]),
    )
    assert ([entry.conversation_id for entry in result.entries], result.complete, result.termination_reason, result.batches) == (["a", "b", "c"], True, "history_exhausted", 2)
    assert persisted == [["a", "b"], ["c"]]

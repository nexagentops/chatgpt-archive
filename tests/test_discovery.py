from chatgpt_archive.discovery import conversation_id_from_url, normalize_links


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

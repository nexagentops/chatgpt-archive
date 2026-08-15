from chatgpt_archive.structured import normalize_mapping


def test_normalizes_mapping_with_current_and_alternate_branches() -> None:
    payload = {"id": "c", "title": "Synthetic", "current_node": "b", "mapping": {
        "root": {"parent": None, "children": ["a"], "message": None},
        "a": {"parent": "root", "children": ["b", "alt"], "message": {"id": "a", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hello"]}, "create_time": 1}},
        "b": {"parent": "a", "children": [], "message": {"id": "b", "author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["answer"]}, "create_time": 2}},
        "alt": {"parent": "a", "children": [], "message": {"id": "alt", "author": {"role": "assistant"}, "content": {"content_type": "code", "parts": ["other"]}, "create_time": 3}},
    }}
    conversation = normalize_mapping(payload, "https://chatgpt.com/c/c")
    assert conversation.capture_method == "structured_browser_response"
    assert conversation.conversation_tree_complete and conversation.richer_branch_data_available
    assert [(item.id, item.branch, item.parent_id) for item in conversation.messages] == [("a", "current", "root"), ("b", "current", "a"), ("alt", "alternate", "a")]

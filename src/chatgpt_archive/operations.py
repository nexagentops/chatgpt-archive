"""Derived exports and integrity checks over canonical JSON archives."""
from __future__ import annotations

import csv
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable

from .models import Conversation
from .storage import ArchiveStore
from .markdown import render_conversation


def conversations(store: ArchiveStore) -> Iterable[tuple[Path, Conversation]]:
    for path in sorted(store.raw_dir.glob("*.json")):
        yield path, Conversation.model_validate_json(path.read_text(encoding="utf-8"))


def reindex(store: ArchiveStore) -> int:
    count = 0
    for path, conversation in conversations(store):
        markdown = store.markdown_dir / f"{path.stem}.md"
        store.index.upsert(conversation, path, markdown, store.content_hash(conversation))
        count += 1
    return count


def render_markdown(store: ArchiveStore) -> int:
    """Regenerate derived Markdown without changing canonical JSON or SQLite."""
    count = 0
    for path, conversation in conversations(store):
        target = store.markdown_dir / f"{path.stem}.md"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as tmp:
            tmp.write(render_conversation(conversation))
            name = tmp.name
        os.replace(name, target)
        count += 1
    return count


def migrate(store: ArchiveStore, target_version: int = 3) -> int:
    """Explicit, per-file atomic migration to the supported canonical schema."""
    migrated = 0
    for path, conversation in conversations(store):
        if conversation.schema_version == target_version:
            continue
        if conversation.schema_version not in {1, 2} or target_version != 3:
            raise ValueError(f"Unsupported archive schema migration: {conversation.schema_version} -> {target_version}")
        conversation.schema_version = 3
        store._atomic_json(path, conversation.model_dump(mode="json"))
        markdown_path = store.markdown_dir / f"{path.stem}.md"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=markdown_path.parent, delete=False) as tmp:
            tmp.write(render_conversation(conversation)); name = tmp.name
        os.replace(name, markdown_path)
        migrated += 1
    reindex(store)
    return migrated


def export_csv(store: ArchiveStore) -> dict[str, int]:
    exports = store.root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    conversation_fields = ["conversation_id", "title", "created_at", "updated_at", "captured_at", "capture_status", "capture_method", "message_count", "user_message_count", "assistant_message_count", "has_branches", "branch_count", "has_attachments", "has_images", "has_tool_content", "json_path", "markdown_path", "schema_version", "content_hash"]
    message_fields = ["conversation_id", "message_id", "parent_id", "sequence", "branch", "role", "timestamp", "model", "content_type", "text", "has_attachment", "has_tool_content"]
    conv_count = message_count = 0
    with _atomic_csv(exports / "conversations.csv", conversation_fields) as conv_writer, _atomic_csv(exports / "messages.csv", message_fields) as msg_writer:
        for path, conversation in conversations(store):
            messages = conversation.messages
            conv_writer.writerow({"conversation_id": conversation.conversation_id, "title": conversation.title, "created_at": conversation.created_at, "updated_at": conversation.updated_at, "captured_at": conversation.captured_at, "capture_status": conversation.capture_status.value, "capture_method": conversation.capture_method, "message_count": len(messages), "user_message_count": sum(item.role == "user" for item in messages), "assistant_message_count": sum(item.role == "assistant" for item in messages), "has_branches": any(item.branch != "current" for item in messages), "branch_count": len({item.branch for item in messages}), "has_attachments": any(item.attachments for item in messages), "has_images": "images" in conversation.unsupported_content_types, "has_tool_content": any(item.content_type == "tool" for item in messages), "json_path": str(path), "markdown_path": str(store.markdown_dir / f"{path.stem}.md"), "schema_version": conversation.schema_version, "content_hash": store.content_hash(conversation)})
            conv_count += 1
            for message in messages:
                msg_writer.writerow({"conversation_id": conversation.conversation_id, "message_id": message.id, "parent_id": message.parent_id, "sequence": message.sequence, "branch": message.branch, "role": message.role, "timestamp": message.timestamp, "model": message.model, "content_type": message.content_type, "text": message.text, "has_attachment": bool(message.attachments), "has_tool_content": message.content_type == "tool"})
                message_count += 1
    return {"conversations": conv_count, "messages": message_count}


class _atomic_csv:
    def __init__(self, path: Path, fields: list[str]): self.path, self.fields = path, fields
    def __enter__(self):
        self.tmp = tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=self.path.parent, delete=False)
        self.writer = csv.DictWriter(self.tmp, fieldnames=self.fields, lineterminator="\n")
        self.writer.writeheader()
        return self.writer
    def __exit__(self, *args):
        self.tmp.close()
        if args[0] is None: os.replace(self.tmp.name, self.path)
        else: Path(self.tmp.name).unlink(missing_ok=True)


def verify(store: ArchiveStore) -> dict[str, int]:
    errors = Counter()
    seen: set[str] = set()
    count = 0
    indexed = {row["conversation_id"]: row for row in store.index.rows()}
    raw_ids: set[str] = set()
    expected_csv_conversations: dict[str, tuple[str, str]] = {}
    expected_csv_messages: dict[tuple[str, str], str] = {}
    for path, conversation in conversations(store):
        count += 1; raw_ids.add(conversation.conversation_id)
        if conversation.conversation_id in seen: errors["duplicate_ids"] += 1
        seen.add(conversation.conversation_id)
        ids = [message.id for message in conversation.messages]
        if len(ids) != len(set(ids)): errors["duplicate_message_ids"] += 1
        if [message.sequence for message in conversation.messages] != list(range(len(conversation.messages))): errors["ordering"] += 1
        if any(message.parent_id and message.parent_id not in ids for message in conversation.messages): errors["broken_parents"] += 1
        if not (store.markdown_dir / f"{path.stem}.md").exists(): errors["missing_markdown"] += 1
        row = indexed.get(conversation.conversation_id)
        if row is None: errors["missing_index"] += 1
        elif row["content_hash"] != store.content_hash(conversation): errors["hash_errors"] += 1
        expected_csv_conversations[conversation.conversation_id] = (conversation.title, store.content_hash(conversation))
        for message in conversation.messages:
            expected_csv_messages[(conversation.conversation_id, message.id)] = message.text
            fts_rows = store.index.fts_rows(conversation.conversation_id, message.id)
            if len(fts_rows) != 1 or fts_rows[0]["title"] != conversation.title or fts_rows[0]["text"] != message.text:
                errors["search_index"] += 1
    errors["orphan_index"] = len(set(indexed) - raw_ids)
    errors["orphan_files"] = len(list(store.raw_dir.glob("*.json"))) - count
    _verify_csv_exports(store, expected_csv_conversations, expected_csv_messages, errors)
    return {"conversations": count, **dict(errors), "errors": sum(errors.values())}


def _verify_csv_exports(
    store: ArchiveStore, expected_conversations: dict[str, tuple[str, str]],
    expected_messages: dict[tuple[str, str], str], errors: Counter[str],
) -> None:
    """Check derived CSV rows when exports have been generated locally."""
    conversations_csv = store.root / "exports" / "conversations.csv"
    messages_csv = store.root / "exports" / "messages.csv"
    if not conversations_csv.exists() and not messages_csv.exists():
        return
    if not conversations_csv.exists() or not messages_csv.exists():
        errors["missing_csv"] += 1
        return
    try:
        with conversations_csv.open(encoding="utf-8", newline="") as source:
            conversation_rows = list(csv.DictReader(source))
        with messages_csv.open(encoding="utf-8", newline="") as source:
            message_rows = list(csv.DictReader(source))
    except (OSError, csv.Error, UnicodeError):
        errors["invalid_csv"] += 1
        return
    actual_conversations = {row.get("conversation_id", ""): (row.get("title", ""), row.get("content_hash", "")) for row in conversation_rows}
    actual_messages = {(row.get("conversation_id", ""), row.get("message_id", "")): row.get("text", "") for row in message_rows}
    if len(actual_conversations) != len(conversation_rows) or actual_conversations != expected_conversations:
        errors["csv_conversations"] += 1
    if len(actual_messages) != len(message_rows) or actual_messages != expected_messages:
        errors["csv_messages"] += 1


def backup(store: ArchiveStore, destination: Path) -> Path:
    if destination.exists(): raise FileExistsError("Backup destination must not already exist.")
    destination.mkdir(parents=True)
    for name in ("raw", "markdown", "manifest.json", "archive.db", "exports"):
        source = store.root / name
        if source.is_dir(): shutil.copytree(source, destination / name)
        elif source.exists(): shutil.copy2(source, destination / name)
    return destination

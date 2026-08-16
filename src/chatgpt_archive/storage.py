from __future__ import annotations

import json
import os
import hashlib
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .index import ArchiveIndex
from .models import CaptureStatus, Conversation, FailureRecord, Manifest, ManifestEntry


class ArchiveStore:
    """Filesystem persistence. All writes replace targets atomically."""

    def __init__(self, root: Path):
        self.root = root
        self.raw_dir = root / "raw"
        self.markdown_dir = root / "markdown"
        self.manifest_path = root / "manifest.json"
        self.index = ArchiveIndex(root / "archive.db")

    def initialize(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.index.initialize()

    @staticmethod
    def content_hash(conversation: Conversation) -> str:
        """Hash meaningful current state while excluding observation-only timestamps."""
        value = conversation.model_dump(mode="json")
        for key in ("captured_at", "first_observed_at", "last_observed_at"):
            value.pop(key, None)
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _atomic_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            json.dump(value, tmp, indent=2, ensure_ascii=False, default=str)
            tmp.write("\n")
            temp_name = tmp.name
        os.replace(temp_name, path)

    def load_manifest(self) -> Manifest:
        if not self.manifest_path.exists():
            return Manifest()
        return Manifest.model_validate_json(self.manifest_path.read_text(encoding="utf-8"))

    def save_manifest(self, manifest: Manifest) -> None:
        self.initialize()
        self._atomic_json(self.manifest_path, manifest.model_dump(mode="json"))

    def merge_discovery(self, entries: list[ManifestEntry]) -> Manifest:
        manifest = self.load_manifest()
        indexed = {entry.conversation_id: entry for entry in manifest.entries}
        for entry in entries:
            existing = indexed.get(entry.conversation_id)
            if existing is None:
                manifest.entries.append(entry)
                indexed[entry.conversation_id] = entry
            elif existing.status != CaptureStatus.COMPLETED:
                existing.title, existing.source_url = entry.title, entry.source_url
        self.save_manifest(manifest)
        return manifest

    def save_conversation(self, conversation: Conversation, markdown: str) -> None:
        self.initialize()
        stem = self.filename_stem(conversation.conversation_id)
        raw_path = self.raw_dir / f"{stem}.json"
        if raw_path.exists():
            existing = Conversation.model_validate_json(raw_path.read_text(encoding="utf-8"))
            if existing.canonical_conversation_id != conversation.canonical_conversation_id:
                raise ValueError("Provider conversation ID collision maps to a different canonical conversation ID.")
            conversation.first_observed_at = existing.first_observed_at
        self._atomic_json(raw_path, conversation.model_dump(mode="json"))
        target = self.markdown_dir / f"{stem}.md"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as tmp:
            tmp.write(markdown)
            temp_name = tmp.name
        os.replace(temp_name, target)
        self.index.upsert(conversation, raw_path, target, self.content_hash(conversation))

    @staticmethod
    def filename_stem(conversation_id: str) -> str:
        """Keep IDs recognizable while preventing URL-derived path traversal."""
        visible = re.sub(r"[^A-Za-z0-9._-]+", "-", conversation_id).strip(".-")[:96] or "conversation"
        suffix = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:12]
        return f"{visible}-{suffix}"

    def mark_complete(self, conversation_id: str) -> None:
        manifest = self.load_manifest()
        for entry in manifest.entries:
            if entry.conversation_id == conversation_id:
                entry.status, entry.error = CaptureStatus.COMPLETED, None
                entry.completed_at = datetime.now(timezone.utc)
        manifest.last_synchronization_at = datetime.now(timezone.utc)
        self.save_manifest(manifest)

    def mark_failed(self, conversation_id: str, error: str) -> None:
        self.record_failure(FailureRecord(conversation_id=conversation_id, stage="unknown", category="unknown", message=error))

    def record_failure(self, failure: FailureRecord) -> None:
        manifest = self.load_manifest()
        for entry in manifest.entries:
            if entry.conversation_id == failure.conversation_id:
                entry.status, entry.error = CaptureStatus.FAILED, failure.message[:1000]
                entry.failures.append(failure)
        manifest.last_synchronization_at = datetime.now(timezone.utc)
        self.save_manifest(manifest)

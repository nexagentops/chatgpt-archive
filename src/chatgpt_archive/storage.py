from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .models import CaptureStatus, Conversation, Manifest, ManifestEntry


class ArchiveStore:
    """Filesystem persistence. All writes replace targets atomically."""

    def __init__(self, root: Path):
        self.root = root
        self.raw_dir = root / "raw"
        self.markdown_dir = root / "markdown"
        self.manifest_path = root / "manifest.json"

    def initialize(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

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
        stem = conversation.conversation_id
        self._atomic_json(self.raw_dir / f"{stem}.json", conversation.model_dump(mode="json"))
        target = self.markdown_dir / f"{stem}.md"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as tmp:
            tmp.write(markdown)
            temp_name = tmp.name
        os.replace(temp_name, target)

    def mark_complete(self, conversation_id: str) -> None:
        manifest = self.load_manifest()
        for entry in manifest.entries:
            if entry.conversation_id == conversation_id:
                entry.status, entry.error = CaptureStatus.COMPLETED, None
                entry.completed_at = datetime.now(timezone.utc)
        manifest.last_synchronization_at = datetime.now(timezone.utc)
        self.save_manifest(manifest)

    def mark_failed(self, conversation_id: str, error: str) -> None:
        manifest = self.load_manifest()
        for entry in manifest.entries:
            if entry.conversation_id == conversation_id:
                entry.status, entry.error = CaptureStatus.FAILED, error[:1000]
        manifest.last_synchronization_at = datetime.now(timezone.utc)
        self.save_manifest(manifest)

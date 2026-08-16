from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaptureStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class CaptureCompleteness(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    FAILED = "failed"


class Attachment(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    url: str | None = None
    content_type: str | None = None
    available: bool | None = None
    binary_archived: bool = False


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    parent_id: str | None = None
    children: list[str] = Field(default_factory=list)
    branch: str = "current"
    sequence: int
    role: str
    content_type: str = "text"
    text: str = ""
    timestamp: datetime | None = None
    model: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conversation(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: int = 3
    conversation_id: str
    canonical_conversation_id: str | None = None
    provider: str = "chatgpt"
    provider_conversation_id: str | None = None
    provider_account_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    source_kind: str = "browser"
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    current_revision_id: str | None = None
    title: str = "Untitled conversation"
    source_url: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    capture_status: CaptureCompleteness = CaptureCompleteness.PARTIAL
    capture_method: str = "dom"
    capture_notes: list[str] = Field(default_factory=lambda: ["current_branch_only", "attachments_unsupported"])
    visible_messages_complete: bool = False
    conversation_tree_complete: bool = False
    attachments_complete: bool = False
    images_complete: bool = False
    tool_content_complete: bool = False
    rich_content_complete: bool = False
    richer_branch_data_available: bool = False
    unsupported_content_types: list[str] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)

    @model_validator(mode="after")
    def establish_identity(self) -> "Conversation":
        """Fill legacy records deterministically without inventing provider metadata."""
        self.provider_conversation_id = self.provider_conversation_id or self.conversation_id
        self.canonical_conversation_id = self.canonical_conversation_id or canonical_conversation_id(
            self.provider, self.provider_conversation_id,
        )
        self.first_observed_at = self.first_observed_at or self.captured_at
        self.last_observed_at = self.last_observed_at or self.captured_at
        return self


def canonical_conversation_id(provider: str, provider_conversation_id: str) -> str:
    """Stable archive identity; account/project metadata intentionally cannot change it."""
    identity = f"chatgpt-archive:conversation:v1\0{provider}\0{provider_conversation_id}".encode("utf-8")
    return f"cc_{hashlib.sha256(identity).hexdigest()}"


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    conversation_id: str
    title: str = "Untitled conversation"
    source_url: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source_method: str = "sidebar_dom"
    status: CaptureStatus = CaptureStatus.PENDING
    error: str | None = None
    failures: list["FailureRecord"] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class Manifest(BaseModel):
    schema_version: int = 1
    entries: list[ManifestEntry] = Field(default_factory=list)
    last_synchronization_at: datetime | None = None


class FailureRecord(BaseModel):
    conversation_id: str
    source_url: str | None = None
    stage: str
    category: str
    message: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    debug_artifacts: list[str] = Field(default_factory=list)

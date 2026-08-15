from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CaptureStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class Attachment(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    url: str | None = None
    content_type: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    parent_id: str | None = None
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
    schema_version: int = 1
    conversation_id: str
    title: str = "Untitled conversation"
    source_url: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    capture_status: CaptureStatus = CaptureStatus.COMPLETED
    messages: list[Message] = Field(default_factory=list)


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    conversation_id: str
    title: str = "Untitled conversation"
    source_url: str
    status: CaptureStatus = CaptureStatus.PENDING
    error: str | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class Manifest(BaseModel):
    schema_version: int = 1
    entries: list[ManifestEntry] = Field(default_factory=list)
    last_synchronization_at: datetime | None = None

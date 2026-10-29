"""Projects and project memory."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, computed_field

from api_service.schemas.base import Model
from core.config import get_settings
from core.memory.service import Section


class ProjectCreate(Model):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    system_prompt: str = Field("", max_length=8000)
    code_level: int | None = Field(None, ge=1, le=4)


class ProjectUpdate(Model):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = Field(None, max_length=8000)
    code_level: int | None = Field(None, ge=1, le=4)


class ProjectRead(Model):
    id: str
    name: str
    description: str
    system_prompt: str
    code_level: int | None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def effective_code_level(self) -> int:
        """The level that applies: this project's, else the service default."""
        return self.code_level or get_settings().default_code_level


MemorySectionName = Section


class MemoryLine(Model):
    id: str
    text: str
    author: Literal["user", "agent"]
    updated_at: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


class MemorySection(Model):
    section: Section
    title: str
    content: str = Field(description="Markdown body (lines joined by \\n)")
    lines: list[MemoryLine] = Field(description="the body line by line")
    version: int = Field(description="0 = never written")
    updated_at: str | None
    max_chars: int


class MemoryRead(Model):
    sections: list[MemorySection] = Field(
        description="overview, preferences, core_interests, key_events"
    )


class MemorySectionWrite(Model):
    content: str = Field(
        description="whole body; '# ' and '## ' headings are refused"
    )
    expected_version: int = Field(ge=0)


class MemoryRevert(Model):
    history_id: int = Field(description="id of the change to undo")
    expected_version: int | None = Field(None, ge=0)


class MemoryHistoryActor(Model):
    type: Literal["user", "agent"]
    id: str


class MemoryHistoryEntry(Model):
    id: int
    section: Section
    action: str = Field(description="update | delete | revert | migrate")
    before: str
    after: str
    version: int | None
    actor: MemoryHistoryActor
    session_id: str | None
    run_id: str | None
    created_at: datetime


class MemoryHistoryRead(Model):
    items: list[MemoryHistoryEntry] = Field(description="newest first")

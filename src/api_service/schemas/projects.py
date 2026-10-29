"""Projects and project memory."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, computed_field

from api_service.schemas.base import Model
from core.config import get_settings
from core.memory.service import (
    DESCRIPTION_MAX_CHARS,
    MAX_TOPICS,
    MIN_TOPIC_CHARS,
    TITLE_MAX_CHARS,
)


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


class MemoryLine(Model):
    id: str
    text: str
    author: Literal["user", "agent"]
    updated_at: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


class MemoryTopic(Model):
    id: str = Field(description="stable; content stays attached to it")
    title: str
    description: str = Field(description="one line; guides what goes here")
    max_chars: int


class MemoryTopicWrite(Model):
    id: str | None = Field(
        None, description="an existing topic's id (edit); none = new topic"
    )
    title: str = Field(description=f"1-{TITLE_MAX_CHARS} characters")
    description: str = Field(
        "", description=f"at most {DESCRIPTION_MAX_CHARS} characters"
    )
    max_chars: int = Field(description=f"at least {MIN_TOPIC_CHARS}")
    replace: bool = Field(
        False,
        description="with an id: a new topic in its place; the old body "
        "is cleared (restorable from history)",
    )


class MemoryTopicsWrite(Model):
    topics: list[MemoryTopicWrite] = Field(
        description=f"the whole list in order, 1-{MAX_TOPICS} topics; "
        "a dropped topic's body is cleared (restorable from history)"
    )
    expected_version: int = Field(ge=0)


class MemoryTopicsRead(Model):
    topics: list[MemoryTopic]
    version: int = Field(description="0 = the defaults, never edited")
    updated_at: str | None
    total_max_chars: int = Field(
        description="the topics' max_chars add up to at most this"
    )


class MemoryTopicContent(Model):
    topic: str = Field(description="topic id")
    title: str
    description: str
    max_chars: int
    content: str = Field(description="Markdown body (lines joined by \\n)")
    lines: list[MemoryLine] = Field(description="the body line by line")
    version: int = Field(description="0 = never written")
    updated_at: str | None


class MemoryRead(Model):
    topics: list[MemoryTopicContent] = Field(description="in topic order")
    topics_version: int
    total_max_chars: int


class MemoryContentWrite(Model):
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
    topic: str = Field(description="topic id")
    title: str | None = Field(description="the topic's title at the time")
    action: str = Field(
        description="update | delete | revert | migrate | topic_removed | "
        "topic_replaced | topic_restored"
    )
    before: str
    after: str
    version: int | None
    replaced_by: str | None = Field(
        None, description="topic_replaced: the id of the new topic"
    )
    actor: MemoryHistoryActor
    session_id: str | None
    run_id: str | None
    created_at: datetime


class MemoryHistoryRead(Model):
    items: list[MemoryHistoryEntry] = Field(description="newest first")

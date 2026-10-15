"""Sessions, turns (runs), messages and run events."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, computed_field, model_validator

from api_service.schemas.base import Model
from core.config import get_settings


class TextBlock(Model):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=20000)


class ImageBlock(Model):
    type: Literal["image"]
    base64: str = Field(min_length=1)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    name: str | None = Field(None, max_length=255)


ContentBlock = Annotated[TextBlock | ImageBlock, Field(discriminator="type")]


class RunInput(Model):
    """A user turn: text, or LangChain content blocks (text + images)."""

    content: str | list[ContentBlock] = Field(
        description="문자열, 또는 [{type: text, text}, {type: image, base64, "
        "mime_type, name?}] 블록 목록"
    )

    @model_validator(mode="after")
    def _text(self) -> "RunInput":
        text = self.text
        if not text.strip():
            raise ValueError("content needs text")
        if len(text) > 20000:
            raise ValueError("text is longer than 20000 characters")
        return self

    @property
    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "\n".join(
            b.text for b in self.content if isinstance(b, TextBlock)
        )

    @property
    def images(self) -> list[ImageBlock]:
        if isinstance(self.content, str):
            return []
        return [b for b in self.content if isinstance(b, ImageBlock)]


class Resume(Model):
    interrupt_id: str
    value: Any


class RunCommand(Model):
    resume: Resume


class RunCreate(Model):
    """Exactly one of ``input`` (new turn) and ``command`` (resume)."""

    input: RunInput | None = None
    command: RunCommand | None = None
    model: str | None = Field(None, description="GET /models 의 name")

    @model_validator(mode="after")
    def _one(self) -> "RunCreate":
        if (self.input is None) == (self.command is None):
            raise ValueError("send exactly one of input and command")
        if self.command is not None and self.model is not None:
            raise ValueError("model is only for a new turn")
        return self


class SessionCreate(Model):
    title: str | None = Field(None, max_length=200)
    code_level: int | None = Field(None, ge=1, le=4)
    input: RunInput | None = Field(
        None, description="첫 턴. 있으면 바로 run 시작"
    )
    model: str | None = None


class SessionUpdate(Model):
    title: str | None = Field(None, min_length=1, max_length=200)
    code_level: int | None = Field(None, ge=1, le=4)


class ChatSessionRead(Model):
    id: str
    project_id: str
    title: str
    title_source: str
    code_level: int | None
    project_code_level: int | None = Field(None, exclude=True)
    active_run_id: str | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def effective_code_level(self) -> int:
        """Session level, else the project's, else the service default."""
        return (
            self.code_level
            or self.project_code_level
            or get_settings().default_code_level
        )


class MessageRead(Model):
    id: str
    run_id: str | None
    role: str
    content: str
    attachments: list[dict[str, Any]]
    created_at: datetime


class RunRead(Model):
    id: str
    session_id: str
    status: str
    model: str
    waiting: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class SessionPage(Model):
    items: list[ChatSessionRead]
    next_cursor: (
        str | None
    )  # pass back as ?cursor= for the next (older) page; null on the last page


class MessagePage(Model):
    items: list[MessageRead]  # oldest -> newest within the page
    next_cursor: str | None  # older messages before this page


class RunPage(Model):
    items: list[RunRead]
    next_cursor: str | None


class RunEventRead(Model):
    id: int
    type: str
    data: dict[str, Any]
    created_at: datetime


class RunEvents(Model):
    run_id: str
    status: str
    items: list[RunEventRead]


class RunStart(Model):
    run: RunRead
    resumed: bool  # true: the run that was waiting continues (same id)


class SessionStart(Model):
    session: ChatSessionRead
    run: RunRead | None

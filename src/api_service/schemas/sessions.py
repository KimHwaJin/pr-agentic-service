"""Sessions, turns (runs), messages and run events."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)

from api_service.schemas.base import Model
from api_service.schemas.hitl import ResumeValue
from core.config import get_settings
from core.contracts.attachments import Attachment
from core.contracts.events import RunStatus, StoredEvent
from core.contracts.hitl import PauseRequest

MessageRole = Literal["user", "assistant"]
# user: set by the user; initial: the first message; auto: the model named it
TitleSource = Literal["user", "initial", "auto"]


class TextBlock(Model):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=20000)


class ImageBlock(Model):
    type: Literal["image"]
    # a parse-time bound (IMAGE_MAX_BYTES is checked after decoding): 16 MB
    # of base64 is 12 MB of image, above any IMAGE_MAX_BYTES in use
    base64: str = Field(min_length=1, max_length=16 * 1024 * 1024)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    name: str | None = Field(None, max_length=255)


ContentBlock = Annotated[TextBlock | ImageBlock, Field(discriminator="type")]


class RunInput(Model):
    """A user turn: text, or LangChain content blocks (text + images)."""

    content: str | list[ContentBlock] = Field(
        max_length=50,
        description="문자열, 또는 [{type: text, text}, {type: image, base64, "
        "mime_type, name?}] 블록 목록",
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
    value: ResumeValue = Field(
        description="질문 종류(hitl_request.type)에 맞는 답. 서버가 그 종류의 "
        "모델로 다시 검사합니다"
    )

    @field_validator("value", mode="wrap")
    @classmethod
    def _one_error(cls, value: Any, handler: Any) -> Any:
        """Neither an object nor a string: one error, not one per branch."""
        try:
            return handler(value)
        except ValidationError:
            raise ValueError("답 객체 또는 문자열이 필요합니다") from None

    @model_validator(mode="wrap")
    @classmethod
    def _as_sent(cls, data: Any, handler: Any) -> "Resume":
        """Keep the reply as sent; its model depends on the question."""
        resume = handler(data)
        if isinstance(data, dict) and "value" in data:
            resume.__dict__["value"] = data["value"]
        return resume


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
    title_source: TitleSource
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
    role: MessageRole
    content: str
    attachments: list[Attachment]
    created_at: datetime


class RunRead(Model):
    id: str
    session_id: str
    status: RunStatus
    model: str
    waiting: PauseRequest | None = Field(
        description="멈춘 이유 (type으로 구분). 진행 중이거나 끝났으면 null"
    )
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


class RunEvents(Model):
    run_id: str
    status: RunStatus
    items: list[StoredEvent] = Field(
        description="type마다 data 모양이 정해져 있음 (SSE와 같음)"
    )


class RunStart(Model):
    run: RunRead
    resumed: bool  # true: the run that was waiting continues (same id)


class SessionStart(Model):
    session: ChatSessionRead
    run: RunRead | None

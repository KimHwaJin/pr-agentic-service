"""Session events: what the SSE stream and ``GET /runs/{id}/events`` carry.

Every event is ``{id?, type, run_id, data}``; ``data`` has one model per
``type`` in ``EVENTS``. ``EventBus.emit`` checks the data against its model
before storing or sending it, so the agent, the worker and the API share
one definition. A new event type adds its data model here.

Durable events are stored and replayed; live-only ones (``token``,
``execution_progress``, ``activity``) are sent once.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Union, cast

from pydantic import Discriminator, Field, Tag, TypeAdapter, create_model

from core.contracts.attachments import ArtifactAttachment
from core.contracts.hitl import MemoryItem, PauseRequest, View, WorkflowSource

RunStatus = Literal[
    "queued",  # waiting for a worker
    "running",
    "waiting_input",  # a hitl_request is open (waiting.kind == "input")
    "waiting_executor",  # code runs on the executor
    "succeeded",
    "failed",
    "cancelled",
]


class RunStatusData(View):
    status: RunStatus
    # waiting_executor only
    execution_id: str | None = None
    operation_id: str | None = None
    steps: list[str] | None = None


class TokenData(View):
    text: str


class MessageFinalData(View):
    content: str = Field(description="확정 답변 (Markdown)")


class ToolCallData(View):
    name: str
    args: dict[str, Any] = Field(description="긴 값은 잘려 있음")


class AgentSwitchedData(View):
    agent: Literal["main", "analyst"]
    task: str | None = None


class PlanApprovedData(View):
    plan_id: str
    title: str
    document: dict[str, Any] = Field(description="Workflow 1.0 문서")


class PlanAutoApprovedData(View):
    title: str
    source: WorkflowSource | None = None


class PlanRevisedData(View):
    call: int = Field(description="고친 호출 번호")
    args: dict[str, Any]


class ExecutionProgressData(View):
    """Relayed from the executor (``execution.*`` events)."""

    event_type: str
    status: str | None = None
    step: dict[str, Any] | None = None
    error: Any = None


class StepResult(View):
    call: int | None = Field(
        None, description="계획의 호출 번호 (직접 작성한 코드는 null)"
    )
    tool: str | None = None
    id: str | None = Field(None, description="직접 작성한 코드의 id")
    status: str = Field(description="SUCCEEDED | FAILED | ... | NOT_RUN")
    observations: list[Any] = Field(
        default_factory=list,
        description="변수 요약 (데이터에 따라 모양이 다름)",
    )
    stdout: str = ""
    images: list[str] = Field(
        default_factory=list,
        description="GET /sessions/{id}/outputs?execution_id=&path= 의 path",
    )
    error: Any = None


class ExecutionCompletedData(View):
    execution_id: str
    # a list in execution order; events stored before that are
    # {"#<call> <tool>": result}
    results: list[StepResult] | dict[str, StepResult]
    error: str | None = None


class HitlResolvedData(View):
    interrupt_id: str | None


class MemoryRef(View):
    id: str


class MemoryUpdatedData(View):
    action: Literal["created", "updated", "deleted"]
    item: MemoryItem | MemoryRef = Field(description="deleted이면 id만")


class WorkflowSavedData(View):
    workflow_id: str
    name: str


class RunErrorData(View):
    message: str


class SessionTitledData(View):
    title: str


class ActivityData(View):
    """Slow work in progress (agent.activity); extra detail may follow."""

    id: str
    kind: str = Field(
        description="answering | planning | summarizing | report_writing | "
        "workflow_saving"
    )
    state: Literal["started", "finished", "failed", "paused"]
    label: str | None = Field(None, description="started에만: 상태 문구")
    elapsed_ms: int | None = Field(None, description="끝 이벤트에만")


class ContextSummarizedData(View):
    messages: int = Field(description="요약한 메시지 수")
    summary_chars: int


@dataclass(frozen=True)
class EventType:
    data: Any
    durable: bool = True


# event type -> its data model; EventBus.emit checks every event against it
EVENTS: dict[str, EventType] = {
    "run_status": EventType(RunStatusData),
    "token": EventType(TokenData, durable=False),
    "message_final": EventType(MessageFinalData),
    "tool_call": EventType(ToolCallData),
    "agent_switched": EventType(AgentSwitchedData),
    "plan_approved": EventType(PlanApprovedData),
    "plan_auto_approved": EventType(PlanAutoApprovedData),
    "plan_revised": EventType(PlanRevisedData),
    "execution_progress": EventType(ExecutionProgressData, durable=False),
    "execution_completed": EventType(ExecutionCompletedData),
    "hitl_request": EventType(PauseRequest),
    "hitl_resolved": EventType(HitlResolvedData),
    "artifact": EventType(ArtifactAttachment),
    "memory_updated": EventType(MemoryUpdatedData),
    "workflow_saved": EventType(WorkflowSavedData),
    "run_error": EventType(RunErrorData),
    "session_titled": EventType(SessionTitledData),
    "activity": EventType(ActivityData, durable=False),
    "context_summarized": EventType(ContextSummarizedData),
}
_ADAPTERS = {name: TypeAdapter(event.data) for name, event in EVENTS.items()}


class UnknownEventType(ValueError):
    pass


def check(type: str, data: dict[str, Any]) -> None:
    """Raises when ``data`` does not fit the model of ``type``."""
    adapter = _ADAPTERS.get(type)
    if adapter is None:
        raise UnknownEventType(f"unknown event type {type!r}")
    adapter.validate_python(data)


# --- the stored event as the API returns it ----------------------------------


def _event_model(type_name: str, data: Any) -> type[View]:
    title = "".join(p.title() for p in type_name.split("_")) + "Event"
    tag = cast(Any, Literal)[type_name]  # a Literal built per event type
    return create_model(
        title,
        __base__=View,
        __doc__=f"``{type_name}`` event",
        id=(int, ...),
        type=(tag, ...),
        data=(data, ...),
        created_at=(datetime, ...),
    )


class OtherEvent(View):
    """A type stored by an older version (e.g. ``error``)."""

    id: int
    type: str
    data: dict[str, Any]
    created_at: datetime


_STORED = {name: _event_model(name, e.data) for name, e in EVENTS.items()}


def _stored_type(value: Any) -> str:
    kind = value.get("type") if isinstance(value, dict) else value.type
    return kind if kind in _STORED else "other"


if TYPE_CHECKING:
    StoredEvent = Any
else:
    StoredEvent = Annotated[
        Union[  # noqa: UP007
            tuple(Annotated[m, Tag(n)] for n, m in _STORED.items())
            + (Annotated[OtherEvent, Tag("other")],)
        ],
        Discriminator(_stored_type),
    ]

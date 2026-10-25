"""What a paused turn holds: why it stopped (``run.waiting``).

The agent raises these as LangGraph interrupts; the worker stores them on
the run and sends them as the ``hitl_request`` event (questions) or
``run_status: waiting_executor``. The API documents them; the worker
checks every pause against its model before storing it, so producer and
readers share one definition.

A new pause type adds its model to ``REQUESTS`` (and, for a question, its
reply to ``api_service.schemas.hitl.REPLIES``).
"""

from typing import TYPE_CHECKING, Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class View(BaseModel):
    """A payload built by the server from stored data.

    Fields are typed; an extra key added later passes through instead of
    breaking older readers.
    """

    model_config = ConfigDict(from_attributes=True, extra="allow")


class Pause(View):
    """Common part of every pause."""

    interrupt_id: str = Field(description="command.resume.interrupt_id로 답")
    kind: Literal["input", "executor"] | None = Field(
        None, description="run.waiting에만: input(사람) | executor"
    )


class QuestionField(View):
    """A structured input the agent asks for (written by the model)."""

    key: str
    label: str | None = None
    type: str | None = Field(None, description="string | number | date | list")
    required: bool = False


class QuestionRequest(Pause):
    type: Literal["question"]
    question: str
    options: list[str] = Field(
        default_factory=list, description="버튼으로 보여줄 선택지"
    )
    fields: list[QuestionField] = Field(default_factory=list)


class WorkflowSource(View):
    """The registered workflow a candidate plan comes from."""

    workflow_id: str
    revision: int
    name: str


class ParamRef(View):
    """Where a ``tool_output`` parameter takes its value from."""

    call: int | None = Field(description="앞 호출의 번호 (calls[].index)")
    tool: str | None
    output: str


class PlanParam(View):
    name: str
    key: str = Field(
        description="<step>.<tool>.<param>: input_values·overrides의 키"
    )
    type: str | None = Field(description="tool 시그니처의 타입 표기")
    required: bool
    doc: str = ""
    source: Literal["literal", "input", "tool_output", "default"] = Field(
        description="literal: Agent가 정한 값 (overrides로 수정), "
        "input: 사용자가 채울 칸 (input_values), "
        "tool_output: 앞 호출의 결과, default: tool 기본값 (overrides로 수정)"
    )
    value: Any = None
    default: str | None = Field(None, description="source가 default일 때")
    ref: ParamRef | None = Field(None, description="source가 tool_output일 때")


class PlanCall(View):
    index: int = Field(description="계획 안의 호출 번호 (#0, #1 ...)")
    key: str = Field(description="<step>.<tool>")
    skill: str
    skill_description: str = ""
    tool: str
    summary: str = ""
    execution: Literal["always", "conditional"]
    condition: str | None = None
    params: list[PlanParam]


class InputSlot(View):
    """A value the user provides (``source: input``)."""

    key: str
    tool: str
    param: str
    type: str | None = None
    required: bool
    value: Any = None


class PlanCandidate(View):
    title: str
    rationale: str = ""
    source: WorkflowSource | None = None
    document: dict[str, Any] = Field(
        description="Workflow 1.0 문서 "
        "(core/workflows/workflow_schema_1.0.json)"
    )
    calls: list[PlanCall]
    input_slots: list[InputSlot]
    input_values: dict[str, Any] = Field(
        default_factory=dict, description="요청에서 이미 정해진 입력값"
    )


class PlanApprovalRequest(Pause):
    type: Literal["plan_approval"]
    candidates: list[PlanCandidate]


class CodeApprovalRequest(Pause):
    type: Literal["code_approval"]
    purpose: str
    code: str
    code_level: int


class MemoryItem(View):
    id: str
    category: str
    title: str
    content: str
    author: Literal["user", "agent"]
    version: int
    created_at: str
    updated_at: str
    source: dict[str, Any] = Field(default_factory=dict)


class MemoryProposal(View):
    category: str | None = None
    title: str | None = None
    content: str | None = None


class MemoryChangeRequest(Pause):
    type: Literal["memory_change"]
    item: MemoryItem = Field(description="지금 내용")
    proposed: MemoryProposal = Field(description="바꿀 내용 (바뀌는 항목만)")
    reason: str | None = None


class WorkflowSaveRequest(Pause):
    type: Literal["workflow_save"]
    name: str
    user_queries: list[str]
    tags: list[str] = Field(default_factory=list)
    document: dict[str, Any] = Field(description="Workflow 1.0 문서")
    excluded_custom_steps: int = Field(
        0, description="워크플로우에 넣지 않은 직접 작성 코드 수"
    )


class ExecutorWait(Pause):
    """Not a question: the run waits for the executor (resumed by events)."""

    type: Literal["executor_wait"]
    execution_id: str
    operation_id: str | None = Field(
        description="기다리는 작업. null이면 실행 종료(노트북 확정)를 기다림"
    )
    steps: list[str] = Field(default_factory=list)


# pause type -> what the run holds while paused (run.waiting, hitl_request)
REQUESTS: dict[str, Any] = {
    "question": QuestionRequest,
    "plan_approval": PlanApprovalRequest,
    "code_approval": CodeApprovalRequest,
    "memory_change": MemoryChangeRequest,
    "workflow_save": WorkflowSaveRequest,
    "executor_wait": ExecutorWait,
}


# any pause (run.waiting / hitl_request), told apart by ``type``
if TYPE_CHECKING:
    PauseRequest = Any
else:
    PauseRequest = Annotated[
        Union[tuple(REQUESTS.values())],  # noqa: UP007
        Field(discriminator="type"),
    ]

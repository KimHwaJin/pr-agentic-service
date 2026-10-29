"""Human-in-the-loop replies: ``command.resume.value``, one per question.

What a paused run asks lives in ``core.contracts.hitl`` (``REQUESTS``,
``PauseRequest``): the agent produces it, the API shows it as
``RunRead.waiting`` and the ``hitl_request`` event.

The resume request carries no question type, so its schema documents the
union of replies; the server picks the model from the question the run
waits on (``run.waiting.type``) and checks the reply against it
(``api_service.services.hitl``). A new question type adds its request to
``core.contracts.hitl.REQUESTS``, its reply to ``REPLIES`` and its rules
to ``services.hitl.REPLY_RULES``; tests fail when one is missing.
"""

from typing import TYPE_CHECKING, Annotated, Any, Literal, Union

from pydantic import Field

from api_service.schemas.base import Model

# --- replies: command.resume.value -------------------------------------------


class PlanApproveReply(Model):
    """plan_approval: run candidate ``index``."""

    action: Literal["approve"]
    index: int = Field(0, ge=0, description="candidates[] 순번")
    input_values: dict[str, Any] = Field(
        default_factory=dict,
        description='빈 입력칸: {"<step>.<tool>.<param>": 값}',
    )
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description='Agent가 정한 값을 바꿀 때: {"<step>.<tool>.<param>": 값}',
    )


class PlanReviseReply(Model):
    """plan_approval: ask for a different plan."""

    action: Literal["revise"]
    feedback: str


class PlanCancelReply(Model):
    """plan_approval: stop the analysis."""

    action: Literal["cancel"]


PlanReply = Annotated[
    PlanApproveReply | PlanReviseReply | PlanCancelReply,
    Field(discriminator="action"),
]


class CodeApprovalReply(Model):
    """code_approval: run (optionally edited) code, or refuse."""

    approve: bool
    code: str | None = Field(None, description="고친 코드 (승인 시, 선택)")
    feedback: str | None = Field(None, description="거절 사유 (선택)")


class WorkflowSaveReply(Model):
    """workflow_save: save the plan as a workflow (values may be edited)."""

    approve: bool
    name: str | None = None
    user_queries: list[str] | None = Field(
        None, description="승인 시 1개 이상"
    )
    tags: list[str] | None = None
    feedback: str | None = None


QuestionReply = Annotated[
    str | dict[str, Any],
    Field(
        description="question: 답 문자열, 또는 fields가 있으면 "
        "{<field key>: 값}"
    ),
]

# question type -> the reply it takes. A new question type adds its model
# here (and its rules in api_service.services.hitl.REPLY_RULES).
REPLIES: dict[str, Any] = {
    "question": QuestionReply,
    "plan_approval": PlanReply,
    "code_approval": CodeApprovalReply,
    "workflow_save": WorkflowSaveReply,
}

# command.resume.value: any of them (the request names no question type).
# Built from REPLIES so a new type shows up without touching this line;
# type checkers cannot follow a union built at runtime, hence Any for them.
if TYPE_CHECKING:
    ResumeValue = Any
else:
    ResumeValue = Union[tuple(REPLIES.values())]  # noqa: UP007

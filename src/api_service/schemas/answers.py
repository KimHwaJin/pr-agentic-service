"""Answers to a paused turn (``command.resume.value``), one per question type.

The request carries no question type, so the request schema documents the
union; the server picks the model from the question the run waits on
(``run.waiting.type``) and checks the answer against it
(``api_service.services.answers``).
"""

from typing import TYPE_CHECKING, Annotated, Any, Literal, Union

from pydantic import Field

from api_service.schemas.base import Model


class PlanApprove(Model):
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


class PlanRevise(Model):
    """plan_approval: ask for a different plan."""

    action: Literal["revise"]
    feedback: str


class PlanCancel(Model):
    """plan_approval: stop the analysis."""

    action: Literal["cancel"]


PlanAnswer = Annotated[
    PlanApprove | PlanRevise | PlanCancel, Field(discriminator="action")
]


class CodeApprovalAnswer(Model):
    """code_approval: run (optionally edited) code, or refuse."""

    approve: bool
    code: str | None = Field(None, description="고친 코드 (승인 시, 선택)")
    feedback: str | None = Field(None, description="거절 사유 (선택)")


class MemoryChangeAnswer(Model):
    """memory_change: apply the proposed project memory change or not."""

    approve: bool
    feedback: str | None = None


class WorkflowSaveAnswer(Model):
    """workflow_save: save the plan as a workflow (values may be edited)."""

    approve: bool
    name: str | None = None
    user_queries: list[str] | None = Field(
        None, description="승인 시 1개 이상"
    )
    tags: list[str] | None = None
    feedback: str | None = None


QuestionAnswer = Annotated[
    str | dict[str, Any],
    Field(
        description="question: 답 문자열, 또는 fields가 있으면 "
        "{<field key>: 값}"
    ),
]

# question type -> the answer it takes. A new question type adds its model
# here (and its rules in api_service.services.answers.RULES).
ANSWERS: dict[str, Any] = {
    "question": QuestionAnswer,
    "plan_approval": PlanAnswer,
    "code_approval": CodeApprovalAnswer,
    "memory_change": MemoryChangeAnswer,
    "workflow_save": WorkflowSaveAnswer,
}

# command.resume.value: any of them (the request names no question type).
# Built from ANSWERS so a new type shows up without touching this line;
# type checkers cannot follow a union built at runtime, hence Any for them.
if TYPE_CHECKING:
    ResumeValue = Any
else:
    ResumeValue = Union[tuple(ANSWERS.values())]  # noqa: UP007

from dataclasses import dataclass, field
from typing import Any, NotRequired

from langchain.agents import AgentState

from src.dtest.agent.activity import activity
from src.dtest.core.services import Services


@dataclass
class RunContext:
    """Per-run runtime context (not checkpointed).

    Tools reach services through it.
    """

    services: Services
    run_id: str
    session_id: str
    project_id: str
    user_id: str
    model: str
    code_level: int
    project_prompt: str
    user_text: str
    # LangChain content blocks when the turn has images (image blocks carry
    # our image id in file_id); None for a plain text turn
    user_content: list[dict[str, Any]] | None = None
    cache: dict[str, Any] = field(default_factory=dict)

    async def emit(
        self, type: str, data: dict[str, Any], durable: bool = True
    ) -> None:
        await self.services.events.emit(
            self.session_id, self.run_id, type, data, durable
        )

    def activity(self, kind: str, label: str | None = None, **detail: Any):
        """``async with ctx.activity(kind):`` around slow work (see
        agent.activity)."""
        return activity(self.emit, kind, label, **detail)


class AnalysisState(AgentState):
    """Checkpointed per session thread.

    active_agent: which persona drives the conversation (main | analyst).
    plan: approved Workflow 1.0 document + run bindings
        (see agent.tools.analysis).
    execution: the session's live executor MULTI execution
        (one kernel, one notebook).
    nudges: text-only analyst replies sent back in this graph run.
    notice: one-off instruction appended to the next model call only.
    """

    active_agent: NotRequired[str]
    plan: NotRequired[dict[str, Any] | None]
    execution: NotRequired[dict[str, Any] | None]
    nudges: NotRequired[int]
    notice: NotRequired[str | None]


@dataclass
class BatchReportContext:
    """Runtime context of the batch report agent (agent.batch).

    Its events go to the report job's stream instead of a session.
    """

    services: Services
    job_id: str
    execution_id: str
    batch_id: str | None
    model: str
    cache: dict[str, Any] = field(default_factory=dict)

    async def emit(
        self, type: str, data: dict[str, Any], durable: bool = True
    ) -> None:
        await self.services.events.emit_report(
            self.job_id, type, data, durable
        )

    def activity(self, kind: str, label: str | None = None, **detail: Any):
        return activity(self.emit, kind, label, **detail)


class BatchReportState(AgentState):
    """report: what submit_report handed in ({title, markdown, summary})."""

    report: NotRequired[dict[str, Any] | None]

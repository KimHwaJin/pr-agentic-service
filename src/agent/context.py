from dataclasses import dataclass, field
from typing import Any, NotRequired

from langchain.agents import AgentState

from core.services import Services


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
    employee_id: str
    model_alias: str
    code_level: int
    project_prompt: str
    user_text: str
    cache: dict[str, Any] = field(default_factory=dict)

    async def emit(
        self, type: str, data: dict[str, Any], durable: bool = True
    ) -> None:
        await self.services.events.emit(
            self.session_id, self.run_id, type, data, durable
        )


class AnalysisState(AgentState):
    """Checkpointed per session thread.

    active_agent: which persona drives the conversation (main | analyst).
    plan: approved Workflow 1.0 document + run bindings
        (see agent.tools.analysis).
    execution: the session's live executor MULTI execution
        (one kernel, one notebook).
    reports: published report artifacts of this session.
    nudges: text-only analyst replies sent back in this graph run.
    notice: one-off instruction appended to the next model call only.
    """

    active_agent: NotRequired[str]
    plan: NotRequired[dict[str, Any] | None]
    execution: NotRequired[dict[str, Any] | None]
    reports: NotRequired[list[dict[str, Any]]]
    nudges: NotRequired[int]
    notice: NotRequired[str | None]

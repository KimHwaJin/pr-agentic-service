"""Caps the model calls of one user turn, across resumes.

``ModelCallLimitMiddleware(run_limit=...)`` counts in an untracked channel,
so the count starts over whenever the graph resumes from an interrupt. Our
turns resume after every executor wait (run_plan, run_custom_code) and every
approval, so a model retrying a failing execution was never stopped by it.
This count is checkpointed: ``before_agent`` runs when a new user message
starts the graph, not when it resumes, so it resets once per turn.
"""

from typing import Annotated, Any, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import PrivateStateAttr, hook_config
from langchain_core.messages import AIMessage


class TurnCallState(AgentState):
    turn_model_calls: NotRequired[Annotated[int, PrivateStateAttr]]


# the text ModelCallLimitMiddleware ends with too; agent.graph answers the
# user in its place (STOPPED_ANSWER)
LIMIT_PREFIX = "Model call limits exceeded"


def limit_text(limit: int) -> str:
    return f"{LIMIT_PREFIX}: turn limit ({limit} model calls)"


class TurnModelCallLimitMiddleware(AgentMiddleware[TurnCallState]):
    state_schema = TurnCallState

    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit

    def before_agent(self, state, runtime) -> dict[str, Any]:
        return {"turn_model_calls": 0}

    async def abefore_agent(self, state, runtime) -> dict[str, Any]:
        return self.before_agent(state, runtime)

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime) -> dict[str, Any] | None:
        if state.get("turn_model_calls", 0) < self.limit:
            return None
        return {
            "jump_to": "end",
            "messages": [AIMessage(limit_text(self.limit))],
        }

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return self.before_model(state, runtime)

    def after_model(self, state, runtime) -> dict[str, Any]:
        return {"turn_model_calls": state.get("turn_model_calls", 0) + 1}

    async def aafter_model(self, state, runtime) -> dict[str, Any]:
        return self.after_model(state, runtime)

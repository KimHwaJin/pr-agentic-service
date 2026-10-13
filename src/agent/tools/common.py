from typing import Any

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt

from agent.context import AnalysisState, RunContext


@tool
async def ask_user(
    question: str,
    runtime: ToolRuntime[RunContext, AnalysisState],
    options: list[str] | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> str:
    """Ask the user and wait for the answer (human-in-the-loop).

    Use whenever a required value is missing or the request is ambiguous
    instead of guessing.
    options: short choices shown as buttons (the user may still type a free
    answer).
    fields: structured inputs, each
    {"key", "label", "type": "string|number|date|list", "required"}.
    """
    answer = interrupt(
        {
            "type": "question",
            "question": question,
            "options": options or [],
            "fields": fields or [],
        }
    )
    return f"사용자 답변: {answer}"

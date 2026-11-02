"""Stops a tool that keeps failing the same way within one turn.

``ToolErrorMiddleware`` hands every tool exception back to the model so it
can adapt. When the cause is outside the model's reach (a full disk, a
path the OS refuses, an executor that rejects every request) the model
retries the same call until the recursion limit ends the turn with no
answer. This middleware counts, from the checkpointed messages of the
current turn, how many times in a row a tool has returned the same error
(numbers and ids masked, so a new folder number or pid still matches). At
``limit`` the tool is no longer run: the model gets an instruction to
explain the error to the user and end the turn instead. A success or a
different error starts the count over.

A failed execution (run_plan, run_custom_code) comes back with new code and
a new traceback each try, so it rarely repeats word for word: ``any_limit``
stops a tool after that many errors in a row, whatever they say.

Place it outside ``ToolErrorMiddleware`` so it sees the error results.
"""

import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    ToolMessage,
)

STOPPED = "[중단됨]"
# hex ids, uuids, then any other number (folder numbers, pids, line numbers)
_VARIABLE = re.compile(r"[0-9a-fA-F]{8,}|\d+")


def normalized(content: object) -> str:
    return _VARIABLE.sub("#", str(content)).strip()


def _tool_results(messages: list[AnyMessage], tool: str) -> list[ToolMessage]:
    """``tool``'s results in this turn, newest first, without our stops."""
    start = next(
        (
            i + 1
            for i in range(len(messages) - 1, -1, -1)
            if isinstance(messages[i], HumanMessage)
        ),
        0,
    )
    turn = messages[start:]
    names = {
        call["id"]: call["name"]
        for m in turn
        if isinstance(m, AIMessage)
        for call in m.tool_calls
    }
    return [
        m
        for m in reversed(turn)
        if isinstance(m, ToolMessage)
        and names.get(m.tool_call_id, m.name) == tool
        and not str(m.content).startswith(STOPPED)
    ]


def failure_streak(messages: list[AnyMessage], tool: str) -> tuple[int, str]:
    """Consecutive same-error results of ``tool`` at the end of this turn.

    Returns (count, the last error's text). Results this middleware wrote
    (stops) neither count nor break the streak.
    """
    count, last, error = 0, None, ""
    for message in _tool_results(messages, tool):
        if message.status != "error":
            break
        key = normalized(message.content)
        if last is None:
            last, error = key, str(message.content)
        elif key != last:
            break
        count += 1
    return count, error


def error_streak(messages: list[AnyMessage], tool: str) -> tuple[int, str]:
    """Consecutive error results of ``tool`` at the end of this turn,
    whatever the errors say. Returns (count, the last error's text)."""
    count, error = 0, ""
    for message in _tool_results(messages, tool):
        if message.status != "error":
            break
        error = error or str(message.content)
        count += 1
    return count, error


class ToolFailureLimitMiddleware(AgentMiddleware):
    def __init__(self, limit: int, any_limit: int | None = None):
        super().__init__()
        self.limit = limit
        self.any_limit = any_limit

    def _stop(self, request) -> ToolMessage | None:
        tool = request.tool_call["name"]
        messages = (request.state or {}).get("messages", [])
        count, error = failure_streak(messages, tool)
        how = "같은 오류로 "
        if count < self.limit:
            if self.any_limit is None:
                return None
            count, error = error_streak(messages, tool)
            if count < self.any_limit:
                return None
            how = ""
        return ToolMessage(
            f"{STOPPED} `{tool}`이(가) {how}{count}번 연속 실패해 "
            "더 이상 실행하지 않습니다. 다시 호출하지 말고, 사용자에게 "
            "어떤 작업이 어떤 오류로 막혔는지 설명한 뒤 이번 답변을 "
            f"마치세요.\n마지막 오류: {error[:1500]}",
            tool_call_id=request.tool_call["id"],
            name=tool,
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        return self._stop(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._stop(request) or await handler(request)

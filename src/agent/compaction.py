"""Compacts the tool traffic of finished conversation segments.

A segment runs from a call to one of ``start_tools`` (or, without start
tools, from the end of the previous segment) to the result of one of
``end_tools``. When a segment ends, the tool calls inside it are handled
by per-tool rules: removed outright (call and result), or kept with the
result rewritten under the same message id. A segment that is still
running is never touched. The changes ride on the end tool's own state
update, so they add no graph step and land in the same checkpoint.

Removing a finished segment's calls entirely works better than leaving
shortened traces: a model copies the shape of its earlier calls, and a
placeholder where a document was reads as "already known" without the
content.

Unlike ``ContextEditingMiddleware`` (which edits each model request when a
token threshold is passed and leaves the history as is), this changes the
checkpointed history once, at a point the agent defines.

Generic: knows nothing about the tools it compacts; callers pass the rules.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    RemoveMessage,
    ToolMessage,
)
from langgraph.types import Command

MARK = "compacted"  # response_metadata flag on rewritten messages

# "keep" | "remove" (call and result) | "clear" (placeholder)
# | max characters | content -> new content
ResultRule = Literal["keep", "remove", "clear"] | int | Callable[[str], str]
# segment messages -> text appended to the end tool's result
Note = Callable[[Sequence[AnyMessage]], str | None]


@dataclass(frozen=True)
class Rule:
    result: ResultRule = "keep"


KEEP, REMOVE = Rule(), Rule(result="remove")


class ToolResultCompactionMiddleware(AgentMiddleware):
    """Removes or rewrites the tool calls of segments that have ended.

    rules: tool name -> Rule; tools not listed use ``default``.
    note: called with an ended segment's messages; its text is appended to
    the end tool's result (e.g. ids of what the removed calls produced).
    placeholder: text for cleared results; ``{tool}`` is the tool name.
    """

    def __init__(
        self,
        *,
        end_tools: Collection[str],
        start_tools: Collection[str] = (),
        rules: Mapping[str, Rule] | None = None,
        default: Rule = KEEP,
        note: Note | None = None,
        placeholder: str = "[compacted: {tool}]",
        truncated: str = " ...[compacted]",
    ):
        super().__init__()
        self.end_tools, self.start_tools = set(end_tools), set(start_tools)
        self.rules, self.default = dict(rules or {}), default
        self.note = note
        self.placeholder, self.truncated = placeholder, truncated

    def wrap_tool_call(self, request, handler):
        return self._with_compaction(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._with_compaction(request, await handler(request))

    def _with_compaction(self, request, result: Any) -> Any:
        """Adds the compacted segment to the end tool's own update."""
        if request.tool_call["name"] not in self.end_tools:
            return result
        if isinstance(result, Command):
            if not isinstance(result.update, dict):
                return result
            update: dict[str, Any] = result.update
            produced = list(update.get("messages", []))
        else:
            update, produced = {}, [result]
        history = list(request.state["messages"])
        segment = self.segment(history)
        noted = (
            self._noted(produced, request, segment)
            if segment is not None
            else produced
        )
        changed = self.compact([*history, *noted])
        if not changed and noted is produced:
            return result
        messages = [*noted, *changed]
        if isinstance(result, Command):
            return replace(result, update={**update, "messages": messages})
        return Command(update={"messages": messages})

    def segment(self, history: Sequence[AnyMessage]) -> list | None:
        """Messages of the segment the end tool is about to close."""
        if not self.start_tools:
            names = self._names(history)
            ends = [
                i
                for i, m in enumerate(history)
                if isinstance(m, ToolMessage)
                and names.get(m.tool_call_id) in self.end_tools
            ]
            return list(history[ends[-1] + 1 if ends else 0 :])
        for i in range(len(history) - 1, -1, -1):
            m = history[i]
            if isinstance(m, AIMessage) and any(
                c["name"] in self.start_tools for c in m.tool_calls
            ):
                return list(history[i:])
        return None

    def _noted(self, produced, request, segment) -> list:
        text = self.note(segment) if self.note else None
        if not text:
            return produced
        call_id = request.tool_call["id"]
        return [
            m.model_copy(update={"content": f"{m.content}\n\n{text}"})
            if isinstance(m, ToolMessage)
            and m.tool_call_id == call_id
            and isinstance(m.content, str)
            else m
            for m in produced
        ]

    def compact(self, messages: Sequence[BaseMessage]) -> list[BaseMessage]:
        """Removals and rewritten copies (same ids) for ended segments."""
        names = self._names(messages)
        changed: list[BaseMessage] = []
        start: int | None = None if self.start_tools else 0
        for i, message in enumerate(messages):
            if isinstance(message, AIMessage) and any(
                c["name"] in self.start_tools for c in message.tool_calls
            ):
                start = i
            elif (
                isinstance(message, ToolMessage)
                and names.get(message.tool_call_id) in self.end_tools
            ):
                if start is not None:
                    for m in messages[start:i]:
                        changed += self._rewrite(m, names)
                start = None if self.start_tools else i + 1
        return changed

    def _names(self, messages: Sequence[BaseMessage]) -> dict[str, str]:
        return {
            call["id"] or "": call["name"]
            for m in messages
            if isinstance(m, AIMessage)
            for call in m.tool_calls
        }

    def _rule(self, tool: str | None) -> Rule:
        return self.rules.get(tool or "", self.default)

    def _rewrite(
        self, message: BaseMessage, names: dict[str, str]
    ) -> list[BaseMessage]:
        if message.response_metadata.get(MARK) or message.id is None:
            return []
        if isinstance(message, ToolMessage):
            tool = names.get(message.tool_call_id)
            rule = self._rule(tool).result
            if rule == "remove":
                return [RemoveMessage(id=message.id)]
            content = (
                message.content
                if isinstance(message.content, str)
                else message.text
            )
            new = self._result(rule, content, tool)
            if new == content:
                return []
            return [self._marked(message, content=new)]
        if isinstance(message, AIMessage) and message.tool_calls:
            kept = [
                c
                for c in message.tool_calls
                if self._rule(c["name"]).result != "remove"
            ]
            if len(kept) == len(message.tool_calls):
                return []
            if not kept and not message.text:
                return [RemoveMessage(id=message.id)]
            # drop the provider copy too, or it would resend removed calls
            extra = {
                k: v
                for k, v in message.additional_kwargs.items()
                if k != "tool_calls"
            }
            return [
                self._marked(message, tool_calls=kept, additional_kwargs=extra)
            ]
        return []

    @staticmethod
    def _marked(message: BaseMessage, **update: Any) -> BaseMessage:
        metadata = {**message.response_metadata, MARK: True}
        return message.model_copy(
            update={**update, "response_metadata": metadata}
        )

    def _result(self, rule: ResultRule, content: str, tool: str | None):
        if rule == "keep":
            return content
        if rule == "clear":
            return self.placeholder.format(tool=tool)
        if isinstance(rule, int):
            if len(content) <= rule:
                return content
            return content[:rule] + self.truncated
        if callable(rule):
            return rule(content)
        return content

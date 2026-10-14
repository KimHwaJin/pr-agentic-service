"""Compacts the tool traffic of finished conversation segments.

A segment runs from a call to one of ``start_tools`` (or, without start
tools, from the end of the previous segment) to the result of one of
``end_tools``. Once a segment has ended, the tool results and call
arguments inside it are rewritten by per-tool rules and saved back under
the same message ids, so every later model call (and summarization) sees
the compact version. A segment that is still running is never touched.
The rewrite rides on the end tool's own state update.

Prefer rules on results over rules on arguments: a model copies the shape
of its own earlier calls, so arguments rewritten into a shape the tool
does not accept get imitated in later calls.

Unlike ``ContextEditingMiddleware`` (which edits each model request when a
token threshold is passed and leaves the history as is), this changes the
checkpointed history once, at a point the agent defines.

Generic: knows nothing about the tools it compacts; callers pass the rules.
"""

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langgraph.types import Command

MARK = "compacted"  # response_metadata flag on rewritten messages

# "keep" | "clear" (placeholder) | max characters | content -> new content
ResultRule = Literal["keep", "clear"] | int | Callable[[str], str]
# "keep" | "clear" (each value -> placeholder) | args -> new args
ArgsRule = Literal["keep", "clear"] | Callable[[dict[str, Any]], dict]


@dataclass(frozen=True)
class Rule:
    result: ResultRule = "keep"
    args: ArgsRule = "keep"
    # clear a result once the same call (tool + args) returns again later;
    # for reference reads the next segment may rely on without re-reading
    latest_only: bool = False


KEEP = Rule()


class ToolResultCompactionMiddleware(AgentMiddleware):
    """Rewrites tool results/arguments of segments that have ended.

    rules: tool name -> Rule; tools not listed use ``default``.
    placeholder: text for cleared values; ``{tool}`` is the tool name.
    """

    def __init__(
        self,
        *,
        end_tools: Collection[str],
        start_tools: Collection[str] = (),
        rules: Mapping[str, Rule] | None = None,
        default: Rule = KEEP,
        placeholder: str = "[compacted: {tool}]",
        truncated: str = " ...[compacted]",
        superseded: str = "[compacted: {tool}, repeated later]",
    ):
        super().__init__()
        self.end_tools, self.start_tools = set(end_tools), set(start_tools)
        self.rules, self.default = dict(rules or {}), default
        self.placeholder, self.truncated = placeholder, truncated
        self.superseded = superseded

    def wrap_tool_call(self, request, handler):
        return self._with_compaction(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._with_compaction(request, await handler(request))

    def _with_compaction(self, request, result: Any) -> Any:
        """Adds the compacted segment to the end tool's own update.

        Done inside the tool step, so it adds no graph step (recursion limit)
        and lands in the same checkpoint as the end tool's result.
        """
        if request.tool_call["name"] not in self.end_tools:
            return result
        if isinstance(result, Command):
            if not isinstance(result.update, dict):
                return result
            update: dict[str, Any] = result.update
            produced = list(update.get("messages", []))
        else:
            update, produced = {}, [result]
        changed = self.compact([*request.state["messages"], *produced])
        if not changed:
            return result
        messages = [*produced, *changed]
        if isinstance(result, Command):
            return replace(result, update={**update, "messages": messages})
        return Command(update={"messages": messages})

    def compact(self, messages: Sequence[AnyMessage]) -> list[AnyMessage]:
        """Rewritten copies (same ids) of messages in ended segments."""
        names: dict[str, str] = {
            call["id"] or "": call["name"]
            for m in messages
            if isinstance(m, AIMessage)
            for call in m.tool_calls
        }
        superseded = self._superseded(messages)
        changed: list[AnyMessage] = []
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
                        new = self._rewrite(m, names, superseded)
                        if new is not None:
                            changed.append(new)
                start = None if self.start_tools else i + 1
        return changed

    def _superseded(self, messages: Sequence[AnyMessage]) -> set[str]:
        """Tool call ids of latest_only results repeated by a later call."""
        keys: dict[str, tuple[str, str]] = {
            call["id"] or "": (
                call["name"],
                json.dumps(call["args"], sort_keys=True),
            )
            for m in messages
            if isinstance(m, AIMessage)
            for call in m.tool_calls
            if self._rule(call["name"]).latest_only
        }
        latest: dict[tuple[str, str], str] = {}
        for m in messages:
            if isinstance(m, ToolMessage) and m.tool_call_id in keys:
                latest[keys[m.tool_call_id]] = m.tool_call_id
        return set(keys) - set(latest.values())

    def _rule(self, tool: str | None) -> Rule:
        return self.rules.get(tool or "", self.default)

    def _rewrite(
        self,
        message: AnyMessage,
        names: dict[str, str],
        superseded: set[str],
    ) -> AnyMessage | None:
        if message.response_metadata.get(MARK):
            return None
        update: dict[str, Any] = {}
        if isinstance(message, ToolMessage):
            tool = names.get(message.tool_call_id)
            content = (
                message.content
                if isinstance(message.content, str)
                else message.text
            )
            new = (
                self.superseded.format(tool=tool)
                if message.tool_call_id in superseded
                else self._result(self._rule(tool).result, content, tool)
            )
            if new != content:
                update["content"] = new
        elif isinstance(message, AIMessage) and message.tool_calls:
            calls = [
                {**c, "args": self._args(self._rule(c["name"]).args, c)}
                for c in message.tool_calls
            ]
            if calls != message.tool_calls:
                update["tool_calls"] = calls
        if not update:
            return None
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
        return rule(content)

    def _args(self, rule: ArgsRule, call: Mapping[str, Any]) -> dict[str, Any]:
        args = call.get("args") or {}
        if rule == "keep":
            return args
        if rule == "clear":
            text = self.placeholder.format(tool=call["name"])
            return {k: text for k in args}
        return rule(args)

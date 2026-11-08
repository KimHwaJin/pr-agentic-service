"""Duplicate tool calls in one model response.

A model with parallel tool calls can put the same call twice in one
response, or split its plan candidates over several ``propose_plans``
calls. Each ``propose_plans`` call is its own approval card, and approving
two in the same step writes ``plan`` twice (LangGraph refuses that and the
turn fails). Before the tools run:

- identical calls (same tool, same arguments) run once;
- several ``propose_plans`` calls become one: the first, carrying every
  candidate in order (``propose_plans`` drops repeated plans and keeps the
  configured number).

Other parallel calls run as before, so no model call is added.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import json_repair
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage

log = logging.getLogger(__name__)

# tools whose calls in one response merge into one; value: the list
# argument the calls are joined on
MERGED = {"propose_plans": "candidates"}


class ToolCallDedupMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> Any:
        response = await handler(request)
        if isinstance(response, AIMessage):
            return dedup_message(response)
        if isinstance(response, ModelResponse):
            response.result = [
                dedup_message(m) if isinstance(m, AIMessage) else m
                for m in response.result
            ]
        return response


def dedup_message(message: AIMessage) -> AIMessage:
    calls = message.tool_calls
    if len(calls) < 2:
        return message
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    merged_into: dict[str, dict[str, Any]] = {}  # tool name -> first call
    dropped: list[str] = []
    for call in calls:
        name = call["name"]
        if (field := MERGED.get(name)) is not None:
            first = merged_into.get(name)
            if first is None:
                first = {
                    **call,
                    "args": {
                        **call["args"],
                        field: _as_list(call["args"].get(field)),
                    },
                }
                merged_into[name] = first
                kept.append(first)
            else:
                first["args"][field] = [
                    *first["args"][field],
                    *_as_list(call["args"].get(field)),
                ]
                dropped.append(name)
            continue
        key = _key(call)
        if key in seen:
            dropped.append(name)
            continue
        seen.add(key)
        kept.append(call)
    if not dropped:
        return message
    log.info(
        "tool_calls_deduplicated message_id=%s dropped=%s",
        message.id,
        dropped,
    )
    return message.model_copy(update={"tool_calls": kept})


def _key(call: dict[str, Any]) -> str:
    return json.dumps(
        [call["name"], call["args"]],
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def _as_list(value: Any) -> list[Any]:
    """A list argument; some served models send it as a JSON string."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = json_repair.loads(value)
    if isinstance(value, list):
        return value
    return [] if value is None else [value]

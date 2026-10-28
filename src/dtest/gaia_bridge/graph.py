"""The graph gaia runs for this service (src/workflows/dtest/analyst.py).

One node: the gaia message becomes a turn of our chat (``turn.run_turn``),
whose text is streamed through LangGraph's custom stream (gaia shows
custom ``str`` chunks as they come) and returned as ``answer``.
"""

import logging
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from src.dtest.gaia_bridge import runtime
from src.dtest.gaia_bridge.turn import run_turn

log = logging.getLogger(__name__)


class BridgeState(TypedDict, total=False):
    # from gaia
    query: str
    user_id: str  # employee id
    session_id: str  # gaia's session id
    trace_id: str
    gaia_input_channel: str
    # to gaia
    answer: str
    docs: list[Any]
    urls: list[dict[str, str]]
    usage: list[Any]


async def answer(state: BridgeState) -> dict[str, Any]:
    def reply(text: str) -> dict[str, Any]:
        return {
            "answer": text,
            "docs": [],
            "urls": [],
            "usage": [],
            "trace_id": state.get("trace_id", ""),
        }

    services = runtime.current()
    if services is None:
        return reply(
            "분석 서비스가 준비 중입니다. 잠시 후 다시 시도해 주세요."
        )
    employee_id = (state.get("user_id") or "").strip()
    query = (state.get("query") or "").strip()
    if not employee_id:
        return reply("사용자 정보(user_id)가 없습니다.")
    if not query:
        return reply("질문을 입력해 주세요.")
    gaia_session_id = state.get("session_id") or state.get("trace_id") or ""
    try:
        result = await run_turn(
            services,
            employee_id=employee_id,
            gaia_session_id=gaia_session_id,
            query=query,
            write=get_stream_writer(),
        )
    except Exception:
        log.exception("gaia_turn_failed user_id=%s", employee_id)
        return reply("분석 중 오류가 발생했습니다. 다시 시도해 주세요.")
    return {**reply(result.answer), "urls": result.urls}


def _return_adapter() -> Callable[[Any], Any]:
    """gaia's wrapper for the last node (only inside the template)."""
    try:
        from src.common.return_node import (  # ty: ignore[unresolved-import]
            gaia_return_adapter,
        )
    except ImportError:
        return lambda node: node
    return gaia_return_adapter


def build_graph():
    graph = StateGraph(BridgeState)  # ty: ignore[invalid-argument-type]
    graph.add_node("answer", _return_adapter()(answer))
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile()

"""Both personas see and read knowledge skills; analysis skills stay the
analyst's."""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from src.dtest.agent.middleware import persona
from src.dtest.agent.middleware.persona import (
    PERSONA_TOOLS,
    PersonaMiddleware,
    _isolate,
)
from src.dtest.agent.tools.main import read_knowledge


class _Index:
    def __init__(self, text):
        self.text = text

    def index(self):
        return self.text


INDEXES = {
    "analysis": "- `eda_analysis`: EDA",
    "knowledge": "- `product_glossary`: 제품 코드와 사내 용어",
}


class _Request:
    def __init__(self, ctx, state, tools):
        self.runtime = SimpleNamespace(context=ctx)
        self.state, self.tools, self.messages = state, tools, []

    def override(self, **changes):
        return changes


def _call(agent, monkeypatch):
    async def same(messages, ctx):
        return messages

    monkeypatch.setattr(persona, "_with_images", same)
    monkeypatch.setattr(persona, "_with_figures", same)
    ctx = SimpleNamespace(
        code_level=3,
        project_prompt="",
        cache={},
        services=SimpleNamespace(
            skills=lambda root: _Index(INDEXES[root]),
            settings=SimpleNamespace(
                plan_recommend_mode="mixed", plan_candidates=3
            ),
        ),
    )
    ctx.activity = lambda kind: _Async()
    names = set().union(*PERSONA_TOOLS.values())
    tools = [SimpleNamespace(name=n) for n in sorted(names)]

    async def handler(request):
        return request

    request = _Request(ctx, {"active_agent": agent, "messages": []}, tools)
    return asyncio.run(PersonaMiddleware().awrap_model_call(request, handler))


class _Async:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_analyst_lists_and_reads_knowledge(monkeypatch):
    sent = _call("analyst", monkeypatch)
    system = sent["system_message"].content
    assert "product_glossary" in system and "eda_analysis" in system
    assert "{knowledge_skills}" not in system
    assert "{analysis_skills}" not in system
    names = {t.name for t in sent["tools"]}
    assert {"read_knowledge", "read_skill"} <= names


def test_main_lists_knowledge_only(monkeypatch):
    sent = _call("main", monkeypatch)
    system = sent["system_message"].content
    assert "product_glossary" in system and "eda_analysis" not in system
    names = {t.name for t in sent["tools"]}
    assert "read_knowledge" in names and "read_skill" not in names


def test_knowledge_read_by_main_stays_visible_to_the_analyst():
    call = AIMessage(
        "",
        tool_calls=[
            {"name": read_knowledge.name, "args": {"name": "g"}, "id": "k1"},
            {"name": "read_skill", "args": {"name": "s"}, "id": "s1"},
        ],
    )
    messages = [
        call,
        ToolMessage("A100 = 제품 A", tool_call_id="k1"),
        ToolMessage("skill body", tool_call_id="s1"),
    ]
    for_analyst = _isolate(messages, "analyst")
    assert for_analyst[1].content == "A100 = 제품 A"
    for_main = _isolate(messages, "main")
    assert for_main[1].content == "A100 = 제품 A"
    assert for_main[2].content != "skill body"

"""Without embeddings the chat model, not word overlap, picks templates."""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from core.workflows import pick
from core.workflows.service import WorkflowService


class _Model:
    def __init__(self, reply: str):
        self.reply, self.seen = reply, []

    async def ainvoke(self, messages):
        self.seen.append(messages)
        return AIMessage(self.reply)


def _wf(workflow_id, name="wf", queries=()):
    return SimpleNamespace(
        id=workflow_id,
        name=name,
        user_request=f"{name} 요청",
        user_queries=list(queries),
    )


def test_keeps_the_models_order_and_drops_unknown_ids():
    pool = [_wf("a"), _wf("b"), _wf("c")]
    model = _Model('{"ids": ["c", "zz", "a", "c"]}')
    chosen = asyncio.run(pick.pick(model, "NCE 분포", pool, 5))
    assert [w.id for w in chosen] == ["c", "a"]


def test_limit_and_empty_answers():
    pool = [_wf("a"), _wf("b")]
    assert [
        w.id
        for w in asyncio.run(
            pick.pick(_Model('{"ids": ["b", "a"]}'), "q", pool, 1)
        )
    ] == ["b"]
    assert asyncio.run(pick.pick(_Model('{"ids": []}'), "q", pool, 5)) == []
    assert asyncio.run(pick.pick(_Model("모르겠습니다"), "q", pool, 5)) == []


def test_shared_words_alone_are_not_a_match():
    # the model decides; a word in common ("분석") is no reason
    pool = [_wf("a", "설비 분석", ["설비 가동률 분석"])]
    model = _Model('{"ids": []}')
    assert asyncio.run(pick.pick(model, "수율 분석", pool, 5)) == []
    request = model.seen[0][1].content
    assert "설비 가동률 분석" in request and "id=a" in request


def test_no_call_without_templates_or_query():
    model = _Model('{"ids": ["a"]}')
    assert asyncio.run(pick.pick(model, "q", [], 5)) == []
    assert asyncio.run(pick.pick(model, "  ", [_wf("a")], 5)) == []
    assert model.seen == []


def test_service_without_embedder_or_chooser_finds_nothing():
    service = WorkflowService(None, None, "m", 1024, 0.8)
    assert asyncio.run(service.search("q", 5)) == []

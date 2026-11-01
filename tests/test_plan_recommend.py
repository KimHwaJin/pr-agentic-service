"""Template recommendation: when a plan runs without the card, rejecting
the recommended workflows, and the prompt text of each mode."""

import asyncio
import copy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.dtest.agent.middleware.persona import plan_recommend
from src.dtest.agent.tools import analysis
from src.dtest.api_service.services import hitl
from src.dtest.core.config import Settings
from src.dtest.core.workflows import spec


def _settings(**over):
    values = {
        "plan_candidates": 5,
        "plan_recommend_mode": "mixed",
        "workflow_auto_run_similarity": 0.77,
    }
    return SimpleNamespace(**(values | over))


@pytest.fixture
def template(static):
    document = copy.deepcopy(static)
    document["workflow"]["allow_immediate_execution"] = True
    return document


class Workflows:
    def __init__(self, documents: dict[str, dict], hits: list[dict]):
        self.documents, self.hits = documents, hits

    async def readable(self, workflow_id, user_id):
        return SimpleNamespace(
            id=workflow_id,
            revision=1,
            name=f"wf {workflow_id}",
            document=copy.deepcopy(self.documents[workflow_id]),
        )

    async def search(self, query, limit):
        return self.hits[:limit]


def _runtime(skills, tools, workflows, state=None, settings=None):
    events = []

    async def emit(type, data, durable=True):
        events.append(type)

    services = SimpleNamespace(
        skills=lambda kind: skills,
        tool_catalog=lambda: tools,
        workflows=workflows,
        settings=settings or _settings(),
    )
    ctx = SimpleNamespace(
        services=services,
        run_id="run1",
        user_id="u1",
        user_text="NCE 통계",
        emit=emit,
    )
    return SimpleNamespace(
        context=ctx, state=state or {}, tool_call_id="tc1", events=events
    )


def _all_inputs(document, tools):
    """Every input slot of a template filled, as the model writes inputs."""
    keys = [c.key for c in spec.calls(spec.normalize(document))]
    out = {}
    for slot in spec.input_slots(spec.normalize(document), tools):
        step, tool, param = slot["key"].split(".", 2)
        out[f"{keys.index(f'{step}.{tool}')}.{param}"] = "x"
    return out


def _hit(workflow_id, similarity, document):
    workflow = SimpleNamespace(
        id=workflow_id,
        name="wf",
        user_request="q",
        document=document,
    )
    return {"workflow": workflow, "similarity": similarity}


def _search(runtime, query="NCE 통계"):
    result = asyncio.run(
        analysis.search_workflows.coroutine(query, runtime=runtime)
    )
    runtime.state = {**runtime.state, **result.update}
    return result


def _propose(runtime, candidates):
    return asyncio.run(
        analysis.propose_plans.coroutine(candidates, runtime=runtime)
    )


@pytest.fixture
def asked(monkeypatch):
    """Payloads of the approval cards; the user answers with ``reply``."""
    seen: list[dict] = []
    reply = {"value": {"action": "cancel"}}

    def fake(payload):
        seen.append(payload)
        return reply["value"]

    monkeypatch.setattr(analysis, "interrupt", fake)
    return SimpleNamespace(seen=seen, reply=reply)


def _template_candidate(workflow_id, document, tools):
    return {
        "title": f"템플릿 {workflow_id}",
        "workflow_id": workflow_id,
        "inputs": _all_inputs(document, tools),
    }


NEW_PLAN = {
    "title": "새 계획",
    "calls": [
        {
            "skill": "data_load",
            "tool": "extract_data",
            "args": {"data_type": "$input"},
        }
    ],
}


# --- when a template runs without the card ------------------------------


def test_one_template_close_enough_runs_at_once(
    skills, tools, template, asked
):
    wf = Workflows({"w1": template}, [_hit("w1", 0.98, template)])
    runtime = _runtime(skills, tools, wf)
    _search(runtime)
    result = _propose(runtime, [_template_candidate("w1", template, tools)])
    assert asked.seen == []
    assert runtime.events == ["plan_auto_approved", "plan_approved"]
    assert result.update["plan"]["source"]["workflow_id"] == "w1"


def test_two_candidates_always_show_the_card(skills, tools, template, asked):
    wf = Workflows(
        {"w1": template, "w2": template},
        [_hit("w1", 0.99, template), _hit("w2", 0.99, template)],
    )
    runtime = _runtime(skills, tools, wf)
    _search(runtime)
    _propose(
        runtime,
        [
            _template_candidate("w1", template, tools),
            _template_candidate("w2", template, tools),
        ],
    )
    assert len(asked.seen) == 1


def test_similarity_below_the_auto_run_bar_shows_the_card(
    skills, tools, template, asked
):
    wf = Workflows({"w1": template}, [_hit("w1", 0.75, template)])
    runtime = _runtime(skills, tools, wf)
    _search(runtime)
    _propose(runtime, [_template_candidate("w1", template, tools)])
    assert len(asked.seen) == 1


def test_keyword_search_never_runs_at_once(skills, tools, template, asked):
    wf = Workflows({"w1": template}, [_hit("w1", None, template)])
    runtime = _runtime(skills, tools, wf)
    _search(runtime)
    _propose(runtime, [_template_candidate("w1", template, tools)])
    assert len(asked.seen) == 1


def test_similarity_comes_from_this_runs_search_only(
    skills, tools, template, asked
):
    wf = Workflows({"w1": template}, [])
    # never searched in this run: the model cannot claim a similarity
    runtime = _runtime(skills, tools, wf)
    _propose(
        runtime,
        [_template_candidate("w1", template, tools) | {"similarity": 1.0}],
    )
    # another run's search does not count either
    stale = {"recommend": {"run_id": "run0", "similarity": {"w1": 0.99}}}
    runtime = _runtime(skills, tools, wf, state=stale)
    _propose(runtime, [_template_candidate("w1", template, tools)])
    assert len(asked.seen) == 2


# --- allow_reject_templates and reject_templates -------------------------


def test_reject_is_offered_only_when_every_candidate_is_a_template(
    skills, tools, template, asked
):
    wf = Workflows({"w1": template}, [_hit("w1", 0.75, template)])
    runtime = _runtime(skills, tools, wf)
    _search(runtime)
    _propose(runtime, [_template_candidate("w1", template, tools)])
    _propose(runtime, [_template_candidate("w1", template, tools), NEW_PLAN])
    _propose(runtime, [NEW_PLAN])
    assert [p["allow_reject_templates"] for p in asked.seen] == [
        True,
        False,
        False,
    ]


def test_rejected_templates_are_refused_for_the_rest_of_the_run(
    skills, tools, template, asked
):
    wf = Workflows({"w1": template}, [_hit("w1", 0.75, template)])
    runtime = _runtime(skills, tools, wf)
    _search(runtime)
    asked.reply["value"] = {"action": "reject_templates"}
    result = _propose(runtime, [_template_candidate("w1", template, tools)])
    text = result.update["messages"][0].content
    assert "거절" in text and "5개" in text and "propose_plans" in text
    assert result.update["recommend"]["rejected"] is True
    assert "plan" not in result.update
    runtime.state = {**runtime.state, "recommend": result.update["recommend"]}

    # the server holds the line: no workflow_id candidate after a reject
    before = len(asked.seen)
    refused = _propose(
        runtime, [NEW_PLAN, _template_candidate("w1", template, tools)]
    )
    assert len(asked.seen) == before
    assert "workflow_id" in refused.update["messages"][0].content
    assert "후보 1" in refused.update["messages"][0].content
    # a search later in the run keeps the rejection
    _search(runtime)
    assert runtime.state["recommend"]["rejected"] is True

    # new plans go through
    asked.reply["value"] = {"action": "cancel"}
    _propose(runtime, [NEW_PLAN])
    assert len(asked.seen) == before + 1

    # the next run (turn) may recommend again
    runtime.context.run_id = "run2"
    _propose(runtime, [_template_candidate("w1", template, tools)])
    assert len(asked.seen) == before + 2


def test_reject_templates_reply_needs_the_question_to_allow_it():
    waiting = {"type": "plan_approval", "candidates": [{}]}
    reply = {"action": "reject_templates"}
    errors = hitl.validate(waiting, reply)
    assert [e["field"] for e in errors] == ["value.action"]
    allowed = {**waiting, "allow_reject_templates": True}
    assert hitl.validate(allowed, reply) == []
    # no other fields on it
    assert hitl.validate(allowed, {**reply, "index": 0})


def test_reject_templates_is_refused_with_422():
    from src.dtest.api_service.errors import ApiError
    from src.dtest.api_service.services import runs

    active = SimpleNamespace(
        status="waiting_input",
        waiting={
            "type": "plan_approval",
            "interrupt_id": "i1",
            "candidates": [{}],
            "allow_reject_templates": False,
        },
    )
    resume = SimpleNamespace(
        interrupt_id="i1", value={"action": "reject_templates"}
    )
    with pytest.raises(ApiError) as exc:
        runs._resume(active, resume)
    assert exc.value.status == 422
    assert exc.value.code == "invalid_answer"


def test_the_card_shape_documents_allow_reject_templates():
    from pydantic import TypeAdapter

    from src.dtest.core.contracts.hitl import PauseRequest

    pause = TypeAdapter(PauseRequest).validate_python(
        {
            "interrupt_id": "i",
            "type": "plan_approval",
            "candidates": [],
            "allow_reject_templates": True,
        }
    )
    assert pause.allow_reject_templates is True


# --- prompt and settings -------------------------------------------------


def test_prompt_step_three_follows_the_mode():
    mixed = plan_recommend(_settings(plan_candidates=4))
    assert "나머지 4-k개는 새로" in mixed
    first = plan_recommend(
        _settings(plan_candidates=4, plan_recommend_mode="recommend_first")
    )
    assert "추천 워크플로우(`workflow_id` 후보)만" in first
    assert "추천을 거절하면" in first and "새 계획을 4개" in first
    assert "{n}" not in mixed + first


def test_analyst_prompt_takes_the_mode_text():
    from src.dtest.agent.prompts import load_prompt

    body = load_prompt("analyst").body
    assert "3. {plan_recommend}" in body


def test_auto_run_similarity_is_not_below_workflow_similarity():
    assert Settings().plan_recommend_mode == "mixed"
    assert Settings().workflow_similarity == 0.70
    assert Settings().workflow_auto_run_similarity == 0.77
    with pytest.raises(ValidationError, match="WORKFLOW_AUTO_RUN"):
        Settings(workflow_similarity=0.93, workflow_auto_run_similarity=0.9)
    with pytest.raises(ValidationError):
        Settings(plan_recommend_mode="templates_only")
    Settings(workflow_similarity=0.9, workflow_auto_run_similarity=0.9)

"""Reports: evidence chosen by code, one-call writing."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from langchain_core.language_models.fake_chat_models import (
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage

from agent import report_agent, reporter
from core.config import Settings

OUTPUTS = {
    2: "mean 1.998321\nstd 0.142695",
    3: "count 988\n" + "row\n" * 2000,  # long output
}


class _ToolModel(GenericFakeChatModel):
    bound: list[str] | None = None

    def bind_tools(self, tools, **kwargs):
        self.bound = [t.name for t in tools]
        return self


def _model(*messages):
    return _ToolModel(messages=iter(messages), disable_streaming=True)


def _call(name, args, id):
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": id}])


class _Executor:
    def __init__(self):
        self.results = 0

    async def result(self, execution_id):
        self.results += 1
        return {
            "operations": [
                {
                    "steps": [
                        {
                            "sequence": n,
                            "lineage": {"skill_name": "eda", "tool_name": "t"},
                            "result": {
                                "status": "SUCCEEDED",
                                "result_ref": {"step": n},
                            },
                        }
                        for n in OUTPUTS
                    ]
                }
            ]
        }


class _Storage:
    def read_step_outputs(self, ref, max_chars):
        text = OUTPUTS[ref["step"]]
        return {
            "available": True,
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
        }

    def step_source(self, ref):
        return ""


class _Memory:
    async def contents(self, project_id):
        return [{"topic": "preferences", "content": "- 표 위주"}]


def _services():
    return SimpleNamespace(
        settings=Settings(),
        executor=_Executor(),
        storage=_Storage(),
        memory=_Memory(),
    )


def _ctx(sent):
    async def emit(type, data, durable=True):
        sent.append((type, data))

    return cast(
        Any,
        SimpleNamespace(
            services=_services(),
            project_id="p",
            project_prompt="",
            user_text="수율 분석",
            model="m",
            emit=emit,
        ),
    )


def _write(ctx, evidence):
    return asyncio.run(
        reporter.generate_report(
            ctx, "exe-1", title="수율", focus="f", evidence=evidence
        )
    )


def _use(monkeypatch, model):
    monkeypatch.setattr(report_agent, "chat_model", lambda s, n: model)
    reporter._analysis_agents.clear()


# --- evidence ---------------------------------------------------------------


def test_evidence_that_fits_is_whole_and_unmarked():
    text = asyncio.run(
        reporter.collect_evidence(cast(Any, _services()), "e", None)
    )
    assert "row\n" * 1999 in text  # step 3 whole
    assert "※" not in text


def test_evidence_over_budget_marks_what_it_cut():
    services = cast(Any, _services())
    text = asyncio.run(
        reporter.collect_evidence(services, "e", None, max_chars=3000)
    )
    assert "mean 1.998321" in text  # step 2 is short: whole, unmarked
    assert "※ 일부만 표시(출력 2,000/" in text
    small = asyncio.run(
        reporter.collect_evidence(services, "e", None, max_chars=200)
    )
    assert "※ Step 3: 분량 제한으로 생략" in small


# --- writing ----------------------------------------------------------------


def test_whole_evidence_takes_one_call(monkeypatch):
    model = _model(AIMessage("# 수율\n평균 1.998, 988건"))
    _use(monkeypatch, model)
    sent = []
    ctx = _ctx(sent)
    markdown = _write(ctx, "mean 1.998321\ncount 988")
    assert markdown == "# 수율\n평균 1.998, 988건"
    assert sent == []  # no tool calls, no report text in the chat
    assert not model.bound  # nothing to re-read: no read_step to call


def test_trimmed_evidence_is_detected():
    assert not reporter.trimmed("mean 1.998321\n※ 참고: 단위는 nm")
    assert reporter.trimmed(
        "※ 일부만 표시(출력 2,000/9,000자). read_step으로 전체를 읽으세요."
    )
    assert reporter.trimmed(
        "※ Step 4, 5: 분량 제한으로 생략. read_step으로 읽으세요."
    )


def test_marked_steps_are_read_in_one_call(monkeypatch):
    model = _model(
        _call("read_step", {"sequences": [2, 3]}, "c1"),
        AIMessage("# 수율\n표준편차 0.1427, 988건"),
    )
    _use(monkeypatch, model)
    sent = []
    ctx = _ctx(sent)
    markdown = _write(
        ctx,
        "※ 일부만 표시(출력 2,000/9,000자). read_step으로 전체를 읽으세요.",
    )
    assert model.bound == ["read_step"]
    assert markdown.endswith("0.1427, 988건")
    assert ctx.services.executor.results == 1
    calls = [d for t, d in sent if t == "tool_call"]
    assert [c["label"] for c in calls] == ["Step 2, 3 결과 확인"]


def test_report_text_does_not_reach_the_chat():
    from agent.context import ReportContext

    sent = []

    async def send(type, data, durable=True):
        sent.append(type)

    ctx = ReportContext(
        services=cast(Any, None), execution_id="e", model="m", send=send
    )
    asyncio.run(ctx.emit("token", {"text": "# 리포트"}))
    asyncio.run(ctx.emit("tool_call", {"name": "read_step"}))
    assert sent == ["tool_call"]


def test_request_carries_the_project_and_the_overview():
    ctx = SimpleNamespace(
        services=SimpleNamespace(memory=_Memory()),
        project_id="p",
        project_prompt="수율은 소수 첫째 자리까지",
        user_text="수율 분석",
    )
    text = asyncio.run(
        reporter.analysis_request(
            cast(Any, ctx), title="t", focus="이상 lot", evidence="### Step 0"
        )
    )
    for part in ("수율 분석", "이상 lot", "소수 첫째", "- 표 위주"):
        assert part in text
    assert text.endswith("### Step 0")


def test_defaults():
    settings = Settings()
    assert settings.report_model_call_limit == 8
    assert settings.report_evidence_max_chars == 60000

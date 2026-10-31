"""The analysis report of write_report is written by the report agent."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from langchain_core.language_models.fake_chat_models import (
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage

from agent import report_agent, reporter
from core.config import Settings


class _ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


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
                            "sequence": 2,
                            "lineage": {},
                            "result": {
                                "status": "SUCCEEDED",
                                "result_ref": {"path": "s2"},
                            },
                        }
                    ]
                }
            ]
        }


class _Storage:
    def read_step_outputs(self, ref, max_chars):
        return {"available": True, "text": "yield 97.3%"}

    def step_source(self, ref):
        return "df.mean()"


class _Memory:
    async def contents(self, project_id):
        return [{"topic": "preferences", "content": "- 표 위주"}]


def test_agent_reads_a_step_and_hands_in_the_report(monkeypatch):
    model = _ToolModel(
        messages=iter(
            [
                _call("read_step", {"sequence": 2}, "c1"),
                _call(
                    "submit_report",
                    {
                        "title": "다른 제목",
                        "markdown": "# 수율 97.3%",
                        "summary": "수율 97.3%",
                    },
                    "c2",
                ),
            ]
        ),
        disable_streaming=True,
    )
    monkeypatch.setattr(report_agent, "chat_model", lambda s, n: model)
    reporter._analysis_agents.clear()
    sent: list[tuple[str, dict]] = []

    async def emit(type, data, durable=True):
        sent.append((type, data))

    executor = _Executor()
    ctx = SimpleNamespace(
        services=SimpleNamespace(
            settings=Settings(),
            executor=executor,
            storage=_Storage(),
            memory=_Memory(),
        ),
        project_id="p",
        project_prompt="",
        user_text="수율 분석",
        model="m",
        emit=emit,
    )
    markdown = asyncio.run(
        reporter.generate_report(
            cast(Any, ctx), "exe-1", title="수율", focus="f", evidence="개요"
        )
    )
    assert markdown == "# 수율 97.3%"
    assert executor.results == 1
    calls = [d["name"] for t, d in sent if t == "tool_call"]
    assert calls == ["read_step"]  # submit_report stays quiet


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
    for part in (
        "수율 분석",
        "이상 lot",
        "소수 첫째",
        "- 표 위주",
        "### Step 0",
    ):
        assert part in text


def test_report_call_limit_default():
    assert Settings().report_model_call_limit == 8

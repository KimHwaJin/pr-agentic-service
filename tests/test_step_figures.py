"""Step figures reach a vision model only; a text model's requests stay."""

import asyncio
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from PIL import Image

from agent import batch as batch_agent
from agent import reporter
from agent.middleware import persona, summarization
from core import figures, images
from core.config import ModelSpec, Settings
from core.executor.storage import SharedStorage

VISION = ModelSpec(
    name="vlm", input=["text", "image"], max_images=8, default=True
)
TEXT = ModelSpec(name="llm")


def _settings(**values) -> Settings:
    return Settings(models=[VISION, TEXT], **values)


def _png(width=64, height=32, format="PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format=format)
    return out.getvalue()


@pytest.fixture
def storage(tmp_path: Path) -> SharedStorage:
    root = tmp_path / "results"
    for name in ("a1.png", "a2.png", "a3.png", "b1.png"):
        (root / "exe").mkdir(parents=True, exist_ok=True)
        (root / "exe" / name).write_bytes(_png())
    return SharedStorage(tmp_path / "in", "in", root)


# --- limits and choice ---


def test_only_a_vision_model_gets_figures():
    settings = _settings()
    assert figures.limit(settings, "llm", 6) == 0
    assert figures.limit(settings, "unknown", 6) == 0
    assert figures.limit(settings, "vlm", 6) == 6
    assert figures.limit(settings, "vlm", 0) == 0  # turned off
    assert figures.limit(settings, "vlm", 20) == 8  # the model's MAX_IMAGES


def test_figures_are_spread_over_the_steps():
    steps = [("Step 1", ["a1", "a2", "a3"]), ("Step 2", ["b1"])]
    assert figures.pick(steps, 10) == [
        ("Step 1 그림 1", "a1"),
        ("Step 2 그림 1", "b1"),
        ("Step 1 그림 2", "a2"),  # at most PER_STEP of one step
    ]
    assert figures.pick(steps, 1) == [("Step 1 그림 1", "a1")]


def test_a_big_figure_is_shrunk_and_other_formats_become_png():
    big = images.fit_file(_png(4000, 1000))
    assert max(big.width, big.height) == images.MAX_SIDE
    gif = images.fit_file(_png(10, 10, format="GIF"))
    assert gif.mime_type == "image/png"
    with pytest.raises(images.ImageError):
        images.fit_file(b"not an image")


def test_an_unreadable_figure_is_left_out(storage):
    loaded = figures.load(
        storage,
        [("ok", "exe/a1.png"), ("gone", "exe/none.png"), ("out", "../x.png")],
    )
    assert [f.label for f in loaded] == ["ok"]
    assert figures.blocks(loaded)[0] == {"type": "text", "text": "[ok]"}
    assert figures.blocks(loaded)[1]["type"] == "image"


# --- reports ---


class _Executor:
    def __init__(self):
        self.calls = 0

    async def result(self, execution_id):
        self.calls += 1
        return {
            "operations": [
                {
                    "steps": [
                        {
                            "sequence": 1,
                            "lineage": {
                                "skill_name": "eda",
                                "tool_name": "box",
                            },
                            "result": {"result_ref": {"step": 1}},
                        }
                    ]
                }
            ]
        }


class _Storage:
    def __init__(self, real: SharedStorage):
        self.real = real

    def read_step_outputs(self, ref, max_chars):
        return {"available": True, "text": "", "images": ["exe/a1.png"]}

    def step_source(self, ref):
        return ""

    def resolve_result(self, path):
        return self.real.resolve_result(path)


class _Memory:
    async def contents(self, project_id):
        return []


def _report_request(storage, model: str) -> tuple[Any, _Executor]:
    executor = _Executor()
    services = SimpleNamespace(
        settings=_settings(),
        executor=executor,
        storage=_Storage(storage),
        memory=_Memory(),
    )
    seen: list[Any] = []

    class Agent:
        async def write(self, ctx, request, title, can_read):
            seen.append(request)
            return {"markdown": "# 리포트"}

    async def emit(*args, **kwargs):
        pass

    ctx = SimpleNamespace(
        services=services,
        project_id="p",
        project_prompt="",
        user_text="분석",
        model=model,
        emit=emit,
    )
    original = reporter.analysis_agent
    reporter.analysis_agent = lambda settings: Agent()
    try:
        asyncio.run(
            reporter.generate_report(
                cast(Any, ctx), "exe-1", title="t", focus="f", evidence="e"
            )
        )
    finally:
        reporter.analysis_agent = original
    return seen[0], executor


def test_a_text_model_report_request_is_unchanged(storage):
    request, executor = _report_request(storage, "llm")
    assert isinstance(request, str)
    assert executor.calls == 0  # nothing read for figures


def test_a_vision_model_report_sees_the_figures(storage):
    request, _ = _report_request(storage, "vlm")
    assert isinstance(request, list)
    assert request[1]["text"] == reporter.FIGURES_NOTE
    assert {"type": "text", "text": "[Step 1 eda/box 그림 1]"} in request
    assert request[-1]["type"] == "image"


@pytest.mark.parametrize(("model", "count"), [("llm", 0), ("vlm", 6)])
def test_batch_reports_follow_their_model(monkeypatch, model, count):
    asked: list[int] = []

    async def evidence(services, execution_id, plan):
        return "### Step 0 code — SUCCEEDED"

    async def collect(services, execution_id, n):
        asked.append(n)
        return []

    monkeypatch.setattr(batch_agent, "collect_evidence", evidence)
    monkeypatch.setattr(batch_agent, "collect_figures", collect)
    settings = _settings()
    writer = batch_agent.BatchReportAgent(settings)
    seen: list[Any] = []

    class Agent:
        async def write(self, ctx, request, title, can_read):
            seen.append(request)
            return {}

    writer.agent = cast(Any, Agent())

    @contextlib.asynccontextmanager
    async def activity(kind):
        yield

    ctx = SimpleNamespace(
        services=SimpleNamespace(settings=settings),
        execution_id="exe",
        model=model,
        activity=activity,
    )
    asyncio.run(writer.write(cast(Any, ctx), {}, []))
    assert asked == [count]
    assert isinstance(seen[0], str)  # no figures: the text request


# --- analysis turns ---


def _run_ctx(storage, model: str) -> Any:
    return SimpleNamespace(
        services=SimpleNamespace(settings=_settings(), storage=storage),
        model=model,
    )


def _tool_result(figures_=None) -> list:
    return [
        HumanMessage("분석해줘"),
        AIMessage(
            "", tool_calls=[{"name": "run_plan", "args": {}, "id": "c1"}]
        ),
        ToolMessage(
            "{}",
            tool_call_id="c1",
            artifact={"figures": figures_} if figures_ else None,
        ),
    ]


def test_the_analyst_sees_the_latest_figures_once(storage):
    messages = _tool_result(
        [["#1 box", "exe/a1.png"], ["#1 box", "exe/a2.png"]]
    )
    ctx = _run_ctx(storage, "vlm")
    out = asyncio.run(persona._with_figures(messages, ctx))
    assert out[:3] == messages
    added = out[3]
    assert isinstance(added, HumanMessage)
    assert added.content[0]["text"] == persona.FIGURES_NOTE
    assert [b["type"] for b in added.content[1:]] == [
        "text",
        "image",
        "text",
        "image",
    ]
    # once the model has answered them, they are not sent again
    later = [*messages, AIMessage("다음 Step")]
    assert asyncio.run(persona._with_figures(later, ctx)) == later


def test_a_text_analyst_gets_no_figures(storage):
    messages = _tool_result([["#1 box", "exe/a1.png"]])
    out = asyncio.run(
        persona._with_figures(messages, _run_ctx(storage, "llm"))
    )
    assert out == messages


def test_tool_figures_can_be_turned_off(storage):
    messages = _tool_result([["#1 box", "exe/a1.png"]])
    ctx = _run_ctx(storage, "vlm")
    ctx.services.settings = Settings(models=[VISION], agent_tool_images=0)
    assert asyncio.run(persona._with_figures(messages, ctx)) == messages


# --- summarization ---


def test_images_count_their_real_size_for_a_vision_model_only():
    settings = _settings(image_tokens=1500)
    text = summarization.summary_token_counter(settings, "llm")
    assert text is count_tokens_approximately  # LangChain's, unchanged
    vision = summarization.summary_token_counter(settings, "vlm")
    message = [
        HumanMessage(
            [{"type": "image", "file_id": "i1", "mime_type": "image/png"}]
        )
    ]
    assert vision(message) - count_tokens_approximately(message) == 1500 - 85

"""A registered static workflow runs as written: one SINGLE execution, no
revised args, no custom code, no second run, no report after a failure."""

import asyncio
from types import SimpleNamespace
from typing import Any

from agent.tools import analysis
from core.workflows import spec


def _plan(static, mode="static", statuses=None) -> dict[str, Any]:
    keys = [c.key for c in spec.calls(static)]
    statuses = statuses or ["pending"] * len(keys)
    return {
        "id": "plan-1",
        "title": "NCE",
        "document": static,
        "input_values": {},
        "source": {"workflow_id": "w-1"},
        "calls": {
            k: {"status": s} for k, s in zip(keys, statuses, strict=True)
        },
        "custom": [],
        "mode": mode,
    }


class Executor:
    def __init__(self):
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def finalize(self, execution_id, **kwargs):
        self.sent.append(("finalize", {"id": execution_id, **kwargs}))
        return {}

    async def submit(self, **kwargs):
        self.sent.append(("submit", kwargs))
        return {
            "execution_id": "ex-new",
            "state": {"version": 1},
            "operation": {
                "operation_id": "op-1",
                "steps": [
                    {"sequence": s["sequence"], "step_id": f"st-{i}"}
                    for i, s in enumerate(kwargs["steps"])
                ],
            },
        }

    async def append_operation(self, *args, **kwargs):
        raise AssertionError("a SINGLE execution takes no operation")


class Sources:
    async def write(self, code, **kwargs):
        return {"path": kwargs["relative"]}

    async def link(self, receipt, paths):
        return None


def _runtime(state: dict[str, Any], executor=None, code_level=3):
    settings = SimpleNamespace(
        executor_step_timeout_seconds=None,
        executor_runtime_profile="default",
        executor_operation_wait_seconds=1800,
    )
    services = SimpleNamespace(
        settings=settings,
        executor=executor or Executor(),
        code_sources=Sources(),
    )
    context = SimpleNamespace(
        services=services,
        run_id="run-1",
        user_id="u-1",
        project_id="p-1",
        session_id="s-1",
        code_level=code_level,
    )
    return SimpleNamespace(
        state={"messages": [], **state},
        context=context,
        tool_call_id="call-1",
        store=None,
    )


def _text(command) -> str:
    return command.update["messages"][-1].content


def test_mode_of_a_plan(static, adaptive):
    assert analysis.plan_mode({"workflow_id": "w"}, static) == "static"
    assert analysis.plan_mode({"workflow_id": "w"}, adaptive) == "adaptive"
    # the agent's own plan keeps today's behaviour, even all-always
    assert analysis.plan_mode(None, static) == "agent"


def test_static_args_are_not_revised(static):
    runtime = _runtime({"plan": _plan(static)})
    result = asyncio.run(
        analysis.revise_call.coroutine(
            call="1", new_args={"data": "@0.data"}, runtime=runtime
        )
    )
    assert _text(result) == analysis.STATIC_FAILED


def test_a_failed_static_plan_is_not_run_again(static):
    count = len(spec.calls(static))
    plan = _plan(
        static, statuses=["succeeded", "failed"] + ["pending"] * (count - 2)
    )
    executor = Executor()
    runtime = _runtime({"plan": plan}, executor)
    for restart in (False, True):
        result = asyncio.run(
            analysis.run_plan.coroutine(runtime=runtime, restart=restart)
        )
        assert _text(result) == analysis.STATIC_FAILED
    assert executor.sent == []


def test_a_finished_static_plan_goes_to_the_report(static):
    plan = _plan(static, statuses=["succeeded"] * len(spec.calls(static)))
    result = asyncio.run(
        analysis.run_plan.coroutine(runtime=_runtime({"plan": plan}))
    )
    assert "write_report" in _text(result)


def test_static_opens_a_single_execution_and_closes_the_live_kernel():
    executor = Executor()
    live = {
        "id": "ex-old",
        "user_id": "u-1",
        "version": 4,
        "next_sequence": 3,
        "alive": True,
        "steps": {},
    }
    runtime = _runtime({"execution": live}, executor)
    steps = [{"payload": {"source": {"path": "a.py"}}}]
    receipt, execution = asyncio.run(
        analysis._submit_now(runtime, steps, ["0.0"], "01-run_plan", True)
    )
    kinds = [kind for kind, _ in executor.sent]
    assert kinds == ["finalize", "submit"]
    assert executor.sent[0][1]["id"] == "ex-old"
    assert executor.sent[1][1]["wait_seconds"] is None  # SINGLE
    assert execution["id"] == "ex-new"


def test_multi_stays_for_other_plans():
    executor = Executor()
    runtime = _runtime({}, executor)
    steps = [{"payload": {"source": {"path": "a.py"}}}]
    asyncio.run(analysis._submit_now(runtime, steps, ["0.0"], "01-run_plan"))
    assert executor.sent[0][1]["wait_seconds"] == 1800


def test_a_single_completion_leaves_no_kernel():
    execution = {"id": "ex", "alive": True, "version": 1}
    event = {
        "event_type": "execution.operation_completed",
        "payload": {"status": "SUCCEEDED", "continuation": None},
    }
    after, _, _ = analysis._apply_event(execution, event)
    assert after["alive"] is False


def test_no_custom_code_on_a_static_workflow(static):
    runtime = _runtime({"plan": _plan(static)})
    result = asyncio.run(
        analysis.run_custom_code.coroutine(
            code="print(1)", purpose="x", runtime=runtime
        )
    )
    assert "static" in _text(result)


def test_custom_code_is_free_again_after_the_report(static):
    plan = {**_plan(static), "reported": True}
    runtime = _runtime({"plan": plan})
    result = None
    try:
        result = asyncio.run(
            analysis.run_custom_code.coroutine(
                code="print(1)", purpose="x", runtime=runtime
            )
        )
    except Exception:  # reached the approval interrupt (no graph here)
        pass
    assert result is None or "static" not in _text(result)


def test_no_report_after_a_static_failure(static):
    count = len(spec.calls(static))
    plan = _plan(static, statuses=["failed"] + ["pending"] * (count - 1))
    runtime = _runtime(
        {"plan": plan, "execution": {"id": "ex", "alive": False}}
    )
    result = asyncio.run(
        analysis.write_report.coroutine(title="t", focus="f", runtime=runtime)
    )
    assert _text(result) == analysis.STATIC_FAILED

"""Tools of the analyst agent.

Plan = Workflow 1.0 document + run bindings, kept in graph state:
    {"id", "title", "document", "input_values": {"s.t.param": value}, "source": {...} | None,
     "calls": {"s.t": {"status": pending|succeeded|failed|skipped, "reason"?, "step_id"?}},
     "custom": [{"id", "purpose", "status", "step_id"}]}
Execution = the session's executor MULTI execution (one kernel, one notebook):
    {"id", "version", "next_sequence", "alive": bool, "steps": {step_id: label}}

Every executor mutation uses an idempotency key derived from (run_id, tool_call_id), so when
LangGraph replays a tool after an interrupt or a pod crash the executor returns the same receipt.
"""

import json
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command, interrupt

from agent import plan_format
from agent.codegen import custom_step_code, parse_observations, tool_step_code
from agent.context import AnalysisState, RunContext
from agent.reporter import collect_evidence, generate_report
from core.db import new_id
from core.executor.client import ExecutorError
from core.workflows import spec
from core.workflows.service import WorkflowError


def _reply(runtime: ToolRuntime, content: str, **update: Any) -> Command:
    return Command(update={**update, "messages": [ToolMessage(content, tool_call_id=runtime.tool_call_id)]})


def _key(runtime: ToolRuntime, suffix: str) -> str:
    return f"{runtime.context.run_id}:{runtime.tool_call_id}:{suffix}"


# --- catalog -------------------------------------------------------------------------------


@tool
async def read_skill(name: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> str:
    """Read an analysis skill: what it is for, its tools and when each tool runs (always/conditional)."""
    services = runtime.context.services
    skill = services.skills("analysis").skills.get(name)
    if skill is None:
        return f"'{name}' skill이 없습니다."
    tools = services.tool_catalog()
    signatures = "\n\n".join(tools.describe(t.tool) for t in skill.tools if t.tool in tools.tools)
    return f"{skill.body}\n\n## Tool signatures\n\n{signatures}"


@tool
async def read_tool(name: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> str:
    """Read one tool's signature, outputs and docstring."""
    tools = runtime.context.services.tool_catalog()
    return tools.describe(name) if name in tools.tools else f"'{name}' tool이 없습니다."


@tool
async def search_tools(query: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> str:
    """Find tools whose name or docstring mentions the query words."""
    words = [w.lower() for w in query.split() if w]
    tools = runtime.context.services.tool_catalog().tools.values()
    hits = [t for t in tools if any(w in f"{t.name} {t.docstring}".lower() for w in words)]
    return (
        "\n".join(f"- {t.name} ({t.category}): {t.docstring.splitlines()[0] if t.docstring else ''}" for t in hits)
        or "없음"
    )


@tool
async def search_workflows(query: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> str:
    """Search registered (promoted) workflow templates similar to the user's request."""
    ctx = runtime.context
    hits = await ctx.services.workflows.search(query, limit=ctx.services.settings.plan_candidates)
    if not hits:
        return "추천할 워크플로우가 없습니다. 새로 계획하세요."
    lines = []
    for h in hits:
        w = h["workflow"]
        calls = json.dumps(plan_format.describe(w.document), ensure_ascii=False)
        lines.append(
            f"- workflow_id={w.id} similarity={h['similarity']} name={w.name}\n"
            f"  user_request: {w.user_request}\n  calls: {calls}"
        )
    return "\n".join(lines)


# --- planning ------------------------------------------------------------------------------


@tool
async def propose_plans(candidates: list[dict[str, Any]], runtime: ToolRuntime[RunContext, AnalysisState]) -> Command:
    """Show plan candidates to the user and wait for one to be approved.

    Each candidate is either a registered template or a new plan written as a flat call list:
      {"title": "...", "rationale": "...", "workflow_id": "<id from search_workflows>", "inputs": {...}}
      {"title": "...", "rationale": "...", "calls": [
          {"skill": "data_load", "tool": "extract_data", "args": {"data_type": "$input", "limit": 5000}},
          {"skill": "data_load", "tool": "transform_nce", "args": {"data": "@0.data"}},
          {"skill": "eda_analysis", "tool": "boxplot_eda", "args": {"data": "@1.data"}}],
       "inputs": {"0.data_type": "nce"}}
    args values: "$input" = value the user provides, "@<call index>.<output name>" = an earlier call's output,
    anything else = a fixed value. Leave out args that should keep the tool default.
    inputs prefill "$input" args as "<call index>.<param>" with what the user already said.
    Templates first, then new plans; at most the configured number of candidates.
    """
    ctx = runtime.context
    services = ctx.services
    skills, tools = services.skills("analysis"), services.tool_catalog()
    prepared, problems = [], []
    for index, candidate in enumerate(candidates[: services.settings.plan_candidates]):
        title = candidate.get("title") or f"계획 {index + 1}"
        source = None
        try:
            if workflow_id := candidate.get("workflow_id"):
                template = await services.workflows.readable(workflow_id, ctx.user_id)
                document = template.document
                keys = [c.key for c in spec.calls(document)]
                source = {"workflow_id": template.id, "revision": template.revision, "name": template.name}
            else:
                document, keys = plan_format.to_workflow(
                    candidate.get("calls") or [], name=title, user_request=ctx.user_text, skills=skills
                )
        except (plan_format.PlanFormatError, WorkflowError) as exc:
            problems.append(f"후보 {index} ({title}): {exc}")
            continue
        errors = spec.validate(document, skills, tools)
        if errors:
            problems.append(f"후보 {index} ({title}):\n  " + "\n  ".join(_by_call_index(errors, keys)))
            continue
        document = spec.normalize(document)
        slots = spec.input_slots(document, tools)
        values = {
            k: v
            for k, v in plan_format.input_keys(candidate.get("inputs") or {}, keys).items()
            if k in {s["key"] for s in slots}
        }
        prepared.append(
            {
                "title": title,
                "rationale": candidate.get("rationale", ""),
                "source": source,
                "document": document,
                "input_slots": [s | {"value": values.get(s["key"])} for s in slots],
                "input_values": values,
            }
        )
    if problems:
        return _reply(runtime, "계획 검증 실패. 해당 후보만 고쳐 다시 제안하세요.\n" + "\n".join(problems))
    if not prepared:
        return _reply(runtime, "제안할 계획이 없습니다.")

    first = prepared[0]
    missing = [s["key"] for s in first["input_slots"] if s["required"] and s["value"] is None]
    if first["source"] and first["document"]["workflow"]["allow_immediate_execution"] and not missing:
        choice = {"action": "approve", "index": 0, "input_values": first["input_values"]}
        await ctx.emit("plan_auto_approved", {"title": first["title"], "source": first["source"]})
    else:
        choice = interrupt({"type": "plan_approval", "candidates": prepared})

    if not isinstance(choice, dict) or choice.get("action") == "cancel":
        return _reply(runtime, "사용자가 계획을 취소했습니다. 이유를 묻거나 분석을 종료하세요.")
    if choice.get("action") == "revise":
        return _reply(runtime, f"사용자가 계획 수정을 요청했습니다: {choice.get('feedback', '')}")
    chosen = prepared[int(choice.get("index", 0))]
    values = {**chosen["input_values"], **(choice.get("input_values") or {})}
    missing = [s["key"] for s in chosen["input_slots"] if s["required"] and values.get(s["key"]) is None]
    if missing:
        return _reply(runtime, f"필수 입력값이 비어 있습니다: {missing}. ask_user로 받은 뒤 다시 제안하세요.")
    plan = {
        "id": new_id(),
        "title": chosen["title"],
        "document": chosen["document"],
        "input_values": values,
        "source": chosen["source"],
        "calls": {c.key: {"status": "pending"} for c in spec.calls(chosen["document"])},
        "custom": [],
    }
    await ctx.emit("plan_approved", {"plan_id": plan["id"], "title": plan["title"], "document": plan["document"]})
    calls = ", ".join(f"#{i} {c.tool}" for i, c in enumerate(spec.calls(plan["document"])))
    return _reply(runtime, f"계획 승인됨: {plan['title']} ({calls}). run_plan으로 실행하세요.", plan=plan)


def _by_call_index(errors: list[str], keys: list[str]) -> list[str]:
    """Validation speaks steps[s].tools[t]; the model wrote call numbers."""
    index = {f"steps[{k.split('.')[0]}].tools[{k.split('.')[1]}]": f"calls[{i}]" for i, k in enumerate(keys)}
    out = []
    for error in errors:
        for where, call in index.items():
            error = error.replace(where, call)
        out.append(error)
    return out


def _call_key(plan: dict[str, Any], ref: str | int) -> str | None:
    """Calls are numbered in plan order (#0, #1, ...) for the model; "<step>.<tool>" also works."""
    order = [c.key for c in spec.calls(plan["document"])]
    ref = str(ref).lstrip("#")
    if ref.isdigit():
        return order[int(ref)] if int(ref) < len(order) else None
    return ref if ref in order else None


@tool
async def revise_call(call: str, args: dict[str, Any], runtime: ToolRuntime[RunContext, AnalysisState]) -> Command:
    """Repair a failed or pending call of the approved plan by replacing its args.

    call: the call number from the plan ("#2" or "2"). args: same notation as propose_plans
    ("$input", "@<call>.<output>", or a fixed value). A fixed value replaces an input the user gave.
    """
    plan = runtime.state.get("plan")
    if not plan:
        return _reply(runtime, "승인된 계획이 없습니다.")
    key = _call_key(plan, call)
    if key is None:
        return _reply(runtime, f"{call}번 호출이 없습니다.")
    if plan["calls"][key]["status"] == "succeeded":
        return _reply(runtime, f"#{call}은 이미 성공했습니다. 새 계획을 제안하세요.")
    order = [c.key for c in spec.calls(plan["document"])]
    position = order.index(key)
    try:
        arguments = {p: plan_format._argument(v, position, order, p) for p, v in args.items()}
    except plan_format.PlanFormatError as exc:
        return _reply(runtime, f"수정안 형식 오류: {exc}")
    document = json.loads(json.dumps(plan["document"]))
    si, ti = (int(x) for x in key.split("."))
    document["workflow"]["steps"][si]["tools"][ti]["arguments"] = arguments
    services = runtime.context.services
    errors = spec.validate(document, services.skills("analysis"), services.tool_catalog())
    if errors:
        return _reply(runtime, "수정안 검증 실패:\n" + "\n".join(_by_call_index(errors, order)))
    values = {
        k: v
        for k, v in plan["input_values"].items()
        if not k.startswith(key + ".") or arguments.get(k[len(key) + 1 :], {}).get("source") == "input"
    }
    plan = {
        **plan,
        "document": document,
        "input_values": values,
        "calls": {**plan["calls"], key: {"status": "pending"}},
    }
    await runtime.context.emit("plan_revised", {"call": position, "args": args})
    return _reply(runtime, f"#{position} 인자를 수정했습니다. run_plan으로 다시 실행하세요.", plan=plan)


# --- execution -----------------------------------------------------------------------------


def _segment(plan: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> tuple[list[spec.Call], list[str]]:
    """Next calls to run, stopping before an undecided conditional call."""
    calls = spec.calls(plan["document"])
    states = plan["calls"]
    skipped = {k for k, v in states.items() if v["status"] == "skipped"}
    for key, decision in decisions.items():
        if key in states and states[key]["status"] == "pending" and not decision.get("run", True):
            states[key] = {"status": "skipped", "reason": decision.get("reason", "")}
            skipped.add(key)
    segment: list[spec.Call] = []
    for call in calls:
        state = states[call.key]
        if state["status"] in {"succeeded", "skipped"}:
            continue
        depends = {
            f"{a['step_index']}.{a['tool_index']}" for a in call.arguments.values() if a["source"] == "tool_output"
        }
        if depends & skipped:
            states[call.key] = {"status": "skipped", "reason": "선행 조건부 호출이 생략됨"}
            skipped.add(call.key)
            continue
        if call.execution == "conditional" and call.key not in decisions:
            break  # the agent decides after reading earlier results
        segment.append(call)
    undecided = [
        c.key
        for c in calls
        if c.execution == "conditional" and states[c.key]["status"] == "pending" and c.key not in decisions
    ]
    return segment, undecided


async def _once(runtime: ToolRuntime, name: str, effect) -> Any:
    """Run an executor side effect once per tool call.

    LangGraph re-executes a tool from the top when it resumes after an interrupt; the recorded
    result is returned instead of calling the executor again (whose state has moved on).
    """
    namespace, key = ("tool_effects", runtime.context.run_id), f"{runtime.tool_call_id}:{name}"
    if (item := await runtime.store.aget(namespace, key)) is not None:
        return item.value["result"]
    result = await effect()
    await runtime.store.aput(namespace, key, {"result": result}, index=False)
    return result


async def _submit(runtime: ToolRuntime, steps: list[dict[str, Any]], labels: list[str]) -> tuple[dict, dict]:
    return tuple(await _once(runtime, "submit", lambda: _submit_now(runtime, steps, labels)))


async def _submit_now(runtime: ToolRuntime, steps: list[dict[str, Any]], labels: list[str]) -> list[dict]:
    """Append to the live execution or open a new MULTI execution; returns [receipt, execution]."""
    ctx = runtime.context
    settings = ctx.services.settings
    executor = ctx.services.executor
    execution = runtime.state.get("execution")
    if execution and execution.get("alive"):
        for i, step in enumerate(steps):
            step["sequence"] = execution["next_sequence"] + i
        try:
            receipt = await executor.append_operation(
                execution["id"], idempotency_key=_key(runtime, "op"), expected_version=execution["version"], steps=steps
            )
        except ExecutorError as exc:
            if exc.status not in (404, 409):
                raise
            execution = None  # wait expired / kernel gone: start over in a new execution
        else:
            execution = {**execution, "next_sequence": execution["next_sequence"] + len(steps)}
    if not execution or not execution.get("alive"):
        for i, step in enumerate(steps):
            step["sequence"] = i
        receipt = await executor.submit(
            idempotency_key=_key(runtime, "submit"),
            context={
                "user_id": ctx.employee_id,
                "task_id": ctx.run_id,
                "project_id": ctx.project_id,
                "session_id": ctx.session_id,
            },
            steps=steps,
            profile=settings.executor_runtime_profile,
            wait_seconds=settings.executor_operation_wait_seconds,
            metadata={"service": "pr-agentic-service"},
        )
        execution = {
            "id": receipt["execution_id"],
            "version": receipt["state"]["version"],
            "next_sequence": len(steps),
            "alive": True,
            "steps": {},
        }
    step_ids = {s["sequence"]: s["step_id"] for s in receipt["operation"]["steps"]}
    execution["steps"] = {
        **execution.get("steps", {}),
        **{step_ids[s["sequence"]]: label for s, label in zip(steps, labels, strict=True)},
    }
    return [receipt, execution]


def _wait_operation(execution: dict, receipt: dict) -> dict[str, Any]:
    """Pause until the executor reports the operation (the scheduler announces the wait)."""
    labels = [execution["steps"][s["step_id"]] for s in receipt["operation"]["steps"]]
    return interrupt(
        {
            "type": "executor_wait",
            "execution_id": execution["id"],
            "operation_id": receipt["operation"]["operation_id"],
            "steps": labels,
        }
    )


def _apply_event(execution: dict, event: dict[str, Any]) -> tuple[dict, dict[str, dict[str, Any]], str | None]:
    """Returns (execution, results by step_id, error)."""
    payload = event.get("payload", {})
    results = {r["step_id"]: r for r in payload.get("step_results", [])}
    error = (payload.get("error") or {}).get("message")
    if event.get("event_type") == "execution.operation_completed" and payload.get("continuation"):
        execution = {**execution, "version": payload["continuation"]["expected_version"], "alive": True}
    else:
        execution = {**execution, "alive": False}
    return execution, results, error


def _bounded(value: Any, limit: int = 1500) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(text) <= limit else text[:limit] + " ...(생략)"


def _step_view(runtime: ToolRuntime, result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {"status": "NOT_RUN"}
    view = runtime.context.services.storage.read_step_outputs(result.get("result_ref"))
    observations, text = parse_observations(view.get("text", ""))
    return {
        "status": result["status"],
        "observations": [_bounded(o) for o in observations],
        "stdout": text[-1500:],
        "images": view.get("images", []),
        "error": view.get("error"),
    }


@tool
async def run_plan(
    runtime: ToolRuntime[RunContext, AnalysisState], decisions: dict[str, dict[str, Any]] | None = None
) -> Command:
    """Run the next calls of the approved plan on the executor and wait for their results.

    Runs pending calls in order and stops before a conditional call you have not decided yet.
    decisions: {"<call number>": {"run": true|false, "reason": "..."}} for conditional calls, decided from
    the condition in the skill's Tool list and the condition_tool's results you already observed.
    """
    ctx = runtime.context
    plan = runtime.state.get("plan")
    if not plan:
        return _reply(runtime, "승인된 계획이 없습니다. propose_plans로 먼저 승인을 받으세요.")
    plan = json.loads(json.dumps(plan))
    decisions = {key: d for ref, d in (decisions or {}).items() if (key := _call_key(plan, ref))}
    number = {c.key: i for i, c in enumerate(spec.calls(plan["document"]))}
    execution = runtime.state.get("execution")
    if not (execution and execution.get("alive")):
        # A new kernel has none of the earlier variables: re-run everything that had succeeded.
        for state in plan["calls"].values():
            if state["status"] == "succeeded":
                state["status"] = "pending"
    segment, undecided = _segment(plan, decisions)
    if not segment:
        if undecided:
            pending = [f"#{number[k]}" for k in undecided]
            return _reply(runtime, f"조건부 호출 {pending}의 실행 여부를 decisions로 정해 주세요.", plan=plan)
        return _reply(runtime, "계획의 모든 호출이 끝났습니다. 결과를 해석하고 write_report를 호출하세요.", plan=plan)

    tools = ctx.services.tool_catalog()
    producers = {c.key: c.tool for c in spec.calls(plan["document"])}
    steps, labels = [], []
    for call in segment:
        code = tool_step_code(call, plan["input_values"], tools, producers)
        inputs = {k[len(call.key) + 1 :]: v for k, v in plan["input_values"].items() if k.startswith(call.key + ".")}
        steps.append(
            {
                "payload": {"type": "PYTHON_EXECUTE", "source": ctx.services.storage.write_source(code)},
                "step_timeout_seconds": ctx.services.settings.executor_step_timeout_seconds,
                "lineage": {"skill_name": call.skill, "tool_name": call.tool, "input_parameters": inputs},
            }
        )
        labels.append(call.key)
    receipt, execution = await _submit(runtime, steps, labels)
    event = _wait_operation(execution, receipt)
    execution, results, error = _apply_event(execution, event)

    by_label = {label: step_id for step_id, label in execution["steps"].items()}
    report: dict[str, Any] = {}
    for call in segment:
        step_id = by_label.get(call.key)
        view = _step_view(runtime, results.get(step_id))
        status = {"SUCCEEDED": "succeeded", "NOT_RUN": "pending"}.get(view["status"], "failed")
        plan["calls"][call.key] = {"status": status, "step_id": step_id}
        report[f"#{number[call.key]} {call.tool}"] = view
    await ctx.emit("execution_completed", {"execution_id": execution["id"], "results": report, "error": error})
    _, undecided = _segment(json.loads(json.dumps(plan)), {})
    summary = {
        "results": report,
        "operation_error": error,
        "kernel_alive": execution["alive"],
        "remaining_conditional_calls": [f"#{number[k]}" for k in undecided],
        "pending_calls": [f"#{number[k]}" for k, v in plan["calls"].items() if v["status"] == "pending"],
    }
    return _reply(runtime, json.dumps(summary, ensure_ascii=False, default=str), plan=plan, execution=execution)


@tool
async def run_custom_code(
    code: str, purpose: str, runtime: ToolRuntime[RunContext, AnalysisState], observe: list[str] | None = None
) -> Command:
    """Run Python you wrote yourself in the same kernel (after the user approves the code).

    Allowed by the session's code level only (2: glue code between tools, 3: new functions when no tool
    fits or to fill a failure, 4: anything). Earlier tool results are kernel variables named
    _r_s<step>_t<tool>. observe: variable names whose value summary you want back.
    """
    ctx = runtime.context
    if ctx.code_level < 2:
        return _reply(
            runtime, "현재 코드 레벨(1)에서는 직접 작성한 코드를 실행할 수 없습니다. 등록된 tool만 사용하세요."
        )
    answer = interrupt({"type": "code_approval", "purpose": purpose, "code": code, "code_level": ctx.code_level})
    if not (isinstance(answer, dict) and answer.get("approve")):
        return _reply(
            runtime,
            f"사용자가 코드 실행을 거절했습니다. {answer.get('feedback', '') if isinstance(answer, dict) else ''}",
        )
    code = answer.get("code") or code
    plan = json.loads(json.dumps(runtime.state.get("plan") or {"custom": [], "calls": {}}))
    custom_id = f"custom-{len(plan.get('custom', [])) + 1}"
    step = {
        "payload": {
            "type": "PYTHON_EXECUTE",
            "source": ctx.services.storage.write_source(custom_step_code(code, observe or [])),
        },
        "step_timeout_seconds": ctx.services.settings.executor_step_timeout_seconds,
        "lineage": {"skill_name": "custom", "tool_name": custom_id, "input_parameters": {"purpose": purpose}},
    }
    receipt, execution = await _submit(runtime, [step], [custom_id])
    event = _wait_operation(execution, receipt)
    execution, results, error = _apply_event(execution, event)
    step_id = receipt["operation"]["steps"][0]["step_id"]
    view = _step_view(runtime, results.get(step_id))
    plan.setdefault("custom", []).append(
        {"id": custom_id, "purpose": purpose, "code": code, "status": view["status"], "step_id": step_id}
    )
    await ctx.emit(
        "execution_completed", {"execution_id": execution["id"], "results": {custom_id: view}, "error": error}
    )
    body = json.dumps({"result": view, "kernel_alive": execution["alive"]}, ensure_ascii=False, default=str)
    return _reply(runtime, body, plan=plan, execution=execution)


# --- wrap-up -------------------------------------------------------------------------------


@tool
async def write_report(title: str, focus: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> Command:
    """Finish the analysis: finalize the notebook, write the report and publish both.

    Call once the user's question is answered by successful results. focus: what the report should
    emphasise. After this the kernel is closed; a follow-up analysis starts a new execution.
    """
    ctx = runtime.context
    executor = ctx.services.executor
    execution = runtime.state.get("execution")
    plan = runtime.state.get("plan")
    if not execution:
        return _reply(runtime, "실행된 분석이 없습니다.")
    if execution.get("alive"):
        await _once(
            runtime,
            "finalize",
            lambda: executor.finalize(
                execution["id"], idempotency_key=_key(runtime, "finalize"), expected_version=execution["version"]
            ),
        )
        event = interrupt(
            {"type": "executor_wait", "execution_id": execution["id"], "operation_id": None, "steps": ["finalize"]}
        )
        status = event.get("payload", {}).get("status")
    else:
        status = (await executor.get(execution["id"]))["state"]["status"]
    closed = {**execution, "alive": False}
    if status != "SUCCEEDED":
        return _reply(
            runtime, f"노트북 확정에 실패했습니다(상태 {status}). 결과를 채팅으로 정리해 전달하세요.", execution=closed
        )

    evidence = await collect_evidence(ctx.services, execution["id"], plan)
    markdown = await generate_report(ctx, title=title, focus=focus, evidence=evidence)
    artifact = await executor.create_report(
        execution["id"],
        idempotency_key=_key(runtime, "report"),
        markdown=markdown,
        name="final-report.md",
        metadata={"title": title, "session_id": ctx.session_id, "run_id": ctx.run_id},
    )
    notebook = next((a for a in await executor.artifacts(execution["id"]) if a["type"] == "NOTEBOOK"), None)
    links = {"report": artifact["artifact_id"], "notebook": notebook["artifact_id"] if notebook else None}
    await ctx.emit("artifact", {"kind": "report", "artifact_id": links["report"], "title": title})
    if links["notebook"]:
        await ctx.emit("artifact", {"kind": "notebook", "artifact_id": links["notebook"], "title": f"{title} 노트북"})
    reports = [*runtime.state.get("reports", []), {"title": title, "execution_id": execution["id"], **links}]
    return _reply(
        runtime,
        f"리포트 게시 완료 (report={links['report']}, notebook={links['notebook']}).\n\n{markdown[:6000]}",
        execution=None,
        reports=reports,
    )


@tool
async def save_workflow(
    name: str, user_queries: list[str], runtime: ToolRuntime[RunContext, AnalysisState], tags: list[str] | None = None
) -> str:
    """Offer to save the approved plan as a reusable workflow (the user confirms and may edit).

    user_queries: example questions this workflow answers (start with the user's own request).
    Code you wrote yourself is not part of a workflow; only registered tool calls are saved.
    """
    ctx = runtime.context
    plan = runtime.state.get("plan")
    if not plan:
        return "저장할 계획이 없습니다."
    document = json.loads(json.dumps(plan["document"]))
    document["workflow"]["name"] = name
    excluded = len(plan.get("custom", []))
    answer = interrupt(
        {
            "type": "workflow_save",
            "name": name,
            "user_queries": user_queries,
            "tags": tags or [],
            "document": document,
            "excluded_custom_steps": excluded,
        }
    )
    if not (isinstance(answer, dict) and answer.get("approve")):
        return "사용자가 워크플로우 저장을 원하지 않습니다."
    document["workflow"]["name"] = answer.get("name") or name
    document["workflow"]["actor"] = {"type": "USER", "id": ctx.employee_id}
    workflow = await ctx.services.workflows.create(
        author_id=ctx.user_id,
        document=document,
        user_queries=answer.get("user_queries") or user_queries,
        tags=answer.get("tags") or tags or [],
        source_run_id=ctx.run_id,
    )
    await ctx.emit("workflow_saved", {"workflow_id": workflow.id, "name": workflow.name})
    note = f" Agent가 작성한 코드 {excluded}개는 제외했습니다." if excluded else ""
    return f"워크플로우 '{workflow.name}'를 저장했습니다(승격 전 candidate).{note}"


@tool
async def finish_analysis(summary: str, runtime: ToolRuntime[RunContext, AnalysisState]) -> Command:
    """Hand the conversation back to the main agent with a short summary of what was done and found."""
    await runtime.context.emit("agent_switched", {"agent": "main"})
    return _reply(runtime, f"분석 종료. 요약:\n{summary}", active_agent="main")

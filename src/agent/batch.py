"""Batch report agent: reads a finished BATCH execution and writes its report.

Runs straight from the report worker (worker.batch_reports), not through the
chat run queue: no session, no project, no checkpointer. A retry starts the
agent over. Previous runs of the same batch are remembered in the Store
under ("batch_memory", batch_id), one item per execution, so each report can
say what changed.

Its events (tokens, tool calls, activity) go to the job's stream in the chat
event format.
"""

from typing import Any

from langgraph.store.base import BaseStore

from agent.context import BatchReportContext
from agent.report_agent import ReportAgent, ReportMissing, handed_in
from agent.reporter import collect_evidence
from core.config import Settings
from core.db import utcnow

__all__ = ["BatchReportAgent", "ReportMissing"]
BATCH_TITLE = "배치 실행 리포트"


def memory_namespace(batch_id: str) -> tuple[str, ...]:
    return ("batch_memory", batch_id)


async def previous_runs(
    store: BaseStore, batch_id: str | None, execution_id: str, limit: int
) -> list[dict[str, Any]]:
    """Summaries of the batch's earlier runs, newest first."""
    if not batch_id or limit <= 0:
        return []
    items = await store.asearch(memory_namespace(batch_id), limit=1000)
    runs = [i.value for i in items if i.key != execution_id]
    runs.sort(key=lambda v: v.get("created_at", ""), reverse=True)
    return runs[:limit]


async def remember_run(
    store: BaseStore,
    batch_id: str | None,
    execution_id: str,
    value: dict[str, Any],
) -> None:
    if batch_id:
        await store.aput(
            memory_namespace(batch_id),
            execution_id,
            {**value, "created_at": utcnow().isoformat()},
            index=False,  # read back by namespace, never searched by meaning
        )


class BatchReportAgent:
    """The report agent (agent.report_agent) with the batch prompt."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.agent = ReportAgent(
            settings, "batch_analyst", settings.batch_report_model_call_limit
        )

    async def write(
        self,
        ctx: BatchReportContext,
        execution: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """{title, markdown, summary} of the execution."""
        evidence = await collect_evidence(
            ctx.services, ctx.execution_id, plan=None
        )
        async with ctx.activity("report_writing"):
            return await self.agent.write(
                ctx, _request(execution, history, evidence), BATCH_TITLE
            )


def _request(
    execution: dict[str, Any], history: list[dict[str, Any]], evidence: str
) -> str:
    metadata = execution.get("metadata") or {}
    lifecycle = execution.get("lifecycle") or {}
    lines = [
        "# 배치 실행",
        f"- execution_id: {execution.get('execution_id')}",
        f"- batch_id: {metadata.get('batch_id') or '알 수 없음'}",
        f"- 배치 실행 번호(run_id): {metadata.get('run_id') or '없음'}",
        f"- 시작: {lifecycle.get('started_at') or '알 수 없음'}",
        f"- 종료: {lifecycle.get('finished_at') or '알 수 없음'}",
        "",
        "# 이전 실행 요약 (최신 순)",
    ]
    if history:
        for run in history:
            lines.append(
                f"## {run.get('finished_at') or run.get('created_at')} "
                f"— {run.get('title', '')}\n{run.get('summary', '')}"
            )
    else:
        lines.append("없음 (이 배치의 첫 리포트)")
    lines += ["", "# 이번 실행 개요", evidence or "(Step 결과 없음)"]
    return "\n".join(lines)


def _report(state: dict[str, Any]) -> dict[str, Any]:
    return handed_in(state, BATCH_TITLE)

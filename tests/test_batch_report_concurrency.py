"""BATCH_REPORT_CONCURRENCY: one pod writes several report jobs at once."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from src.dtest.core.config import Settings
from src.dtest.worker.batch_reports import BatchReportWorker


def test_loops_write_different_jobs_side_by_side():
    worker = BatchReportWorker.__new__(BatchReportWorker)
    queue = [SimpleNamespace(id=f"job-{i}") for i in range(6)]
    done: list[str] = []
    busy = peak = 0

    async def claim():
        return queue.pop(0) if queue else None

    async def process(job):
        nonlocal busy, peak
        busy += 1
        peak = max(peak, busy)
        await asyncio.sleep(0.05)
        busy -= 1
        done.append(job.id)

    w = cast(Any, worker)
    w._claim, w._process = claim, process

    async def main():
        loops = [asyncio.create_task(worker.run_forever()) for _ in range(3)]
        while len(done) < 6:
            await asyncio.sleep(0.01)
        for loop in loops:
            loop.cancel()
        await asyncio.gather(*loops, return_exceptions=True)

    asyncio.run(main())
    assert sorted(done) == [f"job-{i}" for i in range(6)]  # each once
    assert peak == 3


def test_worker_starts_one_loop_per_slot(monkeypatch):
    from src.dtest.worker import runtime

    async def forever():
        await asyncio.Event().wait()

    fake = SimpleNamespace(
        notify=None, progress=None, enqueue=None, run_forever=forever
    )
    for name in (
        "AgentGraphs",
        "RunScheduler",
        "BatchReportWorker",
        "BatchReportRecovery",
        "ExecutorEventConsumer",
        "MissedEventRecovery",
        "Retention",
        "BatchDisableRetry",
        "ExecutionCancelRetry",
    ):
        monkeypatch.setattr(runtime, name, lambda *a, **k: fake)
    services = cast(
        Any,
        SimpleNamespace(
            settings=Settings(
                memory_worker_enabled=False, batch_report_concurrency=3
            ),
            checkpointer=None,
            memory=SimpleNamespace(store=None),
            db=None,
            redis=None,
            executor=None,
        ),
    )

    async def main():
        worker = runtime.Worker(services)
        worker.start()
        names = [t.get_name() for t in worker.tasks]
        for task in worker.tasks:
            task.cancel()
        await asyncio.gather(*worker.tasks, return_exceptions=True)
        return names

    names = asyncio.run(main())
    assert [n for n in names if n.startswith("batch-reports-")] == [
        "batch-reports-0",
        "batch-reports-1",
        "batch-reports-2",
    ]
    assert Settings().batch_report_concurrency == 4

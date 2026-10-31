import asyncio
import os
import socket

from src.dtest.agent.graph import AgentGraphs
from src.dtest.core.executor.cancels import ExecutionCancelRetry
from src.dtest.core.services import Services
from src.dtest.worker.batch_reports import (
    BatchReportRecovery,
    BatchReportWorker,
)
from src.dtest.worker.executor_events import (
    ExecutorEventConsumer,
    MissedEventRecovery,
)
from src.dtest.worker.maintenance import Retention
from src.dtest.worker.memory import MemoryWorker
from src.dtest.worker.scheduler import RunScheduler
from src.dtest.worker.user_deactivation import BatchDisableRetry


class Worker:
    """Background side of the service.

    Agent runs, executor events, batch report jobs, project memory.
    """

    def __init__(self, services: Services):
        settings = services.settings
        self.owner = f"{socket.gethostname()}:{os.getpid()}"
        graphs = AgentGraphs(
            settings, services.checkpointer, services.memory.store
        )
        self.scheduler = RunScheduler(services, graphs, self.owner)
        self.reports = BatchReportWorker(services, self.owner)
        self.report_recovery = BatchReportRecovery(services)
        self.consumer = ExecutorEventConsumer(
            services.db,
            services.redis,
            settings.executor_tenant_stream,
            f"{settings.redis_namespace}:executor-events",
            self.owner,
            on_wake=self.scheduler.notify,
            on_progress=self.scheduler.progress,
            on_completed=self.reports.enqueue,
            executor=services.executor,
        )
        self.recovery = MissedEventRecovery(
            services.db,
            services.executor,
            on_wake=self.scheduler.notify,
            after_seconds=settings.executor_event_recovery_seconds,
        )
        self.retention = Retention(services)
        self.batch_disable = BatchDisableRetry(services)
        self.cancel_retry = ExecutionCancelRetry(services)
        self.memory = (
            MemoryWorker(services, self.owner)
            if settings.memory_worker_enabled
            else None
        )
        self.tasks: list[asyncio.Task] = []
        self.stopping = False

    def start(self) -> None:
        self.tasks = [
            asyncio.create_task(
                self.scheduler.run_forever(), name="run-scheduler"
            ),
            asyncio.create_task(
                self.consumer.run_forever(), name="executor-events"
            ),
            asyncio.create_task(
                self.recovery.run_forever(), name="missed-executor-events"
            ),
            asyncio.create_task(
                self.reports.run_forever(), name="batch-reports"
            ),
            asyncio.create_task(
                self.report_recovery.run_forever(),
                name="batch-report-recovery",
            ),
            asyncio.create_task(
                self.retention.run_forever(), name="retention"
            ),
            asyncio.create_task(
                self.batch_disable.run_forever(), name="batch-disable-retry"
            ),
            asyncio.create_task(
                self.cancel_retry.run_forever(), name="executor-cancel-retry"
            ),
        ]
        if self.memory:
            self.tasks.append(
                asyncio.create_task(
                    self.memory.run_forever(), name="memory-worker"
                )
            )

    def stopped_loops(self) -> list[str]:
        """Background loops that ended on their own (each runs forever)."""
        if self.stopping:
            return []
        return [t.get_name() for t in self.tasks if t.done()]

    async def stop(self, drain_seconds: float = 20) -> None:
        """Drains the run and memory workers together, in ``drain_seconds``.

        Shutdown budget against terminationGracePeriodSeconds 60: preStop
        5 s + uvicorn --timeout-graceful-shutdown 20 s (SSE streams hold it
        to the end) + this 20 s + lease release.
        """
        self.stopping = True
        drains = [self.scheduler.drain(drain_seconds)]
        if self.memory:
            drains.append(self.memory.stop(drain_seconds))
        await asyncio.gather(*drains)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

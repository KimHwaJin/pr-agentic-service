import asyncio
import os
import socket

from agent.graph import AgentGraphs
from core.services import Services
from worker.batch_reports import BatchReportRecovery, BatchReportWorker
from worker.executor_events import ExecutorEventConsumer, MissedEventRecovery
from worker.maintenance import Retention
from worker.scheduler import RunScheduler


class Worker:
    """Background side of the service.

    Agent runs, executor events, batch report jobs.
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
        )
        self.recovery = MissedEventRecovery(
            services.db,
            services.executor,
            on_wake=self.scheduler.notify,
            after_seconds=settings.executor_event_recovery_seconds,
        )
        self.retention = Retention(services)
        self.tasks: list[asyncio.Task] = []

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
        ]

    async def stop(self, drain_seconds: float = 20) -> None:
        await self.scheduler.drain(drain_seconds)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

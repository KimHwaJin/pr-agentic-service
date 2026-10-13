import asyncio
import os
import socket

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent.graph import AgentGraphs
from core.bootstrap import PgPool
from core.services import Services
from worker.batch_reports import BatchReportWorker
from worker.executor_events import ExecutorEventConsumer
from worker.maintenance import Retention
from worker.scheduler import RunScheduler


class Worker:
    """Background side of the service.

    Agent runs, executor events, batch report jobs.
    """

    def __init__(self, services: Services, pool: PgPool):
        settings = services.settings
        self.owner = f"{socket.gethostname()}:{os.getpid()}"
        graphs = AgentGraphs(
            settings, AsyncPostgresSaver(pool), services.memory.store
        )
        self.scheduler = RunScheduler(services, graphs, self.owner)
        self.consumer = ExecutorEventConsumer(
            services.db,
            services.redis,
            settings.executor_event_stream,
            f"{settings.redis_namespace}:executor-events",
            self.owner,
            on_wake=self.scheduler.notify,
            on_progress=self.scheduler.progress,
        )
        self.reports = BatchReportWorker(services, self.owner)
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
                self.reports.run_forever(), name="batch-reports"
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

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY

import pytest
from langchain_core.language_models.fake_chat_models import (
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore
from sqlalchemy.dialects import postgresql

from agent import batch as batch_agent
from agent import report_agent
from agent.batch import (
    BatchReportAgent,
    ReportMissing,
    _report,
    _request,
    previous_runs,
    remember_run,
)
from agent.context import BatchReportContext
from api_service.schemas.batch import BatchReportDetail
from core.config import Settings
from core.contracts import events as contracts
from core.db import utcnow
from core.executor.client import ExecutorError, trigger_type
from worker import batch_reports
from worker.batch_reports import (
    BatchReportWorker,
    LeaseLost,
    NotReady,
    enqueue,
)

EXECUTION = "674ff370-c4c6-42c4-a423-eba72d18352b"
OWNER = "0c8a2f86-5d0e-4e55-9a3c-6f2f0f6a1b11"


class _Db:
    """Async session double: ``scalar`` answers in order."""

    def __init__(self, answers):
        self.answers, self.statements = list(answers), []

    def sessions(self):
        db = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def scalar(self, statement):
                db.statements.append(statement)
                return db.answers.pop(0)

            async def commit(self):
                pass

        return Session()


class _Events:
    def __init__(self):
        self.sent = []

    async def emit_report(self, job_id, type, data, durable=True):
        contracts.check(type, data)  # the shape the chat components read
        self.sent.append((job_id, type, data))


class _Executor:
    def __init__(self, execution=None):
        self.execution = execution or {}
        self.gets, self.reports = 0, []

    async def get(self, execution_id):
        self.gets += 1
        return self.execution

    async def create_report(self, execution_id, **kw):
        self.reports.append(kw)
        return {"artifact_id": "report-1"}

    async def notebook(self, execution_id):
        return {
            "artifact_id": "nb-1",
            "type": "NOTEBOOK",
            "storage": {"relative_path": "x/run.ipynb"},
        }


def _services(db=None, executor=None, store=None):
    return cast(
        Any,
        SimpleNamespace(
            settings=Settings(),
            db=db or _Db([]),
            events=_Events(),
            executor=executor or _Executor(),
            memory=SimpleNamespace(store=store or InMemoryStore()),
        ),
    )


def _inserted(db: _Db) -> dict[str, Any]:
    return (
        db.statements[-1].compile(dialect=postgresql.dialect()).params
    )  # the INSERT of the job


# --- enqueue -------------------------------------------------------------


def _batch_execution(status="SUCCEEDED", trigger="BATCH", owner=OWNER):
    return {
        "state": {"status": status},
        "trigger": {"type": trigger, "actor": {"type": "USER"}},
        "context": {"user_id": owner} if owner else {},
        "metadata": {"batch_id": "batch-3", "run_id": "run-7"},
    }


class _Unknown(_Executor):
    async def get(self, execution_id):
        self.gets += 1
        raise ExecutorError(404, {"error": {"code": "EXECUTION_NOT_FOUND"}})


def test_failed_runs_get_no_report():
    services = _services(executor=_Executor(_batch_execution("FAILED")))
    assert asyncio.run(enqueue(services, EXECUTION)) is None


def test_the_executor_decides_not_the_event():
    """Events can be forged: owner and trigger come from the executor."""
    db = _Db(["job-1"])
    services = _services(db, _Executor(_batch_execution()))
    assert asyncio.run(enqueue(services, EXECUTION)) == "job-1"
    assert services.executor.gets == 1
    params = _inserted(db)
    assert params["idempotency_key"] == f"batch-report:{EXECUTION}"
    assert params["owner_id"] == OWNER and params["batch_run_id"] == "run-7"
    assert params["batch_id"] == "batch-3"
    assert services.events.sent == [
        ("job-1", "run_status", {"status": "queued"})
    ]

    interactive = _services(executor=_Executor(_batch_execution(trigger="X")))
    assert asyncio.run(enqueue(interactive, EXECUTION)) is None


def test_executions_outside_our_tenant_get_no_report():
    services = _services(executor=_Unknown())
    assert asyncio.run(enqueue(services, EXECUTION)) is None
    assert services.executor.gets == 1


def test_executions_without_an_owner_get_no_report():
    services = _services(executor=_Executor(_batch_execution(owner=None)))
    assert asyncio.run(enqueue(services, EXECUTION)) is None


def test_a_job_that_exists_is_not_announced_again():
    services = _services(_Db([None]), _Executor(_batch_execution()))
    assert asyncio.run(enqueue(services, EXECUTION)) is None
    assert services.events.sent == []


def test_worker_skips_events_of_runs_that_did_not_succeed():
    services = _services(executor=_Executor(_batch_execution()))
    worker = BatchReportWorker(services, "me")
    asyncio.run(worker.enqueue(EXECUTION, {"status": "FAILED"}))
    assert services.executor.gets == 0


def test_trigger_type_reads_the_trigger():
    assert trigger_type({"trigger": {"type": "BATCH"}}) == "BATCH"
    assert trigger_type({"trigger_type": "INTERACTIVE"}) is None
    assert trigger_type({}) is None


# --- worker --------------------------------------------------------------


def _job(**values):
    base = dict(
        id="job-1",
        owner_id=OWNER,
        execution_id=EXECUTION,
        batch_id="batch-3",
        batch_run_id="run-7",
        execution={"metadata": {"batch_id": "batch-3"}},
        state="QUEUED",
        title=None,
        markdown=None,
        summary=None,
        collecting_since=None,
    )
    return SimpleNamespace(**{**base, **values})


def _worker(services, job):
    worker = BatchReportWorker(services, "pod-1")

    async def _set(job_id, **values):
        for key, value in values.items():
            setattr(job, key, value)

    cast(Any, worker)._set = _set
    return worker


def _execution(projection="SUCCEEDED", **extra):
    return {
        "execution_id": EXECUTION,
        "state": {"status": "SUCCEEDED"},
        "workspace": {"notebook_projection": {"status": projection}},
        **extra,
    }


def test_collect_waits_for_the_notebook():
    job = _job()
    worker = _worker(_services(executor=_Executor(_execution("PENDING"))), job)
    with pytest.raises(NotReady):
        asyncio.run(worker._collect(cast(Any, job), utcnow()))
    late = utcnow() - timedelta(hours=1)
    with pytest.raises(TimeoutError):
        asyncio.run(worker._collect(cast(Any, job), late))
    failed = _worker(_services(executor=_Executor(_execution("FAILED"))), job)
    with pytest.raises(RuntimeError, match="projection failed"):
        asyncio.run(failed._collect(cast(Any, job), utcnow()))


def test_a_waiting_job_goes_back_to_the_table():
    job = _job()
    services = _services(executor=_Executor(_execution("PENDING")))
    worker = _worker(services, job)
    asyncio.run(worker._run(cast(Any, job)))
    assert job.state == "COLLECTING" and job.lease_owner is None
    assert job.lease_expires_at > utcnow()
    assert [t for _, t, _ in services.events.sent] == [
        "run_status",
        "run_status",
    ]
    assert services.events.sent[-1][2]["status"] == "waiting_executor"

    services.events.sent.clear()  # the next poll says nothing new
    asyncio.run(worker._run(cast(Any, job)))
    assert services.events.sent == []


def test_report_is_written_saved_and_remembered():
    store = InMemoryStore()
    job = _job()
    services = _services(executor=_Executor(_execution()), store=store)
    worker = _worker(services, job)
    seen = {}

    async def write(ctx, execution, history):
        seen["ctx"], seen["history"] = ctx, history
        return {
            "title": "주간 수율",
            "markdown": "# 리포트",
            "summary": "수율 97%",
        }

    cast(Any, worker.agent).write = write
    asyncio.run(
        remember_run(
            store, "batch-3", "previous", {"title": "지난주", "summary": "95%"}
        )
    )
    asyncio.run(worker._run(cast(Any, job)))

    assert job.state == "SUCCEEDED" and job.artifact_id == "report-1"
    assert seen["ctx"].batch_id == "batch-3"
    assert [h["summary"] for h in seen["history"]] == ["95%"]
    report = services.executor.reports[0]
    assert report["markdown"] == "# 리포트"
    assert report["metadata"]["batch_id"] == "batch-3"
    memory = asyncio.run(store.aget(("batch_memory", "batch-3"), EXECUTION))
    assert memory and memory.value["summary"] == "수율 97%"
    types = [t for _, t, _ in services.events.sent]
    assert types == [
        "run_status",
        "artifact",
        "artifact",
        "message_final",
        "run_status",
    ]
    assert services.events.sent[-1][2] == {"status": "succeeded"}


def test_retry_with_a_written_report_only_saves_it():
    job = _job(title="t", markdown="# 이미 씀", summary="s")
    services = _services(executor=_Executor(_execution("PENDING")))
    worker = _worker(services, job)

    async def write(*args):
        raise AssertionError("the report is reused")

    cast(Any, worker.agent).write = write
    asyncio.run(worker._run(cast(Any, job)))
    assert job.state == "SUCCEEDED"
    assert services.executor.reports[0]["markdown"] == "# 이미 씀"


def test_a_failed_stage_is_recorded():
    job = _job()
    services = _services(executor=_Executor(_execution()))
    worker = _worker(services, job)

    async def write(*args):
        raise ReportMissing("no report")

    cast(Any, worker.agent).write = write
    asyncio.run(worker._run(cast(Any, job)))
    assert job.state == "FAILED" and job.failed_stage == "GENERATING"
    assert "오류 ID" in job.error and "ReportMissing" not in job.error
    assert [t for _, t, _ in services.events.sent][-2:] == [
        "run_error",
        "run_status",
    ]


def test_consumer_hands_completions_to_the_reports(monkeypatch):
    from worker import executor_events

    async def deliver(db, event):
        return None

    monkeypatch.setattr(executor_events, "deliver", deliver)
    completed, acked = [], []

    class Redis:
        async def xack(self, *args):
            acked.append(args[-1])

    async def on_completed(execution_id, payload):
        completed.append((execution_id, payload["status"]))

    consumer = executor_events.ExecutorEventConsumer(
        cast(Any, None),
        cast(Any, Redis()),
        "s",
        "g",
        "c",
        on_wake=None,
        on_progress=None,
        on_completed=on_completed,
    )
    fields = {
        "event_id": "e1",
        "execution_id": EXECUTION,
        "event_type": "execution.completed",
        "event_sequence": "9",
        "payload": '{"status": "SUCCEEDED"}',
    }
    asyncio.run(consumer._handle("m1", fields))
    assert completed == [(EXECUTION, "SUCCEEDED")] and acked == ["m1"]


def test_worker_module_exports_enqueue():
    assert batch_reports.enqueue is enqueue


# --- memory and the agent -------------------------------------------------


def test_previous_runs_newest_first_without_this_run():
    store = InMemoryStore()

    async def main():
        for key in ("a", "b", "c"):
            await remember_run(store, "batch-3", key, {"summary": key})
        return await previous_runs(store, "batch-3", "c", limit=5)

    runs = asyncio.run(main())
    assert [r["summary"] for r in runs] == ["b", "a"]
    assert asyncio.run(previous_runs(store, None, "c", limit=5)) == []


def test_request_carries_history_and_evidence():
    text = _request(
        {"execution_id": EXECUTION, "metadata": {"batch_id": "batch-3"}},
        [{"title": "지난주", "summary": "95%", "finished_at": "2026-10-12"}],
        "### Step 0 code — SUCCEEDED",
    )
    assert "batch-3" in text and "95%" in text and "### Step 0" in text
    assert "첫 리포트" in _request({}, [], "")


def test_report_falls_back_to_the_last_answer():
    assert _report({"report": {"title": "t"}}) == {"title": "t"}
    fallback = _report({"messages": [AIMessage("# 직접 쓴 리포트")]})
    assert fallback["markdown"] == "# 직접 쓴 리포트"
    with pytest.raises(ReportMissing):
        _report({"messages": []})


class _ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_agent_hands_in_its_report(monkeypatch):
    model = _ToolModel(
        messages=iter(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "name": "submit_report",
                            "args": {
                                "title": "주간 수율",
                                "markdown": "# 리포트",
                                "summary": "수율 97%",
                            },
                            "id": "call-1",
                        }
                    ],
                )
            ]
        ),
        disable_streaming=True,
    )
    monkeypatch.setattr(report_agent, "chat_model", lambda s, n: model)

    async def evidence(services, execution_id, plan):
        return "### Step 0 code — SUCCEEDED"

    monkeypatch.setattr(batch_agent, "collect_evidence", evidence)
    services = _services()
    ctx = BatchReportContext(
        services=services,
        job_id="job-1",
        execution_id=EXECUTION,
        batch_id="batch-3",
        model="m",
    )
    report = asyncio.run(
        BatchReportAgent(services.settings).write(ctx, {}, [])
    )
    assert report == {
        "title": "주간 수율",
        "markdown": "# 리포트",
        "summary": "수율 97%",
    }
    types = [t for _, t, _ in services.events.sent]
    assert "tool_call" in types


# --- API views ------------------------------------------------------------


def test_detail_names_the_owner():
    now = utcnow()
    job = _job(
        state="SUCCEEDED",
        failed_stage=None,
        artifact_id="report-1",
        error=None,
        created_at=now,
        updated_at=now,
        finished_at=now,
    )
    user = SimpleNamespace(id=OWNER, employee_id="00123", name="홍길동")
    from api_service.routers.batch_reports import _detail

    detail = _detail(cast(Any, job), cast(Any, user))
    assert isinstance(detail, BatchReportDetail)
    assert detail.owner.employee_id == "00123"


# --- recovery ------------------------------------------------------------


class _RecoveryDb:
    """The advisory lock answers ``locked``; ``scalars`` the known jobs."""

    def __init__(self, locked=True, known=()):
        self.locked, self.known = locked, list(known)

    def sessions(self):
        db = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def scalar(self, statement, params=None):
                return db.locked

            async def scalars(self, statement):
                return db.known

        return Session()


class _Listing:
    def __init__(self, items, error=None):
        self.items, self.error, self.asked = items, error, []

    async def executions(self, created_after, **filters):
        self.asked.append((created_after, filters))
        if self.error:
            raise self.error
        return self.items


def _finished(execution_id, minutes_ago):
    finished = utcnow() - timedelta(minutes=minutes_ago)
    return {
        "execution_id": execution_id,
        "trigger": {"type": "BATCH"},
        "context": {"user_id": OWNER},
        "metadata": {"batch_id": "batch-3", "run_id": f"run-{execution_id}"},
        "lifecycle": {"finished_at": finished.isoformat()},
    }


def _recovery(monkeypatch, executor, db=None):
    queued = []

    async def fake_enqueue(services, execution_id):
        queued.append(execution_id)
        return f"job-{execution_id}"

    monkeypatch.setattr(batch_reports, "enqueue", fake_enqueue)
    services = cast(
        Any,
        SimpleNamespace(
            settings=Settings(executor_tenant_id="pr-agentic"),
            db=db or _RecoveryDb(),
            executor=executor,
        ),
    )
    return batch_reports.BatchReportRecovery(services), queued


def test_recovery_queues_missed_executions_only(monkeypatch):
    executor = _Listing(
        [
            _finished("missed", 30),
            _finished("reported", 30),
            _finished("just-done", 1),  # its event may still be on the way
        ]
    )
    recovery, queued = _recovery(
        monkeypatch, executor, _RecoveryDb(known=["reported"])
    )
    assert asyncio.run(recovery.sweep()) == ["job-missed"]
    assert queued == ["missed"]
    created_after, filters = executor.asked[0]
    assert filters == {  # the tenant is our key's
        "trigger_type": "BATCH",
        "status": "SUCCEEDED",
    }
    lookback = utcnow() - created_after
    assert timedelta(days=13) < lookback <= timedelta(days=14, seconds=5)


def test_recovery_leaves_the_sweep_to_the_pod_holding_the_lock(monkeypatch):
    executor = _Listing([_finished("missed", 30)])
    recovery, queued = _recovery(
        monkeypatch, executor, _RecoveryDb(locked=False)
    )
    assert asyncio.run(recovery.sweep()) == []
    assert executor.asked == [] and queued == []


def test_recovery_keeps_going_after_an_executor_error(monkeypatch):
    executor = _Listing([], error=RuntimeError("executor down"))
    recovery, _ = _recovery(monkeypatch, executor)
    recovery.interval = 0
    rounds = 0
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        nonlocal rounds
        rounds += 1
        if rounds == 2:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(batch_reports.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(recovery.run_forever())
    assert len(executor.asked) == 2


def test_a_lost_lease_stops_the_job_without_marking_it_failed():
    job = _job()
    worker = _worker(_services(executor=_Executor(_execution())), job)
    writes: list[dict] = []

    async def _set(job_id, **values):
        writes.append(values)
        raise LeaseLost(job_id)  # another pod claimed it meanwhile

    async def renew(job_id):
        return True

    cast(Any, worker)._set = _set
    cast(Any, worker)._renew = renew
    asyncio.run(worker._process(cast(Any, job)))
    assert writes == [{"state": "COLLECTING", "collecting_since": ANY}]


def test_heartbeat_stops_the_work_when_the_lease_is_gone(monkeypatch):
    worker = _worker(_services(), _job())
    worker.lease_seconds = 3
    beats: list[bool] = [True, False]

    async def renew(job_id):
        return beats.pop(0)

    real_sleep = asyncio.sleep

    async def tick(seconds):
        await real_sleep(0)

    async def main():
        monkeypatch.setattr("worker.batch_reports.asyncio.sleep", tick)
        cast(Any, worker)._renew = renew
        work = asyncio.get_running_loop().create_future()
        await asyncio.wait_for(worker._heartbeat("job-1", cast(Any, work)), 2)
        return work

    work = asyncio.run(main())
    assert beats == [] and work.cancelled()

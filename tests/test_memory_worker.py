import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore
from sqlalchemy.dialects import postgresql

from src.dtest.core.config import Settings
from src.dtest.core.contracts import events as contracts
from src.dtest.core.memory.service import Actor, MemoryEditError, ProjectMemory
from src.dtest.core.models import MemoryExtractionState
from src.dtest.worker import memory as mw
from src.dtest.worker.memory import (
    ChatMessage,
    MemoryWorker,
    claimable,
    is_trivial,
    mark_dirty,
    parse_ops,
    plan_topic,
    render_memory,
    take_chunk,
    worker_prompt,
)
from src.dtest.worker.scheduler import RunScheduler

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
ACTOR = Actor("agent", "memory_worker")
USER_TEXT = "앞으로 보고서는 표 위주로 써 줘. 우리 목표는 A라인 수율 개선이야"


def run(coro):
    return asyncio.run(coro)


def sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class _Session:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement, params=None):
        self.db.statements.append(statement)
        return SimpleNamespace(rowcount=1)

    async def scalar(self, statement):
        self.db.statements.append(statement)
        return self.db.answers.pop(0)

    async def scalars(self, statement):
        self.db.statements.append(statement)
        return []

    def add(self, row):
        row.id = len(self.db.added) + 1
        self.db.added.append(row)

    async def get(self, model, key):
        return None

    async def commit(self):
        self.db.commits += 1


class _Db:
    def __init__(self, answers=()):
        self.answers, self.statements, self.added = list(answers), [], []
        self.commits = 0

    def sessions(self):
        return _Session(self)


class _Events:
    def __init__(self):
        self.sent = []

    async def emit(self, session_id, run_id, type, data, durable=True):
        contracts.check(type, data)
        self.sent.append((session_id, run_id, type, data))


def _worker(db=None, **settings) -> MemoryWorker:
    db = db or _Db()
    memory = ProjectMemory(
        InMemoryStore(), cast(Any, db), Settings().memory_total_max_chars
    )
    services = SimpleNamespace(
        settings=Settings(**settings),
        db=db,
        memory=memory,
        events=_Events(),
    )
    return MemoryWorker(cast(Any, services), "pod-1")


def _msg(i, role, content, session="s1", run_id="r1"):
    return ChatMessage(
        f"m{i}", T0 + timedelta(seconds=i), role, content, session, run_id
    )


# --- trigger ---------------------------------------------------------------


def test_a_finished_turn_marks_the_project_dirty():
    db = _Db()

    async def main():
        async with db.sessions() as session:
            await mark_dirty(cast(Any, session), "p1", "r1")

    run(main())
    text = sql(db.statements[0])
    assert "INSERT INTO memory_extraction_state" in text
    assert "ON CONFLICT (project_id) DO UPDATE" in text
    assert "pending_turns = (memory_extraction_state.pending_turns + 1)" in (
        text
    )
    assert "dirty = true" in text
    # a new project's cursor starts at this run's first message
    assert "min(messages.created_at)" in text


def test_claim_needs_quiet_or_enough_turns():
    text = sql(
        MemoryExtractionState.__table__.select().where(claimable(T0, 180, 5))
    )
    assert "memory_extraction_state.dirty IS true" in text
    assert "memory_extraction_state.lease_expires_at IS NULL" in text
    assert "last_activity_at <= '2026-10-29 08:57:00+00:00'" in text
    assert "pending_turns >= 5" in text


def _scheduler(db, **settings):
    services = SimpleNamespace(
        settings=Settings(**settings),
        db=db,
        events=_Events(),
        forget_tool_effects=lambda run_id: asyncio.sleep(0),
    )
    scheduler = RunScheduler(cast(Any, services), cast(Any, None), "pod-1")

    async def no_title(run, answer):
        pass

    scheduler._auto_title = no_title  # type: ignore[method-assign]
    return scheduler


@pytest.mark.parametrize("enabled", [True, False])
def test_turns_are_counted_even_with_the_worker_off(enabled):
    db = _Db()
    scheduler = _scheduler(db, memory_worker_enabled=enabled)
    turn = cast(
        Any,
        SimpleNamespace(id="r1", session_id="s1", project_id="p1", model="m"),
    )
    run(scheduler._finish(turn, "succeeded", answer="답"))
    assert any(
        "INSERT INTO memory_extraction_state" in sql(s)
        for s in db.statements
        if hasattr(s, "compile")
    )


def test_failed_turns_do_not_count():
    db = _Db()
    turn = cast(
        Any,
        SimpleNamespace(id="r1", session_id="s1", project_id="p1", model="m"),
    )
    run(_scheduler(db)._finish(turn, "failed", error="boom"))
    assert not any(
        "memory_extraction_state" in sql(s)
        for s in db.statements
        if hasattr(s, "compile")
    )


def test_disabled_worker_is_not_started(monkeypatch):
    from src.dtest.worker import runtime

    for name in (
        "AgentGraphs",
        "RunScheduler",
        "BatchReportWorker",
        "BatchReportRecovery",
        "ExecutorEventConsumer",
        "MissedEventRecovery",
        "Retention",
    ):
        monkeypatch.setattr(
            runtime,
            name,
            lambda *a, **k: SimpleNamespace(
                notify=None, progress=None, enqueue=None
            ),
        )
    services = cast(
        Any,
        SimpleNamespace(
            settings=Settings(memory_worker_enabled=False),
            checkpointer=None,
            memory=SimpleNamespace(store=None),
            db=None,
            redis=None,
            executor=None,
        ),
    )
    assert runtime.Worker(services).memory is None
    services.settings = Settings(memory_worker_enabled=True)
    assert runtime.Worker(services).memory is not None


# --- input -----------------------------------------------------------------


def test_chunk_takes_the_oldest_messages_that_fit():
    messages = [_msg(i, "user", "가" * 400) for i in range(10)]
    chunk = take_chunk(messages, 300)  # ~110 tokens per message
    assert [m.id for m in chunk] == ["m0", "m1"]
    # one message is always taken, however long
    assert len(take_chunk([_msg(0, "user", "x" * 100000)], 10)) == 1


@pytest.mark.parametrize(
    "text", ["안녕하세요!", "고마워요 :)", "넵", "ok", "ㅋㅋㅋ", "진행해줘"]
)
def test_trivial_messages(text):
    assert is_trivial(text)


@pytest.mark.parametrize(
    "text", ["앞으로 보고서는 표로 써줘", "A라인 수율 분석해줘"]
)
def test_not_trivial(text):
    assert not is_trivial(text)


def test_trivial_chunk_skips_the_model(monkeypatch):
    def no_model(*args):
        raise AssertionError("the model was called")

    monkeypatch.setattr(mw, "chat_model", no_model)
    worker = _worker()
    chunk = [_msg(0, "user", "안녕"), _msg(1, "assistant", "안녕하세요!")]
    assert run(worker.extract("p", chunk)) == []


def test_process_advances_past_the_chunk_only():
    worker = _worker(memory_worker_max_input_tokens=500)
    messages = [_msg(i, "user", "가" * 1000) for i in range(3)]
    seen = {}

    async def fetch(state):
        return messages

    async def extract(project_id, chunk):
        seen["chunk"] = chunk
        return []

    async def advance(state, last, error=None):
        seen["last"] = last

    worker.messages = fetch  # type: ignore[method-assign]
    worker.extract = extract  # type: ignore[method-assign]
    worker.advance = advance  # type: ignore[method-assign]
    run(worker.process(cast(Any, SimpleNamespace(project_id="p"))))
    assert [m.id for m in seen["chunk"]] == ["m0"]
    assert seen["last"].id == "m0"


def _state(**kw):
    return MemoryExtractionState(
        project_id="p",
        processed_until_at=T0,
        processed_until_id="m0",
        dirty=True,
        pending_turns=4,
        attempts=1,
        lease_owner="pod-1",
        **kw,
    )


@pytest.mark.parametrize("more", [True, False])
def test_advance_keeps_dirty_only_while_messages_remain(more):
    row = _state()
    worker = _worker(_Db([row, more]))
    run(worker.advance(row, _msg(5, "user", "x")))
    assert row.processed_until_id == "m5"
    assert row.processed_until_at == T0 + timedelta(seconds=5)
    assert row.dirty is more
    assert row.pending_turns == (4 if more else 0)
    assert row.lease_owner is None and row.attempts == 0


# --- output and validation -------------------------------------------------


def test_parse_ops_reads_json_inside_text():
    assert parse_ops('결과:\n{"ops": [{"op": "add"}]}') == [{"op": "add"}]
    assert parse_ops('[{"op": "delete"}]') == [{"op": "delete"}]
    assert parse_ops("저장할 것이 없습니다") == []


LINES = [
    {"id": "a1", "text": "- 표 위주", "author": "user", "source": {}},
    {"id": "b2", "text": "- 결론 먼저", "author": "agent", "source": {}},
]


def _plan(ops, lines=LINES, limit=500):
    return plan_topic(lines, ops, [USER_TEXT], limit, ACTOR, "2026-10-29")


def _add(text, quote="보고서는 표 위주로", topic="preferences"):
    return {"op": "add", "topic": topic, "text": text, "quote": quote}


def test_valid_ops_apply_in_order():
    plan = _plan(
        [
            _add("- 보고서는 표 중심"),
            {
                "op": "replace",
                "line_id": "b2",
                "text": "- 목표: A라인 수율",
                "quote": "목표는 A라인 수율 개선",
            },
            {"op": "delete", "line_id": "a1"},
        ]
    )
    assert plan.rejected == []
    assert plan.lines is not None
    assert [line["text"] for line in plan.lines] == [
        "- 목표: A라인 수율",
        "- 보고서는 표 중심",
    ]
    assert plan.lines[0]["id"] == "b2"
    assert all(line["author"] == "agent" for line in plan.lines)


@pytest.mark.parametrize(
    ("op", "reason"),
    [
        (_add("- 표", quote=""), "no quote"),
        (_add("- 표", quote="그래프로 그려줘"), "quote not in a user message"),
        (_add("- 이번만 표로"), "one-off phrasing"),
        (_add("- 이 보고서만 표로"), "one-off phrasing"),
        (_add("- 오늘만 표로"), "one-off phrasing"),
        (_add("- 참고: https://wiki/x"), "url"),
        (_add("- 데이터: /data/nce/lot.csv"), "file path"),
        (_add("- 데이터: C:\\data\\x.csv"), "file path"),
        (_add("## 제목"), "heading"),
        (_add("- 표 위주"), "duplicate line"),
        (
            {"op": "replace", "line_id": "zz", "text": "- x", "quote": "목표"},
            "line_id not found",
        ),
        ({"op": "delete", "line_id": "zz"}, "line_id not found"),
        (
            {
                "op": "replace",
                "line_id": "a1",
                "text": "- 표  위주",
                "quote": "목표",
            },
            "replace changes nothing",
        ),
        ({"op": "merge"}, "unknown op 'merge'"),
    ],
)
def test_each_rule_rejects_only_its_op(op, reason):
    plan = _plan([op, _add("- 보고서는 표 중심")])
    assert [r for _, r in plan.rejected] == [reason]
    assert plan.lines is not None and len(plan.accepted) == 1


def test_formats_are_left_to_the_topic_description():
    # no date rule or ordering in code: the Key Events description asks
    lines = [
        {"id": "e1", "text": "2026-09-01 설비 교체", "author": "user"},
    ]
    plan = plan_topic(
        lines,
        [_add("- 목표 확정: A라인", quote="목표는 A라인", topic="key_events")],
        [USER_TEXT],
        700,
        ACTOR,
        "t",
    )
    assert plan.rejected == [] and plan.lines is not None
    assert [line["text"] for line in plan.lines] == [
        "2026-09-01 설비 교체",
        "- 목표 확정: A라인",
    ]


def test_growing_ops_are_dropped_to_fit_the_limit():
    plan = _plan(
        [
            {"op": "delete", "line_id": "a1"},
            _add("- 보고서는 표 중심으로 쓴다"),
            _add("- 목표: A라인 수율 개선", quote="목표는 A라인 수율 개선"),
        ],
        limit=35,
    )
    assert plan.lines is not None
    assert [line["text"] for line in plan.lines] == [
        "- 결론 먼저",
        "- 보고서는 표 중심으로 쓴다",
    ]
    assert [r for _, r in plan.rejected] == ["topic over 35 characters"]


def test_nothing_left_means_no_change():
    assert _plan([_add("- x", quote="")]).lines is None
    full = _plan([_add("- " + "가" * 600)], limit=500)
    assert full.lines is None
    assert [r for _, r in full.rejected] == ["topic over 500 characters"]


# --- one claim end to end --------------------------------------------------


class _Model:
    def __init__(self, reply):
        self.reply, self.calls, self.messages = reply, 0, []

    async def ainvoke(self, messages):
        self.calls += 1
        self.messages = messages
        if isinstance(self.reply, Exception):
            raise self.reply
        return AIMessage(self.reply)


def test_extract_applies_valid_ops_and_tells_the_sessions(monkeypatch):
    model = _Model(
        '{"ops": ['
        '{"op": "add", "topic": "preferences", "text": "- 보고서는 표 위주",'
        ' "quote": "보고서는 표 위주로 써 줘"},'
        '{"op": "add", "topic": "overview", "text": "- 분석 결과 편차 큼",'
        ' "quote": "편차가 큽니다"},'
        '{"op": "add", "topic": "nope", "text": "x", "quote": "x"}'
        "]}"
    )
    monkeypatch.setattr(mw, "chat_model", lambda settings, name: model)
    worker = _worker(_Db([None]))  # Run.model lookup -> default model
    chunk = [
        _msg(0, "user", USER_TEXT, "s1", "r1"),
        _msg(1, "assistant", "편차가 큽니다", "s1", "r1"),
        _msg(2, "user", "좋아", "s2", "r2"),
    ]
    changed = run(worker.extract("p", chunk))
    assert changed == ["preferences"]
    section = run(worker.memory.content("p", "preferences"))
    assert section["content"] == "- 보고서는 표 위주"
    line = section["lines"][0]
    assert line["author"] == "agent"
    assert line["source"] == {
        "session_ids": ["s1", "s2"],
        "run_ids": ["r1", "r2"],
    }
    history = worker.services.db.added[-1]
    assert (history.actor_type, history.actor_id) == ("agent", "memory_worker")
    sent = worker.services.events.sent
    assert {(s, r, t) for s, r, t, _ in sent} == {
        ("s1", "r1", "memory_updated"),
        ("s2", "r2", "memory_updated"),
    }
    assert model.calls == 1


def test_a_version_conflict_is_retried_once(monkeypatch):
    worker = _worker()
    real_edit = worker.memory.edit
    calls = []

    async def edit(*args, **kw):
        calls.append(kw["expected_version"])
        if len(calls) == 1:
            raise MemoryEditError(409, "version conflict")
        return await real_edit(*args, **kw)

    monkeypatch.setattr(worker.memory, "edit", edit)
    view = run(
        worker.apply(
            "p", "preferences", [_add("- 표 중심")], [USER_TEXT], ACTOR
        )
    )
    assert view is not None and view["content"] == "- 표 중심"
    assert calls == [0, 0]


def test_a_failure_is_retried_later():
    db = _Db()
    worker = _worker(db)
    state = cast(Any, SimpleNamespace(project_id="p", attempts=0))
    run(worker.failed(state, [_msg(0, "user", "x")], "Timeout"))
    text = sql(db.statements[-1])
    assert "attempts=1" in text and "lease_owner=NULL" in text
    assert "last_error='Timeout'" in text


def test_the_third_failure_skips_the_chunk(monkeypatch):
    worker = _worker()
    seen = {}

    async def advance(state, last, error=None):
        seen.update(last=last, error=error)

    monkeypatch.setattr(worker, "advance", advance)
    state = cast(Any, SimpleNamespace(project_id="p", attempts=2))
    run(
        worker.failed(state, [_msg(0, "user", "x"), _msg(1, "user", "y")], "E")
    )
    assert seen["last"].id == "m1" and seen["error"] == "E"


def test_a_model_error_goes_to_the_failure_path(monkeypatch):
    monkeypatch.setattr(
        mw, "chat_model", lambda s, n: _Model(TimeoutError("slow"))
    )
    worker = _worker(_Db([None]))
    seen = {}

    async def fetch(state):
        return [_msg(0, "user", USER_TEXT)]

    async def failed(state, chunk, error):
        seen.update(chunk=chunk, error=error)

    worker.messages = fetch  # type: ignore[method-assign]
    worker.failed = failed  # type: ignore[method-assign]
    run(worker.process(cast(Any, SimpleNamespace(project_id="p"))))
    assert seen["error"] == "TimeoutError: slow" and len(seen["chunk"]) == 1


# --- topics ----------------------------------------------------------------


def _custom_topics(worker):
    """Overview kept, the rest replaced by one 용어 topic."""
    return run(
        worker.memory.put_topics(
            "p",
            [
                {
                    "id": "overview",
                    "title": "배경",
                    "description": "왜 분석하는지",
                    "max_chars": 500,
                },
                {
                    "title": "용어",
                    "description": "사내 약어와 뜻",
                    "max_chars": 300,
                },
            ],
            expected_version=0,
            actor=Actor("user", "u-1"),
        )
    )["topics"]


def test_worker_prompt_lists_the_topics():
    prompt = worker_prompt(
        [
            {
                "id": "overview",
                "title": "배경",
                "description": "왜 분석하는지",
                "max_chars": 500,
            },
            {"id": "t1", "title": "용어", "description": "", "max_chars": 300},
        ],
        "2026-10-29",
    )
    assert "- overview: 배경 — 왜 분석하는지 (한도 500자)" in prompt
    assert "- t1: 용어 (한도 300자)" in prompt
    assert "오늘 날짜: 2026-10-29" in prompt
    assert "key_events" not in prompt and "core_interests" not in prompt
    assert (
        "{topics}" not in prompt and "맞지 않으면 저장하지 않습니다" in prompt
    )


def test_default_prompt_carries_the_key_events_rule_in_its_description():
    worker = _worker()
    prompt = worker_prompt(run(worker.memory.topics("p")), "2026-10-29")
    assert "- key_events: Key Events — 날짜가 있는 사건" in prompt
    assert "날짜(YYYY-MM-DD)로 시작, 최신이 위 (한도 700자)" in prompt


def test_render_memory_shows_topic_ids_titles_and_usage():
    worker = _worker()
    topics = _custom_topics(worker)
    run(
        worker.memory.save_line(
            "p", "overview", "- 수율 개선", actor=Actor("user", "u-1")
        )
    )
    text = render_memory(run(worker.memory.contents("p")))
    lines = run(worker.memory.content("p", "overview"))["lines"]
    assert text == (
        f"## overview (배경) 7/500자\n- [{lines[0]['id']}] (user) - 수율 개선"
        f"\n\n## {topics[1]['id']} (용어) 0/300자\n(비어 있음)"
    )


def test_extract_uses_the_project_topics(monkeypatch):
    worker = _worker(_Db([None]))
    topics = _custom_topics(worker)
    term = topics[1]["id"]
    model = _Model(
        '{"ops": ['
        f'{{"op": "add", "topic": "{term}", "text": "- NCE: 불량 분류",'
        ' "quote": "우리 목표는 A라인 수율 개선"},'
        # the name used before topics were editable
        '{"op": "add", "section": "overview", "text": "- A라인 수율 개선",'
        ' "quote": "우리 목표는 A라인 수율 개선"},'
        '{"op": "add", "topic": "preferences", "text": "- 표 위주",'
        ' "quote": "보고서는 표 위주로 써 줘"}'
        "]}"
    )
    monkeypatch.setattr(mw, "chat_model", lambda settings, name: model)
    changed = run(worker.extract("p", [_msg(0, "user", USER_TEXT)]))
    assert changed == [term, "overview"]  # preferences is gone
    system, request = model.messages
    assert f"- {term}: 용어 — 사내 약어와 뜻 (한도 300자)" in system.content
    assert "preferences" not in system.content
    assert f"## {term} (용어) 0/300자" in request.content


def test_a_topic_removed_before_apply_saves_nothing():
    worker = _worker()
    _custom_topics(worker)
    view = run(
        worker.apply(
            "p", "preferences", [_add("- 표 중심")], [USER_TEXT], ACTOR
        )
    )
    assert view is None


def test_per_topic_limits_apply():
    worker = _worker()
    run(
        worker.memory.put_topics(
            "p",
            [{"id": "preferences", "title": "P", "max_chars": 100}],
            expected_version=0,
            actor=Actor("user", "u-1"),
        )
    )
    long = "- 보고서는 표 위주로 " + "가" * 100
    assert (
        run(worker.apply("p", "preferences", [_add(long)], [USER_TEXT], ACTOR))
        is None
    )
    view = run(
        worker.apply("p", "preferences", [_add("- 표")], [USER_TEXT], ACTOR)
    )
    assert view is not None and view["max_chars"] == 100

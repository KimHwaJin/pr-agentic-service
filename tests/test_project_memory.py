import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from langgraph.store.memory import InMemoryStore

from api_service.routers import projects
from api_service.schemas.projects import (
    MemoryContentWrite,
    MemoryRead,
    MemoryRevert,
    MemoryTopicsRead,
    MemoryTopicsWrite,
)
from core.config import Settings
from core.memory.service import (
    DEFAULT_TOPICS,
    Actor,
    MemoryEditError,
    ProjectMemory,
    diff_lines,
    render_for_prompt,
    render_topic_index,
)
from core.models import MemoryHistory

USER = Actor("user", "u-1")
AGENT = Actor("agent", "main", "s-1", "r-1")


class _Db:
    """Async session double that keeps memory_history rows in a list."""

    def __init__(self):
        self.rows: list[MemoryHistory] = []

    def sessions(self):
        db = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def execute(self, statement, params=None):
                pass  # the advisory lock

            def add(self, row):
                row.id = len(db.rows) + 1
                db.rows.append(row)

            async def commit(self):
                pass

            async def get(self, model, key):
                return next((r for r in db.rows if r.id == key), None)

            async def scalars(self, statement):
                return SimpleNamespace(all=lambda: list(reversed(db.rows)))

        return Session()


def _memory(**limits: int) -> ProjectMemory:
    """Default topics; ``limits`` overrides max_chars by topic id (written
    directly, below the API's minimum)."""
    memory = ProjectMemory(InMemoryStore(), cast(Any, _Db()))
    if limits:
        topics = [
            {**t, "max_chars": limits.get(t["id"], t["max_chars"])}
            for t in DEFAULT_TOPICS
        ]
        memory.store.put(
            ("project_memory_topics", "p"),
            "topics",
            {"topics": topics, "version": 1, "updated_at": None},
        )
    return memory


def run(coro):
    return asyncio.run(coro)


# --- lines and authorship -------------------------------------------------


def test_diff_keeps_unchanged_lines_and_marks_new_ones():
    old = [
        {"id": "a", "text": "- one", "author": "agent"},
        {"id": "b", "text": "- two", "author": "agent"},
        {"id": "c", "text": "- three", "author": "agent"},
    ]
    lines = diff_lines(old, ["- one", "- TWO", "- three", "- four"], USER, "t")
    assert [line["text"] for line in lines] == [
        "- one",
        "- TWO",
        "- three",
        "- four",
    ]
    assert lines[0]["id"] == "a" and lines[0]["author"] == "agent"
    assert lines[2]["id"] == "c" and lines[2]["author"] == "agent"
    assert lines[1]["author"] == lines[3]["author"] == "user"
    assert len({line["id"] for line in lines}) == 4


def test_user_put_keeps_agent_lines_and_agent_may_edit_user_lines():
    memory = _memory()

    async def main():
        await memory.save_line("p", "preferences", "- 표 위주", actor=AGENT)
        put = await memory.put_content(
            "p",
            "preferences",
            "- 표 위주\n- 결론 먼저",
            expected_version=1,
            actor=USER,
        )
        user_line = put["lines"][1]
        # no lock: the agent replaces a user-written line
        replaced = await memory.save_line(
            "p",
            "preferences",
            "- 결론을 맨 앞에",
            actor=AGENT,
            line_id=user_line["id"],
        )
        return put, replaced

    put, replaced = run(main())
    assert [line["author"] for line in put["lines"]] == ["agent", "user"]
    assert put["version"] == 2
    assert replaced["content"] == "- 표 위주\n- 결론을 맨 앞에"
    assert replaced["lines"][1]["author"] == "agent"
    assert replaced["version"] == 3


def test_default_topics_are_the_four_sections():
    sections = run(_memory().contents("p"))
    assert [s["topic"] for s in sections] == [
        "overview",
        "preferences",
        "core_interests",
        "key_events",
    ]
    assert [s["title"] for s in sections] == [
        "Overview",
        "Preferences",
        "Core Interests",
        "Key Events",
    ]
    assert all(s["content"] == "" and s["version"] == 0 for s in sections)
    assert sections[3]["max_chars"] == 700


# --- limits, headings, versions ---------------------------------------------


def test_limit_is_enforced_on_writes():
    memory = _memory(overview=10)
    with pytest.raises(MemoryEditError) as refused:
        run(
            memory.put_content(
                "p", "overview", "x" * 11, expected_version=0, actor=USER
            )
        )
    assert refused.value.status == 422
    with pytest.raises(MemoryEditError):
        run(memory.save_line("p", "overview", "y" * 11, actor=AGENT))


@pytest.mark.parametrize("bad", ["# 제목", "## 소제목", "- a\n## b"])
def test_top_level_headings_are_refused(bad):
    with pytest.raises(MemoryEditError) as refused:
        run(
            _memory().put_content(
                "p", "overview", bad, expected_version=0, actor=USER
            )
        )
    assert refused.value.status == 422


def test_lower_headings_and_lists_are_fine():
    saved = run(
        _memory().put_content(
            "p",
            "overview",
            "### 목표\n- 수율 개선\n그냥 문장",
            expected_version=0,
            actor=USER,
        )
    )
    assert saved["version"] == 1 and len(saved["lines"]) == 3


def test_stale_version_is_a_conflict():
    memory = _memory()

    async def main():
        await memory.put_content(
            "p", "overview", "- a", expected_version=0, actor=USER
        )
        await memory.put_content(
            "p", "overview", "- b", expected_version=0, actor=USER
        )

    with pytest.raises(MemoryEditError) as refused:
        run(main())
    assert refused.value.status == 409


def test_unknown_topic_and_line():
    memory = _memory()
    with pytest.raises(MemoryEditError) as refused:
        run(memory.put_content("p", "x", "", expected_version=0, actor=USER))
    assert refused.value.status == 404
    with pytest.raises(MemoryEditError) as refused:
        run(memory.delete_line("p", "overview", "nope", actor=AGENT))
    assert refused.value.status == 404


# --- history and revert -----------------------------------------------------


def test_revert_restores_the_body_before_a_change():
    memory = _memory()

    async def main():
        await memory.put_content(
            "p", "overview", "- a", expected_version=0, actor=USER
        )
        await memory.save_line("p", "overview", "- b", actor=AGENT)
        history = await memory.history("p", "overview")
        agent_change = history[0]
        reverted = await memory.revert(
            "p", "overview", agent_change["id"], actor=USER
        )
        return agent_change, reverted, await memory.history("p")

    agent_change, reverted, history = run(main())
    assert agent_change["before"] == "- a"
    assert agent_change["after"] == "- a\n- b"
    assert agent_change["actor"] == {"type": "agent", "id": "main"}
    assert reverted["content"] == "- a" and reverted["version"] == 3
    assert history[0]["action"] == "revert"


def test_revert_of_another_topic_is_not_found():
    memory = _memory()

    async def main():
        await memory.put_content(
            "p", "overview", "- a", expected_version=0, actor=USER
        )
        await memory.revert("p", "preferences", 1, actor=USER)

    with pytest.raises(MemoryEditError) as refused:
        run(main())
    assert refused.value.status == 404


# --- migration of the former entries ----------------------------------------


def _legacy(store, key, category, title, content, author, created):
    return store.aput(
        ("project_memory", "p"),
        key,
        {
            "category": category,
            "title": title,
            "content": content,
            "author": author,
            "version": 1,
            "source": {},
            "created_at": created,
            "updated_at": created,
        },
    )


def test_former_entries_move_into_sections_once():
    memory = _memory(overview=5)  # limits not applied
    store = memory.store

    async def main():
        await _legacy(
            store, "e1", "background", "배경", "수율 개선", "user", "1"
        )
        await _legacy(
            store, "e2", "analysis_preferences", "분석", "표", "agent", "2"
        )
        await _legacy(
            store,
            "e3",
            "report_preferences",
            "보고서",
            "결론\n먼저",
            "user",
            "3",
        )
        await _legacy(
            store, "e4", "shared_findings", "발견", "A라인 편차", "agent", "4"
        )
        first = await memory.migrate_all_legacy()
        again = await memory.migrate_all_legacy()
        return first, again, await memory.contents("p")

    first, again, sections = run(main())
    assert (first, again) == (4, 0)
    by = {s["topic"]: s for s in sections}
    assert by["overview"]["content"] == "- 배경: 수율 개선"
    assert by["overview"]["lines"][0]["author"] == "user"
    assert by["preferences"]["content"] == "- 분석: 표\n- 보고서: 결론 먼저"
    assert by["key_events"]["content"] == "- 발견: A라인 편차"
    assert by["core_interests"]["content"] == ""
    left = run(store.asearch(("project_memory", "p")))
    assert sorted(i.key for i in left) == [
        "key_events",
        "overview",
        "preferences",
    ]


def test_a_half_done_migration_adds_nothing_twice():
    memory = _memory()
    store = memory.store

    async def main():
        await _legacy(store, "e1", "background", "배경", "x", "user", "1")
        await memory.migrate_legacy("p")
        # the entry came back (crash before its delete)
        await _legacy(store, "e1", "background", "배경", "x", "user", "1")
        await memory.migrate_legacy("p")
        return await memory.content("p", "overview")

    assert run(main())["content"] == "- 배경: x"


def test_a_migrated_section_over_its_limit_may_shrink():
    memory = _memory(overview=12)
    store = memory.store

    async def main():
        await _legacy(store, "e1", "background", "a", "x" * 20, "user", "1")
        await _legacy(store, "e2", "background", "b", "y", "user", "2")
        await memory.migrate_legacy("p")
        return await memory.delete_line("p", "overview", "e2", actor=AGENT)

    assert run(main())["content"] == "- a: " + "x" * 20


# --- prompt -----------------------------------------------------------------


def test_prompt_has_every_non_empty_topic():
    sections = [
        {"title": "Overview", "content": "- 수율 개선"},
        {"title": "Preferences", "content": ""},
        {"title": "Core Interests", "content": "- A라인"},
        {"title": "Key Events", "content": "  "},
    ]
    assert render_for_prompt(sections) == (
        "# Project memory\n\n## Overview\n- 수율 개선\n\n"
        "## Core Interests\n- A라인"
    )
    assert render_for_prompt([{"title": "Overview", "content": ""}]) == ""


# --- API --------------------------------------------------------------------


def _services(memory):
    return cast(Any, SimpleNamespace(memory=memory, settings=Settings()))


@pytest.fixture
def api(monkeypatch):
    async def allowed(services, user, project_id, write=False):
        return SimpleNamespace(id=project_id)

    monkeypatch.setattr(projects, "project_for", allowed)
    user = cast(Any, SimpleNamespace(id="u-1", role="user"))
    return _memory(), user


def test_api_get_put_history_revert(api):
    memory, user = api
    services = _services(memory)

    async def main():
        empty = await projects.get_memory("p", services, user)
        put = await projects.put_memory_content(
            "p",
            "overview",
            MemoryContentWrite(content="- a\n- b", expected_version=0),
            services,
            user,
        )
        history = await projects.memory_history(
            "p", services, user, "overview", False, 100
        )
        reverted = await projects.revert_memory_content(
            "p",
            "overview",
            MemoryRevert(history_id=history["items"][0]["id"]),
            services,
            user,
        )
        return empty, put, history, reverted

    empty, put, history, reverted = run(main())
    assert len(MemoryRead.model_validate(empty).topics) == 4
    assert put["content"] == "- a\n- b"
    assert history["items"][0]["after"] == "- a\n- b"
    assert reverted["content"] == "" and reverted["version"] == 2


@pytest.mark.parametrize(
    ("topic", "content", "version", "status"),
    [
        ("nope", "- a", 0, 404),
        ("overview", "- a", 5, 409),
        ("overview", "x" * 501, 0, 422),
        ("overview", "## b", 0, 422),
    ],
)
def test_api_refusals(api, topic, content, version, status):
    memory, user = api
    with pytest.raises(HTTPException) as refused:
        run(
            projects.put_memory_content(
                "p",
                topic,
                MemoryContentWrite(content=content, expected_version=version),
                _services(memory),
                user,
            )
        )
    assert refused.value.status_code == status


# --- topics -----------------------------------------------------------------


def _topics(memory, project="p"):
    return run(memory.topic_list(project))


def _put_topics(memory, topics, version=None, actor=USER):
    if version is None:
        version = _topics(memory)["version"]
    return run(
        memory.put_topics("p", topics, expected_version=version, actor=actor)
    )


def _edit(topic_id, **changes):
    base = next(t for t in DEFAULT_TOPICS if t["id"] == topic_id)
    return {**base, **changes}


def test_default_topics_and_old_section_items():
    memory = _memory()
    # a body written before topics existed ("section" key)
    memory.store.put(
        ("project_memory", "p"),
        "key_events",
        {
            "section": "key_events",
            "lines": [
                {"id": "a", "text": "- 2026-10-01 교체", "author": "user"}
            ],
            "version": 3,
            "updated_at": None,
        },
    )
    listing = _topics(memory)
    assert listing["version"] == 0 and listing["total_max_chars"] == 2200
    assert [(t["id"], t["max_chars"]) for t in listing["topics"]] == [
        ("overview", 500),
        ("preferences", 500),
        ("core_interests", 500),
        ("key_events", 700),
    ]
    events = listing["topics"][3]
    assert "YYYY-MM-DD" in events["description"]
    assert "최신이 위" in events["description"]
    view = run(memory.content("p", "key_events"))
    assert view["content"] == "- 2026-10-01 교체" and view["version"] == 3


def test_editing_a_topic_keeps_its_body():
    memory = _memory()
    run(
        memory.put_content(
            "p", "preferences", "- 표 위주", expected_version=0, actor=USER
        )
    )
    saved = _put_topics(
        memory,
        [
            _edit("overview"),
            _edit(
                "preferences",
                title="보고서 선호",
                description="보고서 형식만",
                max_chars=300,
            ),
            _edit("core_interests"),
            _edit("key_events"),
        ],
        version=0,
    )
    assert saved["version"] == 1
    view = run(memory.content("p", "preferences"))
    assert view["title"] == "보고서 선호" and view["content"] == "- 표 위주"
    assert view["max_chars"] == 300 and view["version"] == 1
    assert run(memory.history("p")) and all(
        h["action"] == "update" for h in run(memory.history("p"))
    )


def test_a_lowered_limit_lets_the_body_shrink_but_not_grow():
    memory = _memory()
    run(
        memory.put_content(
            "p", "overview", "x" * 300, expected_version=0, actor=USER
        )
    )
    _put_topics(
        memory,
        [_edit("overview", max_chars=100), *DEFAULT_TOPICS[1:]],
        version=0,
    )
    assert run(memory.content("p", "overview"))["content"] == "x" * 300
    with pytest.raises(MemoryEditError) as refused:
        run(memory.save_line("p", "overview", "- more", actor=AGENT))
    assert refused.value.status == 422
    shrunk = run(
        memory.put_content(
            "p", "overview", "x" * 200, expected_version=1, actor=USER
        )
    )
    assert shrunk["content"] == "x" * 200


def test_replacing_a_topic_clears_it_and_keeps_the_body_in_history():
    memory = _memory()
    run(
        memory.put_content(
            "p", "core_interests", "- A라인", expected_version=0, actor=USER
        )
    )
    saved = _put_topics(
        memory,
        [
            *DEFAULT_TOPICS[:2],
            _edit("core_interests", title="설비", replace=True),
            DEFAULT_TOPICS[3],
        ],
        version=0,
    )
    new_id = saved["topics"][2]["id"]
    assert new_id != "core_interests" and saved["topics"][2]["title"] == "설비"
    assert run(memory.content("p", new_id))["content"] == ""
    with pytest.raises(MemoryEditError) as gone:
        run(memory.content("p", "core_interests"))
    assert gone.value.status == 404
    with pytest.raises(MemoryEditError) as gone:
        run(memory.save_line("p", "core_interests", "- x", actor=AGENT))
    assert gone.value.status == 404
    assert (
        run(memory.store.aget(("project_memory", "p"), "core_interests"))
        is None
    )
    entry = run(memory.history("p"))[0]
    assert entry["action"] == "topic_replaced"
    assert entry["topic"] == "core_interests"
    assert entry["title"] == "Core Interests"
    assert (entry["before"], entry["after"]) == ("- A라인", "")
    assert entry["replaced_by"] == new_id


def test_dropping_a_topic_and_adding_one():
    memory = _memory()
    run(
        memory.put_content(
            "p",
            "key_events",
            "- 2026-10-01 교체",
            expected_version=0,
            actor=USER,
        )
    )
    saved = _put_topics(
        memory,
        [
            *DEFAULT_TOPICS[:3],
            {"title": "용어", "description": "사내 약어", "max_chars": 300},
        ],
        version=0,
    )
    assert [t["title"] for t in saved["topics"]][-1] == "용어"
    new_id = saved["topics"][-1]["id"]
    contents = run(memory.contents("p"))
    assert [c["topic"] for c in contents][-1] == new_id
    assert contents[-1]["content"] == ""  # no backfill
    entry = run(memory.history("p"))[0]
    assert entry["action"] == "topic_removed"
    assert entry["before"] == "- 2026-10-01 교체"
    assert entry["replaced_by"] is None


def test_a_removed_topic_is_restored_with_its_body():
    memory = _memory()
    run(
        memory.put_content(
            "p",
            "key_events",
            "- 2026-10-01 교체",
            expected_version=0,
            actor=USER,
        )
    )
    _put_topics(memory, list(DEFAULT_TOPICS[:3]), version=0)
    removed = run(memory.history("p"))[0]
    restored = run(memory.restore("p", removed["id"], actor=USER))
    assert restored["topics_version"] == 2
    last = restored["topics"][-1]
    assert (last["topic"], last["title"]) == ("key_events", "Key Events")
    assert last["content"] == "- 2026-10-01 교체"
    assert last["version"] == 3  # past the removal's version (2)
    assert run(memory.history("p"))[0]["action"] == "topic_restored"
    # once back, it is a topic like any other
    run(memory.save_line("p", "key_events", "- 2026-10-02 확정", actor=AGENT))
    with pytest.raises(MemoryEditError) as again:
        run(memory.restore("p", removed["id"], actor=USER))
    assert again.value.status == 409


def test_restore_needs_room_in_the_limits():
    memory = _memory()
    _put_topics(
        memory,
        [*DEFAULT_TOPICS[:3], _edit("key_events", replace=True)],
        version=0,
    )
    replaced = run(memory.history("p"))[0]
    with pytest.raises(MemoryEditError) as full:
        run(memory.restore("p", replaced["id"], actor=USER))
    assert full.value.status == 422  # 2900 > 2200
    with pytest.raises(MemoryEditError) as not_topic:
        run(memory.restore("p", 999, actor=USER))
    assert not_topic.value.status == 404


def test_restore_renames_a_title_now_taken():
    memory = _memory()
    _put_topics(
        memory,
        [
            *DEFAULT_TOPICS[:2],
            _edit("core_interests", replace=True, max_chars=200),
            _edit("key_events", max_chars=300),
        ],
        version=0,
    )
    replaced = run(memory.history("p"))[0]
    restored = run(memory.restore("p", replaced["id"], actor=USER))
    assert [t["title"] for t in restored["topics"]][-1] == (
        "Core Interests (복원)"
    )


@pytest.mark.parametrize(
    ("topics", "message"),
    [
        ([], "at least one"),
        (
            [{"title": f"t{i}", "max_chars": 100} for i in range(7)],
            "at most 6",
        ),
        (
            [
                {"title": "a", "max_chars": 2000},
                {"title": "b", "max_chars": 300},
            ],
            "over the total 2200",
        ),
        ([{"title": " ", "max_chars": 100}], "needs a title"),
        ([{"title": "x" * 41, "max_chars": 100}], "title over 40"),
        (
            [{"title": "a", "description": "d" * 201, "max_chars": 100}],
            "description over 200",
        ),
        ([{"title": "a", "max_chars": 99}], "at least 100"),
        ([{"title": "a", "max_chars": "500"}], "at least 100"),
        ([{"id": "made_up", "title": "a", "max_chars": 100}], "unknown topic"),
        (
            [
                {"id": "overview", "title": "a", "max_chars": 100},
                {"id": "overview", "title": "b", "max_chars": 100},
            ],
            "given twice",
        ),
        (
            [
                {"title": "Same", "max_chars": 100},
                {"title": "same", "max_chars": 100},
            ],
            "titled",
        ),
    ],
)
def test_topic_limits(topics, message):
    memory = _memory()
    with pytest.raises(MemoryEditError) as refused:
        _put_topics(memory, topics, version=0)
    assert refused.value.status == 422
    assert message in str(refused.value)
    assert _topics(memory)["version"] == 0


def test_six_topics_up_to_the_total_are_fine():
    memory = _memory()
    saved = _put_topics(
        memory,
        [
            {"title": f"주제 {i}", "description": " 한\n줄 ", "max_chars": 366}
            for i in range(6)
        ],
        version=0,
    )
    assert len(saved["topics"]) == 6
    assert saved["topics"][0]["description"] == "한 줄"
    assert len({t["id"] for t in saved["topics"]}) == 6


def test_stale_topics_version_is_a_conflict():
    memory = _memory()
    _put_topics(memory, list(DEFAULT_TOPICS[:3]), version=0)
    with pytest.raises(MemoryEditError) as refused:
        _put_topics(memory, list(DEFAULT_TOPICS[:2]), version=0)
    assert refused.value.status == 409


def test_unchanged_topics_are_not_a_new_version():
    memory = _memory()
    assert _put_topics(memory, list(DEFAULT_TOPICS), version=0)["version"] == 0


def test_topic_index_lists_ids_titles_descriptions_and_limits():
    index = render_topic_index(
        [
            {
                "id": "a1",
                "title": "A",
                "description": "설명",
                "max_chars": 100,
            },
            {"id": "b2", "title": "B", "description": "", "max_chars": 200},
        ]
    )
    assert index == "- a1: A — 설명 (한도 100자)\n- b2: B (한도 200자)"


def test_prompt_uses_the_current_titles():
    memory = _memory()
    run(
        memory.put_content(
            "p", "overview", "- 수율 개선", expected_version=0, actor=USER
        )
    )
    _put_topics(
        memory, [_edit("overview", title="배경"), *DEFAULT_TOPICS[1:]], 0
    )
    assert render_for_prompt(run(memory.contents("p"))) == (
        "# Project memory\n\n## 배경\n- 수율 개선"
    )


def test_api_topics_put_get_restore(api):
    memory, user = api
    services = _services(memory)

    async def main():
        await projects.put_memory_content(
            "p",
            "overview",
            MemoryContentWrite(content="- a", expected_version=0),
            services,
            user,
        )
        listing = await projects.get_memory_topics("p", services, user)
        body = MemoryTopicsWrite.model_validate(
            {
                "topics": [
                    {"title": "새 주제", "max_chars": 200},
                    *listing["topics"][1:3],
                    {**listing["topics"][3], "max_chars": 400},
                ],
                "expected_version": listing["version"],
            }
        )
        saved = await projects.put_memory_topics("p", body, services, user)
        removed = await projects.memory_history(
            "p", services, user, None, True, 100
        )
        restored = await projects.restore_memory_topic(
            "p", removed["items"][0]["id"], services, user
        )
        return listing, saved, removed, restored

    listing, saved, removed, restored = run(main())
    assert MemoryTopicsRead.model_validate(listing).version == 0
    assert MemoryTopicsRead.model_validate(saved).topics[0].title == "새 주제"
    assert removed["items"][0]["action"] == "topic_removed"
    back = MemoryRead.model_validate(restored)
    assert [t.title for t in back.topics] == [
        "새 주제",
        "Preferences",
        "Core Interests",
        "Key Events",
        "Overview",
    ]
    assert back.topics[-1].content == "- a"


@pytest.mark.parametrize(
    ("topics", "version", "status"),
    [
        ([{"title": "a", "max_chars": 100}], 3, 409),
        ([{"title": "a", "max_chars": 3000}], 0, 422),
    ],
)
def test_api_topics_refusals(api, topics, version, status):
    memory, user = api
    body = MemoryTopicsWrite.model_validate(
        {"topics": topics, "expected_version": version}
    )
    with pytest.raises(HTTPException) as refused:
        run(projects.put_memory_topics("p", body, _services(memory), user))
    assert refused.value.status_code == status


# --- agent tools ----------------------------------------------------------


class _Ctx:
    def __init__(self, memory):
        self.services = SimpleNamespace(memory=memory)
        self.project_id, self.session_id, self.run_id = "p", "s-1", "r-1"
        self.sent: list[tuple[str, dict]] = []

    async def emit(self, type, data, durable=True):
        from core.contracts import events

        events.check(type, data)
        self.sent.append((type, data))


def _tool(tool, ctx, **args):
    return run(tool.coroutine(runtime=SimpleNamespace(context=ctx), **args))


def test_tools_save_and_delete_by_topic_id_or_title():
    from agent.tools.main import delete_memory, save_memory

    memory = _memory()
    ctx = _Ctx(memory)
    topics = _put_topics(
        memory,
        [*DEFAULT_TOPICS[:3], {"title": "용어", "max_chars": 300}],
        version=0,
    )["topics"]
    term = topics[-1]["id"]
    listing = _tool(save_memory, ctx, topic="?")
    assert f"- {term}: 용어 (한도 300자)" in listing
    assert "key_events" not in listing
    saved = _tool(save_memory, ctx, topic=term, text="- NCE: 불량 분류")
    assert saved == "메모리 저장: [용어] v1"
    assert ctx.sent[-1][1]["topic"] == term
    # the title shown in the prompt works too
    _tool(save_memory, ctx, topic="용어", text="- WT: 웨이퍼 테스트")
    lines = _tool(save_memory, ctx, topic=term, line_id="?")
    assert lines.startswith(f"[용어] (topic={term})")
    first = run(memory.content("p", term))["lines"][0]["id"]
    assert (
        _tool(delete_memory, ctx, topic=term, line_id=first) == "삭제했습니다."
    )
    assert run(memory.content("p", term))["content"] == "- WT: 웨이퍼 테스트"


def test_tools_on_an_unknown_topic_list_the_topics():
    from agent.tools.main import delete_memory, save_memory

    memory = _memory()
    ctx = _Ctx(memory)
    _put_topics(memory, list(DEFAULT_TOPICS[:3]), version=0)
    for reply in (
        _tool(save_memory, ctx, topic="key_events", text="- 2026 교체"),
        _tool(delete_memory, ctx, topic="key_events", line_id="x"),
    ):
        assert reply.startswith("'key_events' 주제가 없습니다.")
        assert "- core_interests: Core Interests" in reply
    assert ctx.sent == []


def test_tool_over_the_limit_shows_the_lines():
    from agent.tools.main import save_memory

    memory = _memory(preferences=10)
    reply = _tool(
        save_memory, _Ctx(memory), topic="preferences", text="x" * 11
    )
    assert "한도를 넘습니다" in reply and "[Preferences]" in reply


def test_reporter_reads_the_preferences_topic():
    from agent import reporter

    memory = _memory()
    ctx = SimpleNamespace(
        services=SimpleNamespace(memory=memory),
        project_id="p",
        project_prompt="",
        user_text="분석",
        model="m",
    )
    run(
        memory.put_content(
            "p", "preferences", "- 표 위주", expected_version=0, actor=USER
        )
    )

    def request():
        return run(
            reporter.analysis_request(ctx, title="t", focus="f", evidence="e")
        )

    assert "- 표 위주" in request()
    _put_topics(memory, [DEFAULT_TOPICS[0]], version=0)
    assert "- 표 위주" not in request()

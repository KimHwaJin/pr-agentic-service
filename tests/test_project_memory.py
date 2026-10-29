import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from langgraph.store.memory import InMemoryStore

from api_service.routers import projects
from api_service.schemas.projects import (
    MemoryRead,
    MemoryRevert,
    MemorySectionWrite,
)
from core.config import Settings
from core.memory.service import (
    SECTIONS,
    Actor,
    MemoryEditError,
    ProjectMemory,
    diff_lines,
    render_for_prompt,
)
from core.models import MemoryHistory

LIMITS = {
    "overview": 500,
    "preferences": 500,
    "core_interests": 500,
    "key_events": 700,
}
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


def _memory(limits=None) -> ProjectMemory:
    return ProjectMemory(InMemoryStore(), cast(Any, _Db()), limits or LIMITS)


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


def test_sections_always_lists_all_four():
    sections = run(_memory().sections("p"))
    assert [s["section"] for s in sections] == list(SECTIONS)
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
    memory = _memory({**LIMITS, "overview": 10})
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


def test_unknown_section_and_line():
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


def test_revert_of_another_section_is_not_found():
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
    memory = _memory({**LIMITS, "overview": 5})  # limits not applied
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
        return first, again, await memory.sections("p")

    first, again, sections = run(main())
    assert (first, again) == (4, 0)
    by = {s["section"]: s for s in sections}
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
        return await memory.section("p", "overview")

    assert run(main())["content"] == "- 배경: x"


def test_a_migrated_section_over_its_limit_may_shrink():
    memory = _memory({**LIMITS, "overview": 12})
    store = memory.store

    async def main():
        await _legacy(store, "e1", "background", "a", "x" * 20, "user", "1")
        await _legacy(store, "e2", "background", "b", "y", "user", "2")
        await memory.migrate_legacy("p")
        return await memory.delete_line("p", "overview", "e2", actor=AGENT)

    assert run(main())["content"] == "- a: " + "x" * 20


# --- prompt -----------------------------------------------------------------


def test_prompt_has_every_non_empty_section():
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
        put = await projects.put_memory_section(
            "p",
            "overview",
            MemorySectionWrite(content="- a\n- b", expected_version=0),
            services,
            user,
        )
        history = await projects.memory_history(
            "p", services, user, "overview", 100
        )
        reverted = await projects.revert_memory_section(
            "p",
            "overview",
            MemoryRevert(history_id=history["items"][0]["id"]),
            services,
            user,
        )
        return empty, put, history, reverted

    empty, put, history, reverted = run(main())
    assert len(MemoryRead.model_validate(empty).sections) == 4
    assert put["content"] == "- a\n- b"
    assert history["items"][0]["after"] == "- a\n- b"
    assert reverted["content"] == "" and reverted["version"] == 2


@pytest.mark.parametrize(
    ("section", "content", "version", "status"),
    [
        ("nope", "- a", 0, 404),
        ("overview", "- a", 5, 409),
        ("overview", "x" * 501, 0, 422),
        ("overview", "## b", 0, 422),
    ],
)
def test_api_refusals(api, section, content, version, status):
    memory, user = api
    with pytest.raises(HTTPException) as refused:
        run(
            projects.put_memory_section(
                "p",
                section,
                MemorySectionWrite(content=content, expected_version=version),
                _services(memory),
                user,
            )
        )
    assert refused.value.status_code == status

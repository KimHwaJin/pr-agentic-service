import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.dtest.api_service.errors import ApiError
from src.dtest.api_service.routers import catalog


def _services(skills, tools):
    return SimpleNamespace(
        skills=lambda root: skills, tool_catalog=lambda: tools
    )


def run(coro):
    return asyncio.run(coro)


def _all(fetch):
    """Every item of a paged list, one item per page."""
    items, cursor = [], None
    while True:
        page = run(fetch(cursor))
        items += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            return items


def test_skills_are_light_and_paged(skills, tools):
    svc = _services(skills, tools)
    items = _all(
        lambda c: catalog.list_catalog_skills(svc, None, cursor=c, limit=1)
    )
    assert [s["name"] for s in items] == sorted(skills.skills)
    load = next(s for s in items if s["name"] == "data_load")
    assert load["tool_count"] == len(skills.skills["data_load"].tools)
    assert "body" not in load and "tools" not in load


def test_skill_search(skills, tools):
    svc = _services(skills, tools)
    page = run(catalog.list_catalog_skills(svc, None, q="DATA_LOAD", limit=50))
    assert [s["name"] for s in page["items"]] == ["data_load"]
    assert page["next_cursor"] is None


def test_a_skills_tools_keep_table_order_across_pages(skills, tools):
    svc = _services(skills, tools)
    items = _all(
        lambda c: catalog.list_catalog_tools(
            svc, None, skill="data_load", cursor=c, limit=1
        )
    )
    table = [r.tool for r in skills.skills["data_load"].tools]
    assert [t["name"] for t in items] == table
    extract = items[0]
    assert extract["skill"] == "data_load"
    assert extract["execution"] == "always"
    assert extract["outputs"] == ["data", "query"]
    assert "params" not in extract


def test_tool_search_crosses_skills(skills, tools):
    svc = _services(skills, tools)
    every = _all(
        lambda c: catalog.list_catalog_tools(svc, None, cursor=c, limit=2)
    )
    assert len(every) == sum(len(s.tools) for s in skills.skills.values())
    found = run(catalog.list_catalog_tools(svc, None, q="histogram", limit=50))
    assert [(t["skill"], t["name"]) for t in found["items"]] == [
        ("eda_analysis", "histogram_eda")
    ]


def test_tool_detail(skills, tools):
    svc = _services(skills, tools)
    detail = run(
        catalog.get_catalog_tool("extract_data", "data_load", svc, None)
    )
    params = {p["name"]: p for p in detail["params"]}
    assert params["data_type"]["required"] and params["data_type"]["doc"]
    assert not params["limit"]["required"]
    assert detail["docstring"] and detail["signature"]
    assert "code" not in detail


def test_skill_detail_has_the_body(skills, tools):
    detail = run(
        catalog.get_catalog_skill("data_load", _services(skills, tools), None)
    )
    assert "Tool list" in detail["body"]


@pytest.mark.parametrize(
    "call",
    [
        lambda svc: catalog.get_catalog_skill("nope", svc, None),
        lambda svc: catalog.get_catalog_tool("nope", "data_load", svc, None),
        lambda svc: catalog.get_catalog_tool(
            "extract_data", "nope", svc, None
        ),
        lambda svc: catalog.list_catalog_tools(svc, None, skill="nope"),
    ],
)
def test_unknown_names_are_404(skills, tools, call):
    with pytest.raises(ApiError) as err:
        run(call(_services(skills, tools)))
    assert err.value.status == 404


def test_bad_cursor_is_422(skills, tools):
    with pytest.raises(HTTPException) as err:
        run(
            catalog.list_catalog_skills(
                _services(skills, tools), None, cursor="%%%", limit=5
            )
        )
    assert err.value.status_code == 422


def test_a_listed_tool_without_a_file_is_marked_broken(skills, tools):
    load = skills.skills["data_load"]
    ghost = replace(load.tools[0], tool="ghost_tool")
    only = replace(load, tools=(ghost,))
    broken = replace(skills, skills={"data_load": only})
    page = run(
        catalog.list_catalog_tools(
            _services(broken, tools), None, skill="data_load", limit=5
        )
    )
    assert page["items"][0]["broken"]

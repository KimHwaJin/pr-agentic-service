import asyncio
from types import SimpleNamespace

import pytest

from src.dtest.api_service.errors import ApiError
from src.dtest.api_service.routers import catalog


def _services(skills, tools):
    return SimpleNamespace(
        skills=lambda root: skills, tool_catalog=lambda: tools
    )


def test_every_skill_comes_with_its_tools(skills, tools):
    result = asyncio.run(catalog.get_catalog(_services(skills, tools), None))
    names = [s.name for s in result.skills]
    assert names == sorted(skills.skills)
    load = next(s for s in result.skills if s.name == "data_load")
    extract = next(t for t in load.tools if t.name == "extract_data")
    assert extract.execution == "always"
    assert extract.broken is None
    params = {p.name: p for p in extract.params}
    assert params["data_type"].required and params["data_type"].doc
    assert not params["limit"].required
    assert extract.outputs == ["data", "query"]
    # no tool code, no skill body in the list
    assert "body" not in load.model_dump()
    assert "docstring" not in extract.model_dump()


def test_search_keeps_matching_skills(skills, tools):
    services = _services(skills, tools)
    found = asyncio.run(catalog.get_catalog(services, None, q="extract_DATA"))
    assert [s.name for s in found.skills] == ["data_load"]
    none = asyncio.run(catalog.get_catalog(services, None, q="no-such-x"))
    assert none.skills == []


def test_skill_detail_has_body_and_docstrings(skills, tools):
    detail = asyncio.run(
        catalog.get_catalog_skill("data_load", _services(skills, tools), None)
    )
    assert "Tool list" in detail.body
    assert all(t.docstring for t in detail.tools)


def test_unknown_skill_is_404(skills, tools):
    with pytest.raises(ApiError) as err:
        asyncio.run(
            catalog.get_catalog_skill("nope", _services(skills, tools), None)
        )
    assert err.value.status == 404


def test_a_listed_tool_without_a_file_is_marked_broken(skills, tools):
    from dataclasses import replace

    load = skills.skills["data_load"]
    ghost = replace(load.tools[0], tool="ghost_tool")
    broken = replace(
        skills, skills={"data_load": replace(load, tools=(ghost,))}
    )
    result = asyncio.run(catalog.get_catalog(_services(broken, tools), None))
    assert result.skills[0].tools[0].broken

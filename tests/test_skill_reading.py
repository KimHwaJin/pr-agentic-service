"""read_skill lists tools in one line each; read_tool gives the details."""

import asyncio
from types import SimpleNamespace

from agent.tools.analysis import read_skill, read_tool


def _runtime(skills, tools):
    services = SimpleNamespace(
        skills=lambda kind: skills, tool_catalog=lambda: tools
    )
    return SimpleNamespace(context=SimpleNamespace(services=services))


def test_read_skill_gives_one_line_per_tool(skills, tools):
    text = asyncio.run(
        read_skill.coroutine("data_load", _runtime(skills, tools))
    )
    assert tools.summary("extract_data") in text
    assert tools.tools["extract_data"].signature not in text
    assert "read_tool" in text


def test_read_tool_reads_several_names(skills, tools):
    text = asyncio.run(
        read_tool.coroutine(
            ["extract_data", "nope"], _runtime(skills, tools)
        )
    )
    assert f"### extract_data\n{tools.describe('extract_data')}" in text
    assert "### nope\n'nope' tool이 없습니다." in text

def test_tool_source_drops_docstring_and_keeps_inner_imports(tools):
    tool = tools.tools["histogram_eda"]
    assert '"""' not in tool.code
    assert "import matplotlib.pyplot as plt" in tool.code
    assert tool.code.startswith("def histogram_eda(")
    compile(tool.code, "histogram_eda", "exec")


def test_tool_outputs_come_from_returned_dict_keys(tools):
    assert tools.tools["merge_data"].outputs == ("merged_data", "shape")
    assert [
        p.name for p in tools.tools["merge_data"].params if p.required
    ] == [
        "left_data",
        "right_data",
        "join_columns",
    ]


def test_skill_tool_table(skills):
    eda = {t.tool: t for t in skills.skills["eda_analysis"].tools}
    assert eda["compute_statistics"].execution == "always"
    assert eda["boxplot_eda"].execution == "conditional"
    assert eda["boxplot_eda"].condition_tool == "compute_statistics"


def test_skill_table_columns_by_header_name():
    from src.dtest.core.assets import tool_table

    rows, problems = tool_table(
        "| 역할 | Tool | 입력 데이터 | 실행 방식 |\n"
        "|---|---|---|---|\n"
        "| 추출 | `extract_data` | NCE | 항상 실행 |\n"
        "| 그림 | `boxplot_eda` |  | 조건부 실행 |\n"
        "| 틀림 | extract | x | 항상 |\n"
        "| 모자람 | `a` |\n"
    )
    assert [r.tool for r in rows] == ["extract_data", "boxplot_eda"]
    assert rows[0].role == "추출"
    assert rows[0].extra == (("입력 데이터", "NCE"),)
    assert rows[1].execution == "conditional"
    assert rows[1].extra == ()
    assert len(problems) == 2


def test_other_tables_are_not_tool_lists():
    from src.dtest.core.assets import tool_table

    rows, problems = tool_table("| 컬럼 | 뜻 |\n|---|---|\n| `LOT` | 로트 |\n")
    assert rows == [] and problems == []


def test_every_analysis_skill_table_reads_cleanly():
    from pathlib import Path

    from src.dtest.core.assets import SkillCatalog, ToolCatalog

    root = Path(__file__).resolve().parents[1]
    skills = SkillCatalog.load_many(
        [root / "assets/skills", root / "catalogs/analysis_test/skills"]
    )
    tools = ToolCatalog.load_many(
        [root / "assets/tools", root / "catalogs/analysis_test/tools"]
    )
    assert skills.errors == {}
    for skill in skills.skills.values():
        assert skill.tools, skill.name
        missing = [t.tool for t in skill.tools if t.tool not in tools.tools]
        assert not missing, (skill.name, missing)


def test_tool_parameters_reach_the_model_under_their_own_names():
    # a parameter named "args" is renamed to "v__args" in the tool schema,
    # so the model's calls never match the function
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from src.dtest.agent.graph import TOOLS

    for tool in TOOLS:
        sent = convert_to_openai_tool(tool)["function"]["parameters"]
        names = set(sent.get("properties", {}))
        assert not {n for n in names if n.startswith("v__")}, tool.name


def test_summary_prompt_keeps_the_messages_slot():
    from src.dtest.agent.prompts import load_prompt

    prompt = load_prompt("summary")
    body = prompt.render(max_chars=6000)
    assert "\n<messages>\n" in body and "6000자" in body
    assert body.format(messages="X").count("X") == 1  # no stray braces

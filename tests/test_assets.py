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


def test_tool_parameters_reach_the_model_under_their_own_names():
    # a parameter named "args" is renamed to "v__args" in the tool schema,
    # so the model's calls never match the function
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from agent.graph import TOOLS

    for tool in TOOLS:
        sent = convert_to_openai_tool(tool)["function"]["parameters"]
        names = set(sent.get("properties", {}))
        assert not {n for n in names if n.startswith("v__")}, tool.name

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

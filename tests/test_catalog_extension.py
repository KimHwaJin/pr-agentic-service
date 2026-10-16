"""The test catalog (catalogs/analysis_test) on top of the base catalog.

Structure tests run everywhere. Tool tests need the analysis libraries:
``uv run --group catalog-test pytest tests/test_catalog_extension.py``.
"""

from pathlib import Path

import pytest

from core.assets import SkillCatalog, ToolCatalog
from core.config import ROOT, Settings

EXT = ROOT / "catalogs/analysis_test"


def _catalogs():
    settings = Settings(catalog_extensions=[Path("catalogs/analysis_test")])
    skills = SkillCatalog.load_many(settings.catalog_roots("skills"))
    tools = ToolCatalog.load_many(settings.catalog_roots("tools"))
    knowledge = SkillCatalog.load_many(settings.catalog_roots("knowledge"))
    return skills, tools, knowledge


def test_extension_adds_on_top_and_overrides_by_name():
    base = SkillCatalog.load(ROOT / "assets/skills")
    skills, tools, knowledge = _catalogs()
    assert set(base.skills) < set(skills.skills)  # base skills all still there
    assert "eda_analysis" in skills.skills  # untouched base skill
    # data_load is replaced by the extension's version
    assert [t.tool for t in skills.skills["data_load"].tools] == [
        "load_synthetic"
    ]
    assert "extract_data" in tools.tools  # base tools stay loadable
    assert "semiconductor_test_data" in knowledge.skills
    assert "analysis_datasets" in knowledge.skills
    assert not tools.errors


def test_without_the_extension_the_base_catalog_is_unchanged():
    settings = Settings(catalog_extensions=[])
    skills = SkillCatalog.load_many(settings.catalog_roots("skills"))
    assert set(skills.skills) == {
        "data_load",
        "dataset_preparation",
        "eda_analysis",
    }
    assert [t.tool for t in skills.skills["data_load"].tools][0] == (
        "extract_data"
    )


def test_every_skill_tool_exists_and_conditions_point_inside_the_skill():
    skills, tools, _ = _catalogs()
    for skill in skills.skills.values():
        names = {t.tool for t in skill.tools}
        for rule in skill.tools:
            assert rule.tool in tools.tools, (skill.name, rule.tool)
            if rule.execution == "conditional":
                assert rule.condition_tool in names, (skill.name, rule)


def _tool(name: str):
    """The tool function, built the way the executor runs it."""
    _, tools, _ = _catalogs()
    namespace: dict = {}
    exec(tools.tools[name].code, namespace)  # noqa: S102
    return namespace[name]


@pytest.fixture(scope="module")
def libs():
    pytest.importorskip("pandas")
    pytest.importorskip("sklearn")
    pytest.importorskip("statsmodels")
    import matplotlib

    matplotlib.use("Agg")


@pytest.fixture(scope="module")
def data(libs):
    load = _tool("load_synthetic")
    return {kind: load(kind)["data"] for kind in ("nce", "wt", "fdc", "yield")}


def test_planted_facts_are_in_the_data(data):
    import numpy as np

    nce = data["nce"].drop_duplicates()
    sn = "SN OPEN MASK MACRO.max_val"
    lot3 = nce[nce.alias_lot_id == "L3"][sn].mean()
    others = nce[nce.alias_lot_id != "L3"][sn].mean()
    assert 0.25 < lot3 - others < 0.35  # only L3 shifted
    corr = nce.filter(like="max_val").corr()
    assert corr.loc["DNW MASK MACRO.max_val", "MBO MASK MACRO.max_val"] > 0.8
    assert (
        0.2
        < corr.loc["M4C MASK MACRO.max_val", "REP MASK MACRO.max_val"]
        < 0.4
    )
    assert data["nce"]["PMX MASK MACRO.max_val"].isna().sum() > 0
    assert data["nce"].duplicated().sum() > 0

    wt = data["wt"]
    edge = np.sqrt((wt.x - 11) ** 2 + (wt.y - 11) ** 2) / 10 > 0.8
    ratio = wt[edge]["PT1H.p_f"].mean() / wt[~edge]["PT1H.p_f"].mean()
    assert 1.7 < ratio < 2.5  # edge fails about twice as often

    fdc = data["fdc"]
    b = fdc[fdc.eqp_id == "ETCH_B"]
    late = b[b.timestamp >= "2026-09-25"].CH_PRESSURE.mean()
    early = b[b.timestamp < "2026-09-18"].CH_PRESSURE.mean()
    assert late - early > 1.0
    a = fdc[fdc.eqp_id == "ETCH_A"]
    assert abs(a[a.timestamp >= "2026-09-25"].CH_PRESSURE.mean() - 50) < 0.2
    assert (fdc.GAS_FLOW < 0).sum() == 6

    yld = data["yield"]
    gap = yld.groupby("eqp_id").yield_pct.mean()
    assert 3 < gap["ETCH_A"] - gap["ETCH_B"] < 8


def test_conditions_filter_the_data(libs):
    load = _tool("load_synthetic")
    assert set(load("nce", lot_cd="L2")["data"].alias_lot_id) == {"L2"}
    cols = load("nce", process="SN OPEN")["data"].filter(like="max_val")
    assert list(cols.columns) == ["SN OPEN MASK MACRO.max_val"]
    fdc = load(
        "fdc", process="ETCH_A", start_dt="2026-09-10", end_dt="2026-09-11"
    )
    assert (
        set(fdc["data"].eqp_id) == {"ETCH_A"}
        and len(fdc["data"]) == 2 * 2 * 24
    )
    assert load("wt", limit=10)["shape"][0] == 10
    with pytest.raises(ValueError, match="nce, wt, fdc, yield"):
        load("defect")


def test_every_tool_runs_and_finds_the_planted_facts(data, tmp_path):
    plots = str(tmp_path)
    nce, wt, fdc, yld = data["nce"], data["wt"], data["fdc"], data["yield"]
    sn = "SN OPEN MASK MACRO.max_val"

    assert _tool("check_missing")(nce)["has_missing"]
    assert _tool("check_duplicates")(nce)["has_duplicates"]
    assert _tool("validate_ranges")(fdc)["violations"] == {"GAS_FLOW": 6}
    clean = _tool("clean_data")(nce)["data"]
    assert not clean.isna().any().any() and not clean.duplicated().any()

    one = _tool("filter_rows")(nce, "alias_lot_id", values=["L3"])["data"]
    assert set(one.alias_lot_id) == {"L3"}
    per_lot = _tool("aggregate_by")(clean, ["alias_lot_id"], [sn])["data"]
    assert per_lot.set_index("alias_lot_id")[sn].idxmax() == "L3"
    zoned = _tool("split_by_zone")(wt)["data"]
    assert set(zoned.zone) == {"edge", "center"}

    assert _tool("normality_test")(clean, sn)["groups"] == 1
    lot3 = clean.assign(
        is_l3=(clean.alias_lot_id == "L3").map({True: "L3", False: "other"})
    )
    assert (
        _tool("compare_groups_ttest")(lot3, sn, "is_l3", "L3", "other")[
            "p_value"
        ]
        < 1e-6
    )
    assert (
        _tool("compare_groups_nonparametric")(lot3, sn, "is_l3")["p_value"]
        < 1e-6
    )
    anova = _tool("anova_test")(clean, sn, "alias_lot_id")
    assert anova["highest_group"] == "L3"
    with pytest.raises(ValueError, match="3개 이상"):
        _tool("anova_test")(lot3, sn, "is_l3")
    assert (
        _tool("chi_square_test")(zoned, "zone", "PT1H.p_f")["p_value"] < 1e-6
    )

    b = fdc[fdc.eqp_id == "ETCH_B"]
    daily = _tool("resample_series")(
        fdc, value_columns=["CH_PRESSURE"], group_column="eqp_id"
    )
    assert daily["shape"][0] == 60
    rolled = _tool("rolling_stats")(
        fdc, "CH_PRESSURE", group_column="eqp_id", output_dir=plots
    )
    assert (
        rolled["summary"]["ETCH_B"]["last"]
        > rolled["summary"]["ETCH_A"]["last"] + 1
    )
    change = _tool("detect_change_points")(
        fdc, "CH_PRESSURE", group_column="eqp_id"
    )
    groups = {c["group"] for c in change["change_points"]}
    assert "ETCH_B" in groups and "ETCH_A" not in groups
    one_chamber = b[b.chamber_id == "CH1"]
    assert (
        _tool("decompose_series")(
            fdc[(fdc.eqp_id == "ETCH_A") & (fdc.chamber_id == "CH1")],
            "CH_TEMP",
            output_dir=plots,
        )["seasonal_amplitude"]
        > 2
    )
    chart = _tool("control_chart")(
        one_chamber, "CH_PRESSURE", "timestamp", output_dir=plots
    )
    assert (
        chart["out_of_control"] > 0 and chart["first_out_time"] >= "2026-09-18"
    )
    cap = _tool("process_capability")(
        fdc[fdc.eqp_id == "ETCH_A"], "CH_PRESSURE", 47.0, 53.0
    )
    assert cap["cpk"] > 1.33
    with pytest.raises(ValueError):
        _tool("process_capability")(fdc, "CH_PRESSURE", 53.0, 47.0)

    assert (
        _tool("wafer_map_plot")(wt, "PT1H.p_f", output_dir=plots)["dies"] > 300
    )
    zones = _tool("zone_statistics")(wt, "PT1H.p_f")
    assert zones["outer_to_inner_ratio"] > 1.2
    edge = _tool("edge_effect_test")(wt, "PT1H.p_f")
    assert edge["significant"] and edge["ratio"] > 1.7

    features = [
        "eqp_id",
        "chamber_id",
        "avg_pressure",
        "avg_temp",
        "rf_power",
        "cd_mean",
    ]
    importance = _tool("feature_importance")(yld, "yield_pct", features)
    top = {i["feature"] for i in importance["importances"][:3]}
    assert top & {"avg_pressure", "eqp_id_ETCH_A", "eqp_id_ETCH_B"}
    reg = _tool("linear_regression")(
        yld, "yield_pct", ["eqp_id", "avg_pressure"]
    )
    assert reg["coefficients"]["eqp_id_ETCH_B"] < -2 and reg["r2"] > 0.5
    clusters = _tool("kmeans_clustering")(per_lot, n_clusters=2)
    assert sum(clusters["cluster_sizes"].values()) == 6

    assert _tool("slow_operation")(seconds=0, data=1)["data"] == 1
    with pytest.raises(ValueError, match="'scale' 또는 'offset'"):
        _tool("fragile_transform")(nce, mode="multiply")
    with pytest.raises(ValueError, match="0보다 커야"):
        _tool("fragile_transform")(nce, factor=0)

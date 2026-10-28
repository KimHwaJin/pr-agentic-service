"""Registers (and promotes) the analysis_test catalog's example workflows.

    uv run python scripts/seed_test_workflows.py            # add
    uv run python scripts/seed_test_workflows.py --remove   # take them away

Talks to a running service (BASE_URL, default http://localhost:8080) with
the dev login, so the service must run with the analysis_test catalog
enabled. Every workflow it adds carries the tag ``test-catalog``; --remove
deletes exactly those.
"""

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dtest.agent import plan_format  # noqa: E402
from src.dtest.core.assets import SkillCatalog  # noqa: E402
from src.dtest.core.config import ROOT  # noqa: E402

TAG = "test-catalog"
CATALOG = ROOT / "src/dtest/catalogs/analysis_test"

WORKFLOWS = [
    {
        "name": "NCE 기본 EDA",
        "immediate": True,
        "queries": [
            "NCE 데이터 기술통계와 분포 보여줘",
            "NCE 측정값 분포랑 상관 봐줘",
        ],
        "calls": [
            {
                "skill": "data_load",
                "tool": "load_synthetic",
                "args": {"data_type": "nce"},
            },
            {
                "skill": "eda_analysis",
                "tool": "compute_statistics",
                "args": {"data": "@0.data"},
            },
            {
                "skill": "eda_analysis",
                "tool": "histogram_eda",
                "args": {"data": "@0.data"},
            },
            {
                "skill": "eda_analysis",
                "tool": "boxplot_eda",
                "args": {"data": "@0.data"},
            },
            {
                "skill": "eda_analysis",
                "tool": "correlation_analysis",
                "args": {"data": "@0.data"},
            },
        ],
    },
    {
        "name": "LOT별 측정값 차이 검정",
        "queries": [
            "LOT별로 측정값 차이가 있는지 검정해줘",
            "LOT 간 평균 비교해줘",
        ],
        "calls": [
            {
                "skill": "data_load",
                "tool": "load_synthetic",
                "args": {"data_type": "nce"},
            },
            {
                "skill": "statistical_test",
                "tool": "normality_test",
                "args": {
                    "data": "@0.data",
                    "value_column": "$input",
                    "group_column": "alias_lot_id",
                },
            },
            {
                "skill": "statistical_test",
                "tool": "anova_test",
                "args": {
                    "data": "@0.data",
                    "value_column": "$input",
                    "group_column": "alias_lot_id",
                },
            },
        ],
    },
    {
        "name": "FDC 센서 drift 점검",
        "queries": [
            "설비 센서값이 언제부터 변했는지 봐줘",
            "FDC 센서 drift 확인해줘",
        ],
        "calls": [
            {
                "skill": "data_load",
                "tool": "load_synthetic",
                "args": {"data_type": "fdc"},
            },
            {
                "skill": "time_series",
                "tool": "rolling_stats",
                "args": {
                    "data": "@0.data",
                    "value_column": "$input",
                    "group_column": "eqp_id",
                },
            },
            {
                "skill": "time_series",
                "tool": "detect_change_points",
                "args": {
                    "data": "@0.data",
                    "value_column": "$input",
                    "group_column": "eqp_id",
                },
            },
        ],
    },
    {
        "name": "센서 관리도와 공정능력",
        "queries": [
            "센서값 관리 상태와 Cpk 봐줘",
            "관리도 그려줘",
        ],
        "calls": [
            {
                "skill": "data_load",
                "tool": "load_synthetic",
                "args": {"data_type": "fdc", "process": "$input"},
            },
            {
                "skill": "spc",
                "tool": "control_chart",
                "args": {
                    "data": "@0.data",
                    "value_column": "$input",
                    "time_column": "timestamp",
                },
            },
            {
                "skill": "spc",
                "tool": "process_capability",
                "args": {
                    "data": "@0.data",
                    "value_column": "$input",
                    "lsl": "$input",
                    "usl": "$input",
                },
            },
        ],
    },
    {
        "name": "WT edge 효과 점검",
        "queries": [
            "wafer 가장자리에 불량이 많은지 봐줘",
            "WT 불량 위치별로 봐줘",
        ],
        "calls": [
            {
                "skill": "data_load",
                "tool": "load_synthetic",
                "args": {"data_type": "wt"},
            },
            {
                "skill": "wafer_map",
                "tool": "wafer_map_plot",
                "args": {"data": "@0.data", "value_column": "PT1H.p_f"},
            },
            {
                "skill": "wafer_map",
                "tool": "zone_statistics",
                "args": {"data": "@0.data", "value_column": "PT1H.p_f"},
            },
            {
                "skill": "wafer_map",
                "tool": "edge_effect_test",
                "args": {"data": "@0.data", "value_column": "PT1H.p_f"},
            },
        ],
    },
]


def client() -> httpx.Client:
    base = os.environ.get("BASE_URL", "http://localhost:8080") + "/api/v1"
    c = httpx.Client(base_url=base, timeout=60)
    c.get("/auth/login/sso", params={"return_to": "/"})
    c.headers["X-CSRF-Token"] = c.get("/auth/session").json()["csrf_token"]
    return c


def add(c: httpx.Client) -> None:
    skills = SkillCatalog.load_many(
        [ROOT / "src/dtest/assets/skills", CATALOG / "skills"]
    )
    for spec in WORKFLOWS:
        document, _ = plan_format.to_workflow(
            spec["calls"],
            name=spec["name"],
            user_request=spec["queries"][0],
            skills=skills,
        )
        document["workflow"]["allow_immediate_execution"] = bool(
            spec.get("immediate")
        )
        created = c.post(
            "/workflows",
            json={
                "document": document,
                "user_queries": spec["queries"],
                "tags": [TAG],
            },
        )
        created.raise_for_status()
        workflow = created.json()
        promoted = c.post(f"/workflows/{workflow['id']}/promote")
        promoted.raise_for_status()
        print(f"added  {spec['name']} ({workflow['id']})")


def remove(c: httpx.Client) -> None:
    for item in c.get("/workflows", params={"tag": TAG}).json():
        c.delete(f"/workflows/{item['id']}").raise_for_status()
        print(f"removed {item['name']} ({item['id']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    c = client()
    try:
        remove(c) if args.remove else add(c)
    finally:
        c.close()

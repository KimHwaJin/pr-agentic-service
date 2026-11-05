---
name: yield_analysis
description: 수율을 LOT·웨이퍼·설비 단위로 요약하고, 불량 bin 파레토를 보고, 수율·불량과 관련된 공통 요인(설비, 챔버, 구역 등)을 찾는 skill.
---

# Yield Analysis

## capabilities

- 그룹별 수율과 전체 대비 차이, 낮은 순 정렬 (`yield_summary`). die별 pass/fail(WT) 또는 수율 컬럼(yield) 모두 가능
- 불량 bin 파레토 차트와 그룹별 bin 구성 (`bin_pareto`)
- 범주형 요인별 수율·불량 차이의 유의성 순위, 가장 나쁜 수준 (`commonality_analysis`)

## limitations

- 수치형 변수(압력 등)의 영향은 보지 않음 (`modeling`)
- 위치(edge·center) 효과를 보려면 먼저 `dataset_preparation`의 `split_by_zone`으로 구역 컬럼을 붙여야 함

## when_to_use

- "LOT별 수율이 어떤가", "수율이 낮은 웨이퍼는", "어떤 bin이 제일 많나"
- "수율 저하가 어느 설비·챔버와 관련 있나" (공통성 분석)

## not_for

- wafer map 같은 위치 분포 (`wafer_map`)
- 수치형 공정 변수의 영향 크기 (`modeling`)

## typical_previous_skill

- `data_load`, `dataset_preparation`

## typical_next_skills

- `statistical_test`, `modeling`, `visualization`, `report_export`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `yield_summary` | 항상 실행 | 그룹별 수율을 볼 때 | 없음 | 그룹별 수율 |
| `bin_pareto` | 항상 실행 | bin·불량 유형 컬럼이 있을 때 | 없음 | 불량 bin 파레토 |
| `commonality_analysis` | 조건부 실행 | `yield_summary`에서 그룹 간 수율 차이가 보이고 비교할 범주형 요인이 있을 때 | `yield_summary` | 공통 요인 찾기 |

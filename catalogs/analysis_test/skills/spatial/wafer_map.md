---
name: wafer_map
description: die 좌표가 있는 데이터(NCE, WT)를 wafer 위치 기준으로 보는 skill. wafer map, 중심에서의 거리(ring)별 요약, edge 효과 검정.
---

# Wafer Map

## capabilities

- 좌표별 평균값 wafer map (`wafer_map_plot`)
- 중심 거리 구간별 요약 (`zone_statistics`)
- edge와 center 차이 검정 (`edge_effect_test`)

## limitations

- die 좌표(x, y)가 없는 데이터에는 쓸 수 없음

## when_to_use

- "가장자리에 불량이 많나", "wafer 위치별로 다른가"를 물을 때

## not_for

- 좌표가 없는 FDC·수율 데이터

## typical_previous_skill

- `data_load`, `dataset_preparation`

## typical_next_skills

- `statistical_test`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `wafer_map_plot` | 항상 실행 | 위치별 분포를 볼 때 | 없음 | wafer map |
| `zone_statistics` | 항상 실행 | 거리 구간별로 비교할 때 | 없음 | 구간 요약 |
| `edge_effect_test` | 조건부 실행 | `zone_statistics`의 outer_to_inner_ratio가 1.2 이상이거나 0.8 이하일 때 | `zone_statistics` | edge 효과 검정 |

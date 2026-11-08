---
name: visualization
description: 두 변수의 관계를 산점도(회귀선, 그룹 색)로, 두 범주 조합별 값을 히트맵으로 그리는 시각화 skill (seaborn).
---

# Visualization

## capabilities

- 두 수치형 변수 산점도와 회귀선, 그룹별 색 구분, 상관계수 (`scatter_plot`)
- 두 범주(LOT × 설비, 날짜 × 챔버 등) 조합별 집계 히트맵과 최대·최소 칸 (`pivot_heatmap`)

## limitations

- 유의성 검정은 하지 않음 (`statistical_test`)
- 한 변수의 분포(히스토그램, 박스플롯)는 `eda_analysis`

## when_to_use

- "압력과 수율 관계를 그려줘", "설비별로 색을 나눠서 보여줘"
- "LOT별·챔버별 평균을 한눈에 보여줘"

## not_for

- wafer 좌표 기준 그림 (`wafer_map`)
- 시간 추세 그림 (`time_series`)

## typical_previous_skill

- `data_load`, `dataset_preparation`, `anomaly_detection`, `yield_analysis`

## typical_next_skills

- `statistical_test`, `modeling`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `scatter_plot` | 항상 실행 | 두 수치형 변수의 관계를 볼 때 | 없음 | 산점도 |
| `pivot_heatmap` | 항상 실행 | 두 범주 조합별 값을 비교할 때 | 없음 | 히트맵 |

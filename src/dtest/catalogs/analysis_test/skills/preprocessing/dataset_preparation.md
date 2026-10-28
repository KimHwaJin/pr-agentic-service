---
name: dataset_preparation
description: 둘 이상의 데이터를 공통 키로 결합하거나, 행을 고르고, 그룹별로 집계하고, wafer edge·center 구역을 나누는 skill.
---

# Dataset Preparation

## capabilities

- 공통 키 기준 데이터 결합 (`merge_data`)
- 무작위 또는 층화 표본 추출 (`sample_data`)
- 값 목록이나 범위로 행 고르기 (`filter_rows`)
- 그룹별 집계 (`aggregate_by`)
- die 좌표로 edge·center 구역 컬럼 붙이기 (`split_by_zone`)

## limitations

- 결측값 대체, 이상치 제거 같은 정제는 하지 않음 (`data_quality`)

## when_to_use

- 여러 데이터셋을 함께 분석하거나, 일부만 고르거나, 그룹 단위로 비교해야 할 때

## not_for

- 단일 데이터를 그대로 분석하는 경우

## typical_previous_skill

- `data_load`, `data_quality`

## typical_next_skills

- `eda_analysis`, `statistical_test`, `wafer_map`, `modeling`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `merge_data` | 항상 실행 | 둘 이상의 데이터셋을 공통 키로 결합해야 할 때 | 없음 | 단일 분석 데이터 생성 |
| `sample_data` | 항상 실행 | 분석 데이터 행 수가 많을 때 | 없음 | 분석용 표본 생성 |
| `filter_rows` | 항상 실행 | 특정 LOT·설비·범위만 분석할 때 | 없음 | 행 선택 |
| `aggregate_by` | 항상 실행 | LOT·웨이퍼·설비 단위로 비교할 때 | 없음 | 그룹 집계 |
| `split_by_zone` | 항상 실행 | wafer edge와 center를 나눠 볼 때 | 없음 | 구역 컬럼 추가 |

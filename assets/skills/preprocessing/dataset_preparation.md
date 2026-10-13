---
name: dataset_preparation
description: 둘 이상의 데이터를 공통 키로 결합하거나 분석용 표본을 추출하는 skill.
---

# Dataset Preparation

## capabilities

- 공통 키 기준 데이터 결합 (`merge_data`)
- 무작위 또는 층화 표본 추출 (`sample_data`)

## limitations

- 결측치 대체, 이상치 제거 같은 정제는 수행하지 않음

## when_to_use

- 여러 데이터셋을 함께 분석해야 하거나 데이터가 커서 표본이 필요한 경우

## not_for

- 단일 데이터를 그대로 분석하는 경우

## typical_previous_skill

- `data_load`

## typical_next_skills

- `eda_analysis`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `merge_data` | 항상 실행 | 둘 이상의 데이터셋을 공통 키로 결합해야 할 때 | 없음 | 단일 분석 데이터 생성 |
| `sample_data` | 항상 실행 | 분석 데이터 행 수가 많을 때 | 없음 | 분석용 표본 생성 |

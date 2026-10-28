---
name: modeling
description: 목표 값(수율, 불량 여부 등)에 영향이 큰 변수를 찾고, 선형 관계를 정량화하고, 비슷한 대상끼리 군집으로 나누는 skill.
---

# Modeling

## capabilities

- 랜덤 포레스트 변수 중요도 (`feature_importance`)
- 선형회귀 계수와 유의성 (`linear_regression`)
- K-means 군집 (`kmeans_clustering`)

## limitations

- 모델을 저장하거나 배포하지 않음
- 인과 관계를 판단하지 않음

## when_to_use

- "수율에 영향을 주는 요인이 뭔가", "원인 후보를 찾아줘", "비슷한 LOT끼리 묶어줘"

## not_for

- 단순 상관 확인 (`eda_analysis`)

## typical_previous_skill

- `data_load`, `dataset_preparation`, `data_quality`

## typical_next_skills

- 없음

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `feature_importance` | 항상 실행 | 목표 컬럼이 정해진 경우 | 없음 | 영향 변수 순위 |
| `linear_regression` | 조건부 실행 | 목표가 수치형이고 `feature_importance` 상위 변수의 효과 크기를 정량화할 때 | `feature_importance` | 선형 효과 추정 |
| `kmeans_clustering` | 항상 실행 | 비슷한 대상끼리 묶을 때 | 없음 | 군집 |

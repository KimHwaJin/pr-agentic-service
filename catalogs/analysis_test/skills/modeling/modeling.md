---
name: modeling
description: 목표 값(수율, 불량 여부 등)에 영향이 큰 변수를 찾고(랜덤 포레스트, XGBoost, 결정 트리 규칙), 선형·로지스틱 회귀로 효과를 정량화하고, 주성분(PCA)이나 군집으로 비슷한 대상·변수를 묶는 skill.
---

# Modeling

## capabilities

- 랜덤 포레스트 변수 중요도 (`feature_importance`)
- XGBoost 예측 성능과 변수 중요도, 비선형 관계에 강함 (`xgboost_model`)
- "어떤 조건일 때 나빠지나"를 사람이 읽는 규칙으로 (`decision_tree_rules`)
- 선형회귀 계수와 유의성 (`linear_regression`)
- 불량 여부 같은 0/1 목표의 로지스틱 회귀 odds ratio (`logistic_regression`)
- 주성분 분석, 함께 움직이는 변수 묶음 (`pca_analysis`)
- K-means 군집 (`kmeans_clustering`)

## limitations

- 모델을 저장하거나 배포하지 않음
- 인과 관계를 판단하지 않음
- 범주형 요인(설비, 챔버)별 수율 차이만 볼 때는 `yield_analysis`의 `commonality_analysis`가 더 단순함

## when_to_use

- "수율에 영향을 주는 요인이 뭔가", "원인 후보를 찾아줘", "비슷한 LOT끼리 묶어줘"
- "어떤 조건에서 불량이 나나", "측정값 여러 개를 요약해줘"

## not_for

- 단순 상관 확인 (`eda_analysis`)

## typical_previous_skill

- `data_load`, `dataset_preparation`, `data_quality`

## typical_next_skills

- `report_export`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `feature_importance` | 항상 실행 | 목표 컬럼이 정해진 경우 | 없음 | 영향 변수 순위 |
| `xgboost_model` | 항상 실행 | 목표 컬럼이 정해지고 비선형 관계나 예측 성능까지 볼 때 | 없음 | 부스팅 모델과 영향 변수 |
| `decision_tree_rules` | 항상 실행 | 목표가 나빠지는 조건을 규칙으로 설명해야 할 때 | 없음 | 조건 규칙 |
| `linear_regression` | 조건부 실행 | 목표가 수치형이고 `feature_importance` 상위 변수의 효과 크기를 정량화할 때 | `feature_importance` | 선형 효과 추정 |
| `logistic_regression` | 조건부 실행 | `feature_importance`의 task가 classification(목표가 0/1)이고 상위 변수의 효과를 정량화할 때 | `feature_importance` | 이진 결과 효과 추정 |
| `pca_analysis` | 항상 실행 | 수치형 변수가 많아 묶음이나 요약 축을 볼 때 | 없음 | 주성분 |
| `kmeans_clustering` | 항상 실행 | 비슷한 대상끼리 묶을 때 | 없음 | 군집 |

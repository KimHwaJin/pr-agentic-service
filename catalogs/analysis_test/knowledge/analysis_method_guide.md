---
name: analysis_method_guide
description: 질문 유형에 따라 어떤 통계 검정·모델·관리도를 고를지와 결과 해석 기준(p-value, 효과 크기, 상관 강도, 모델 점수)을 정리한 지식. 분석 방법을 고르거나 결과를 해석할 때 사용한다.
---

# 분석 방법 고르기

## 그룹 비교

| 상황 | 방법 |
| --- | --- |
| 두 그룹, 정규분포 | Welch t-검정 (`compare_groups_ttest`) |
| 두 그룹, 정규분포 아님 | Mann-Whitney U (`compare_groups_nonparametric`) |
| 세 그룹 이상, 정규분포 | ANOVA (`anova_test`) → 유의하면 Tukey HSD (`tukey_posthoc`)로 다른 쌍 찾기 |
| 세 그룹 이상, 정규분포 아님 | Kruskal-Wallis (`kruskal_test`) |
| 범주 두 개의 연관 (예: 구역 × 불량 여부) | 카이제곱 (`chi_square_test`) |

- 표본이 수천 행이면 아주 작은 차이도 p < 0.05가 된다. p-value와 함께 평균 차이(실제 크기)를 같이 말한다.
- 여러 쌍을 한꺼번에 비교하면 우연히 유의한 쌍이 생긴다. 쌍 비교는 Tukey HSD처럼 보정한 결과를 쓴다.

## 관계

- 상관 강도(|r|): 0.1 미만 거의 없음, 0.1~0.3 약함, 0.3~0.7 중간, 0.7 이상 강함.
- 선형 관계면 Pearson, 순위·비선형 단조 관계나 이상치가 있으면 Spearman (`correlation_test`).
- 상관은 인과가 아니다. 공정 순서나 설비 이력 같은 근거가 있을 때만 원인 후보로 말한다.

## 원인 후보 찾기

- 범주형 요인(설비, 챔버, 경로)과 수율·불량: 공통성 분석 (`commonality_analysis`).
- 수치형·범주형이 섞인 여러 변수: 랜덤 포레스트 (`feature_importance`) 또는 XGBoost (`xgboost_model`) 중요도로 후보를 좁히고, 선형회귀 (`linear_regression`)나 로지스틱 회귀 (`logistic_regression`)로 효과 크기를 말한다.
- 사람이 읽는 조건이 필요하면 얕은 결정 트리 (`decision_tree_rules`).
- 모델 점수: 회귀 r2는 0.3 미만이면 설명력이 약하다. 분류 AUC는 0.5가 무작위, 0.7 이상이면 쓸 만하다.

## 시간 변화

- 언제 바뀌었나: 변화점 (`detect_change_points`), CUSUM (`cusum_chart`).
- 꾸준히 오르거나 내리나, 얼마나 빠른가: 추세 검정 (`trend_test`)의 tau·p-value와 하루당 기울기.
- 하루 주기 같은 반복 성분: 분해 (`decompose_series`).

## 이상치

- 한 컬럼 기준: IQR 1.5배(기본) 또는 z-score 3. 설비마다 수준이 다르면 설비별로 기준을 잡는다 (`detect_outliers`의 `group_column`).
- 여러 변수 조합이 이상한 행: Isolation Forest (`isolation_forest_outliers`).
- 이상치는 먼저 원인(계측 오류인지 실제 공정 이상인지)을 확인하고 지운다.

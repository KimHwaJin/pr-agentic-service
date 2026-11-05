---
name: statistical_test
description: 그룹 간 평균·분포 차이(LOT끼리, 설비끼리 등), 어느 그룹 쌍이 다른지(사후검정), 두 수치형 변수의 상관, 범주형 변수의 연관이 통계적으로 유의한지 검정하는 skill.
---

# Statistical Test

## capabilities

- 정규성 검정 (`normality_test`)
- 두 그룹 평균 비교, Welch t-검정 (`compare_groups_ttest`)
- 두 그룹 분포 비교, Mann-Whitney U (`compare_groups_nonparametric`)
- 세 그룹 이상 평균 비교, ANOVA (`anova_test`)
- 세 그룹 이상 분포 비교, Kruskal-Wallis (`kruskal_test`)
- ANOVA 뒤 어느 그룹 쌍이 다른지, Tukey HSD (`tukey_posthoc`)
- 두 수치형 변수의 상관계수와 p-value, Pearson·Spearman·Kendall (`correlation_test`)
- 범주형 두 변수의 독립성, 카이제곱 (`chi_square_test`)

## limitations

- 다중 비교 보정은 `tukey_posthoc`에서만 함
- 시간에 따른 변화(추세, 변화점)는 다루지 않음 (`time_series`)
- 관리 한계·공정능력은 다루지 않음 (`spc`)

## when_to_use

- "LOT끼리 차이가 있나", "설비별로 다른가"처럼 그룹 차이의 유의성을 물을 때
- "어느 LOT가 다른가"처럼 다른 그룹을 특정해야 할 때
- "두 측정값의 상관이 유의한가"를 물을 때

## not_for

- 단순히 분포나 상관 행렬을 보고 싶을 때 (`eda_analysis`)

## typical_previous_skill

- `data_load`, `dataset_preparation`

## typical_next_skills

- `report_export`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `normality_test` | 항상 실행 | 그룹 비교 전 | 없음 | 정규성 확인 |
| `compare_groups_ttest` | 조건부 실행 | `normality_test`의 is_normal이 true이고 비교할 그룹이 2개일 때 | `normality_test` | 두 그룹 평균 비교 |
| `compare_groups_nonparametric` | 조건부 실행 | `normality_test`의 is_normal이 false이고 비교할 그룹이 2개일 때 | `normality_test` | 두 그룹 분포 비교 |
| `anova_test` | 조건부 실행 | `normality_test`의 is_normal이 true이고 groups가 3 이상일 때 | `normality_test` | 여러 그룹 평균 비교 |
| `kruskal_test` | 조건부 실행 | `normality_test`의 is_normal이 false이고 groups가 3 이상일 때 | `normality_test` | 여러 그룹 분포 비교 |
| `tukey_posthoc` | 조건부 실행 | `anova_test`의 p_value가 0.05 미만일 때 | `anova_test` | 다른 그룹 쌍 찾기 |
| `correlation_test` | 항상 실행 | 두 수치형 변수의 상관 유의성을 볼 때 | 없음 | 상관 검정 |
| `chi_square_test` | 항상 실행 | 두 범주형 변수의 연관을 볼 때 | 없음 | 독립성 검정 |

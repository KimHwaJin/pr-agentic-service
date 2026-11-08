---
name: analysis_planning_map
description: 분석 요청을 어떤 데이터와 skill 순서로 풀지, tool을 어떻게 잇고 조건부 tool을 언제 실행할지 정리한 분석 계획 지도. 데이터 분석 요청이면 start_analysis로 넘기기 전에 읽고, 해당하는 계획을 context에 요약해 넣는다.
---

# 분석 계획 지도

분석 담당은 이 문서를 직접 읽지 못한다. 요청에 맞는 질문 유형의 skill 순서와 주의점만 골라 `start_analysis`의 context에 적는다. 아래 계획은 시작점이며, 사용자가 범위를 정했으면 그에 맞춰 줄인다. 검정 방법의 선택 근거와 결과 해석 기준은 `analysis_method_guide`를 본다.

## 기본 순서

1. `data_load`: 데이터는 항상 `load_synthetic`으로 불러온다.
2. `data_quality` (선택): 품질을 묻거나 결과를 믿을 수 있는지 확인이 필요할 때. 극단값이 결과를 흔들 수 있으면 `anomaly_detection`을 함께 본다.
3. `dataset_preparation` (선택): 결합, 행 선택, 집계, 표본 추출, 구역 나누기가 필요할 때.
4. 분석 skill: 질문에 맞는 것만 고른다.
5. `report_export` (선택): 사용자가 파일로 달라고 할 때만.

`test_tools`는 사용자가 시험이라고 지목할 때만 쓴다.

## 데이터별로 가능한 분석

| data_type | 단위 | 쓸 수 있는 분석 skill | 쓸 수 없는 것 |
|---|---|---|---|
| `nce` | die별 공정 측정 | `eda_analysis`, `anomaly_detection`, `statistical_test`, `wafer_map`, `modeling`, `visualization` | `time_series` (시간 컬럼 없음) |
| `wt` | die별 pass/fail, bin | `wafer_map`, `yield_analysis`, `statistical_test`, `modeling`, `visualization` | `time_series` |
| `fdc` | 설비·챔버별 시간당 센서 | `time_series`, `spc`, `eda_analysis`, `anomaly_detection`, `statistical_test`, `visualization` | `wafer_map` (좌표 없음) |
| `yield` | LOT·웨이퍼별 수율 | `yield_analysis`, `modeling`, `statistical_test`, `eda_analysis`, `visualization` | `wafer_map`, `time_series` |

`nce`와 `wt`만 `merge_data`로 결합한다 (`join_columns: ["alias_lot_id", "wf_id", "x", "y"]`). `yield`의 LOT(YL01~YL40)은 NCE·WT의 LOT(L1~L6)과 달라 결합하지 않는다.

## 질문 유형별 계획

| 질문 | 데이터 | skill 순서와 tool | 인자와 판단 |
|---|---|---|---|
| 데이터 품질이 괜찮나 | 물어본 데이터 | `data_load` → `data_quality`: `check_missing`, `check_duplicates`, `validate_ranges`, 문제가 있으면 `clean_data` | 정상 범위를 사용자가 말했으면 `validate_ranges.rules`와 `clean_data.clip_ranges`에 같은 값을 준다 |
| 튀는 값, 이상한 웨이퍼·시점 | 물어본 데이터 | `data_load` → `anomaly_detection`: `detect_outliers`, 변수 조합까지 보면 `isolation_forest_outliers` | 설비마다 수준이 다르면 `group_column: "eqp_id"` |
| 분포, 이상치, 변수 상관 | 물어본 데이터 | `data_load` → `eda_analysis` | 품질 언급이 있으면 `data_quality`를 앞에 넣는다 |
| LOT끼리, 설비끼리 차이가 있나 | `nce`, `yield`, `fdc` | `data_load` → `statistical_test`: `normality_test` 후 그룹 수와 정규성으로 분기 | `value_column`, `group_column` 지정. LOT은 `alias_lot_id`, 설비는 `eqp_id`(2개) |
| 어느 LOT가 다른가 | `nce`, `yield` | 위와 같고, ANOVA가 유의하면 `tukey_posthoc` | 정규가 아니면 `kruskal_test`로 그친다 |
| 두 측정값 상관이 유의한가 | `nce`, `fdc`, `yield` | `data_load` → `statistical_test`: `correlation_test` | `x_column`, `y_column` |
| 가장자리 불량이 많나, 위치별로 다른가 | `wt` 또는 `nce` | `data_load` → `wafer_map`: `wafer_map_plot`, `zone_statistics`, 비율이 벌어지면 `edge_effect_test` | 불량이면 `value_column: "PT1H.p_f"` |
| 구역과 불량이 연관되나 | `wt` | `data_load` → `dataset_preparation`: `split_by_zone` → `statistical_test`: `chi_square_test` | `column_a: "zone"`, `column_b: "PT1H.p_f"`. `split_by_zone`의 data를 입력으로 쓴다 |
| LOT별 수율, 낮은 웨이퍼, 많은 bin | `yield` 또는 `wt` | `data_load` → `yield_analysis`: `yield_summary`, `bin_pareto` | `yield`는 `yield_column: "yield_pct"`, `wt`는 `fail_column: "PT1H.p_f"`. bin은 `bin_column: "PT1H.symbol"` (`wt`만) |
| 수율 저하가 어느 설비·챔버와 관련 있나 | `yield` | `data_load` → `yield_analysis`: `yield_summary`, 차이가 보이면 `commonality_analysis` | `target_column: "yield_pct"`, `factor_columns: ["eqp_id", "chamber_id"]` |
| 수율 저하에 영향 주는 공정 변수 | `yield` | `data_load` → `modeling`: `feature_importance`, 상위 변수를 `linear_regression`으로 정량화 | `target_column: "yield_pct"` |
| 측정값과 불량의 관계 | `nce` + `wt` | `data_load` 두 번 → `dataset_preparation`: `merge_data` → `modeling`: `feature_importance`, `logistic_regression` | `target_column: "PT1H.p_f"` |
| 어떤 조건에서 불량이 나나 | `yield` 또는 `nce` + `wt` | `modeling`: `decision_tree_rules` | 사람이 읽을 규칙이 필요할 때 |
| 측정값 여러 개를 요약, 비슷한 대상 묶기 | `nce`, `yield` | `modeling`: `pca_analysis`, `kmeans_clustering` | LOT 단위로 묶으려면 먼저 `aggregate_by`로 집계한다 |
| 센서가 언제부터 변했나, drift가 있나 | `fdc` | `data_load` → `time_series`: `rolling_stats`, `detect_change_points`, `trend_test` | `group_column: "eqp_id"`, `time_column: "timestamp"` |
| 주기 성분이 있나 | `fdc` | `data_load` → `dataset_preparation`: `filter_rows` → `time_series`: `resample_series` → `decompose_series` | 설비·챔버 하나로 거른 뒤 분해한다 |
| 공정이 관리 상태인가, Cpk는 | `fdc` | `data_load` → `dataset_preparation`: `filter_rows` → `spc`: `control_chart`, `process_capability`, 작은 drift가 의심되면 `cusum_chart` | 설비 하나로 거른다. Cpk는 `lsl`, `usl`이 필요하며 없으면 `$input` |
| 웨이퍼·LOT·날짜 단위 관리 | `nce`, `yield`, `fdc` | `spc`: `xbar_s_chart` | `subgroup_column` 지정 |
| 관계나 조합을 그림으로 | 물어본 데이터 | `visualization`: `scatter_plot`, `pivot_heatmap` | 설비별 색은 `hue_column` |
| 결과를 파일로 | 앞 분석의 DataFrame | `report_export`: `export_excel`, 큰 데이터는 `export_parquet` | 사용자가 파일을 요청할 때만 |

## tool을 잇는 출력 이름

다음 호출의 `data`에는 앞 호출의 DataFrame 출력을 넘긴다. 출력 이름이 tool마다 다르다.

| 출력 | tool |
|---|---|
| `data` | `load_synthetic`, `clean_data`, `filter_rows`, `aggregate_by`, `split_by_zone`, `resample_series`, `rolling_stats`, `detect_outliers`, `isolation_forest_outliers`, `kmeans_clustering`, `pca_analysis`, `yield_summary`, `pivot_heatmap` |
| `merged_data` | `merge_data` |
| `sampled_data` | `sample_data` |

점검, 검정, 그림 tool은 DataFrame을 돌려주지 않는다. 뒤에 이어지는 tool에는 그 앞의 DataFrame을 그대로 넘긴다.

## 조건부 tool 판단

| tool | 볼 결과 | 실행 기준 |
|---|---|---|
| `boxplot_eda` | `compute_statistics.outlier_ratio` | 이상치 비율이 1% 이상인 컬럼이 있을 때 |
| `correlation_analysis` | `compute_statistics.numeric_columns` | 수치형 컬럼이 2개 이상일 때 |
| `isolation_forest_outliers` | `detect_outliers` 결과 | 수치형 변수가 2개 이상이고 변수 조합의 이상까지 봐야 할 때 |
| `clean_data` | `has_missing`, `has_duplicates`, `has_violations` | 셋 중 하나라도 true일 때 |
| `compare_groups_ttest` | `normality_test.is_normal`, `groups` | 정규이고 그룹이 2개일 때 |
| `compare_groups_nonparametric` | `normality_test.is_normal`, `groups` | 정규가 아니고 그룹이 2개일 때 |
| `anova_test` | `normality_test.is_normal`, `groups` | 정규이고 그룹이 3개 이상일 때 |
| `kruskal_test` | `normality_test.is_normal`, `groups` | 정규가 아니고 그룹이 3개 이상일 때 |
| `tukey_posthoc` | `anova_test.p_value` | 0.05 미만일 때 |
| `edge_effect_test` | `zone_statistics.outer_to_inner_ratio` | 1.2 이상이거나 0.8 이하일 때 |
| `linear_regression` | `feature_importance.importances`, `task` | 목표가 수치형(`task`가 regression)이고 상위 변수의 효과를 정량화할 때 |
| `logistic_regression` | `feature_importance.importances`, `task` | `task`가 classification이고 상위 변수의 효과를 정량화할 때 |
| `cusum_chart` | `control_chart.out_of_control` | 0이지만 작은 drift가 의심될 때 |
| `decompose_series` | `resample_series.shape` | 행 수가 주기의 2배 이상일 때 |
| `commonality_analysis` | `yield_summary.lowest`, `highest` | 그룹 간 수율 차이가 보이고 비교할 범주형 요인이 있을 때 |

## 계획할 때 주의점

- `normality_test`에는 `group_column`을 반드시 준다. 없으면 groups가 1이 되어 비교 tool이 실행되지 않는다. 표본이 8개 미만인 그룹이 있으면 is_normal은 false로 나온다.
- `control_chart`, `cusum_chart`, `process_capability`, `decompose_series`는 한 계열만 받는다. FDC는 설비가 섞여 있으므로 먼저 `filter_rows`로 거른다.
- `clean_data`는 `clip_ranges`로 준 범위만 제거한다. 범위 위반을 지우려면 해당 범위를 넘긴다.
- 사용자가 정상 범위를 말하지 않으면 `validate_ranges`는 음수만 위반으로 본다.
- 위치 효과를 수율 요인으로 보려면 `split_by_zone`으로 `zone` 컬럼을 먼저 붙인다.
- `modeling` 결과는 관련성이지 인과가 아니다. 상위 변수는 그룹 비교나 회귀로 효과 크기를 확인한다.

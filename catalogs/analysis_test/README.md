# analysis_test: 시험용 분석 카탈로그

`assets/`(기본 카탈로그) 위에 겹쳐 읽는 확장 카탈로그입니다. Agent 동작을 시험하려고 만든 것으로, 실제 분석 tool은 다른 팀이 관리합니다.

## 켜고 끄기

- 켜기: `config.yml`의 `CATALOG_EXTENSIONS: ["catalogs/analysis_test"]`, 로컬은 compose의 `CATALOG_EXTENSIONS` (지금은 로컬만 켜져 있음)
- 끄기(원복): 그 줄을 지우면 `assets/`만 읽습니다. `assets/`의 파일은 하나도 바꾸지 않았습니다.
- 이름이 같으면 확장이 이깁니다. 이 카탈로그는 `data_load`, `dataset_preparation` skill을 덮어씁니다(합성 데이터 `load_synthetic`, 행 선택·집계·구역 tool 추가). 기본 tool(`extract_data` 등)은 그대로 읽힙니다. 이 카탈로그의 skill이 부르는 tool은 모두 이 카탈로그의 `tools/`에 있습니다(`merge_data`, `sample_data`는 기본과 같은 파일을 복사해 둠).

## 구성

| skill | tool |
| --- | --- |
| `data_load` (덮어씀) | `load_synthetic` |
| `data_quality` | `check_missing`, `check_duplicates`, `validate_ranges`, `clean_data` |
| `dataset_preparation` (덮어씀) | `merge_data`, `sample_data` (기본에서 복사), `filter_rows`, `aggregate_by`, `split_by_zone` |
| `eda_analysis` (기본 그대로) | `compute_statistics`, `histogram_eda`, `boxplot_eda`, `correlation_analysis` |
| `anomaly_detection` | `detect_outliers`, `isolation_forest_outliers` |
| `statistical_test` | `normality_test`, `compare_groups_ttest`, `compare_groups_nonparametric`, `anova_test`, `kruskal_test`, `tukey_posthoc`, `correlation_test`, `chi_square_test` |
| `time_series` | `resample_series`, `rolling_stats`, `detect_change_points`, `trend_test`, `decompose_series` |
| `spc` | `control_chart`, `xbar_s_chart`, `cusum_chart`, `process_capability` |
| `wafer_map` | `wafer_map_plot`, `zone_statistics`, `edge_effect_test` |
| `yield_analysis` | `yield_summary`, `bin_pareto`, `commonality_analysis` |
| `modeling` | `feature_importance`, `xgboost_model`, `decision_tree_rules`, `linear_regression`, `logistic_regression`, `pca_analysis`, `kmeans_clustering` |
| `visualization` | `scatter_plot`, `pivot_heatmap` |
| `report_export` | `export_excel`, `export_parquet` |
| `analysis_planning_map` (계획 지도, 실행 tool 없음) | 없음 |
| `test_tools` (시험 전용) | `slow_operation`, `fragile_transform` |

지식 문서: `analysis_method_guide`, `analysis_datasets`, `fdc_sensor_data`, `yield_definitions`, `spc_basics` (기본 `semiconductor_test_data`도 그대로).

## 쓸 수 있는 라이브러리

tool은 executor 커널에서 돌고, 커널에 있는 라이브러리만 import할 수 있습니다.

- numpy, pandas, scipy, scikit-learn, matplotlib, seaborn, xgboost, pyarrow, python-dotenv, requests, minio, lakes, pyspark, openpyxl
- Python 표준 라이브러리

`tests/test_catalog_extension.py`가 `assets/`와 이 카탈로그의 모든 tool 파일 import를 이 목록과 대조합니다. 목록이 바뀌면 그 테스트의 `RUNTIME_LIBRARIES`도 함께 고치세요. 예전에 statsmodels를 쓰던 `decompose_series`(고전 가법 분해)와 `linear_regression`(OLS, t 분포 p-value)은 numpy·pandas·scipy로 다시 썼고, 이름·인자·반환 키는 그대로입니다.

## 합성 데이터와 심어 둔 정답

`load_synthetic`은 고정 seed로 데이터를 만듭니다. 같은 조건이면 같은 데이터입니다. 아래 사실을 일부러 심어 두었고, `tests/test_catalog_extension.py`가 데이터와 tool 결과로 확인합니다. **Agent에게 보이는 skill·지식 문서에는 적지 않습니다.**

| 정답 | 데이터 |
| --- | --- |
| LOT `L3`만 `SN OPEN MASK MACRO.max_val` 평균이 약 +0.3 높음 | nce |
| `DNW`와 `MBO` 측정값 상관 약 0.86, 나머지 쌍은 약 0.3 | nce |
| `PMX` 측정값 결측 약 1%, 중복 행 약 0.5% | nce |
| wafer edge die의 fail 비율이 center의 약 2배 | wt |
| `SN OPEN` 값이 큰 die의 fail 비율이 더 높음 | nce + wt |
| `ETCH_B`의 `CH_PRESSURE`가 2026-09-18부터 서서히 증가(drift), `ETCH_A`는 그대로 | fdc |
| `CH_TEMP`에 하루 주기 변동 | fdc |
| `GAS_FLOW` 음수(계측 오류) 6행 | fdc |
| `ETCH_B`를 거친 LOT의 수율이 약 4%p 낮고, 압력이 높을수록 수율이 낮음 | yield |

## tool 테스트

```bash
uv run --group catalog-test pytest tests/test_catalog_extension.py
```

`xgboost_model` 테스트는 xgboost가 있을 때만 돕니다. Linux 휠이 300MB짜리 GPU 라이브러리를 끌고 와서 `catalog-test` 그룹에 넣지 않았습니다. 돌려 보려면 `uv pip install xgboost-cpu`(Linux·Windows) 또는 `uv pip install xgboost`(macOS) 후 실행하세요.

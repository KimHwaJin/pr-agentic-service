# analysis_test: 시험용 분석 카탈로그

`assets/`(기본 카탈로그) 위에 겹쳐 읽는 확장 카탈로그입니다. Agent 동작을 시험하려고 만든 것으로, 실제 분석 tool은 다른 팀이 관리합니다.

## 켜고 끄기

- 켜기: `config.yml`(로컬) 또는 `config.{APP_ENV}.yml`에 `catalog_extensions: [catalogs/analysis_test]` (지금은 로컬 `config.yml`만 켜져 있음)
- 끄기(원복): 그 줄을 지우면 `assets/`만 읽습니다. `assets/`의 파일은 하나도 바꾸지 않았습니다.
- 이름이 같으면 확장이 이깁니다. 이 카탈로그는 `data_load`, `dataset_preparation` skill을 덮어씁니다(합성 데이터 `load_synthetic`, 행 선택·집계·구역 tool 추가). 기본 tool(`extract_data` 등)은 그대로 읽힙니다.

## 구성

| skill | tool |
| --- | --- |
| `data_load` (덮어씀) | `load_synthetic` |
| `data_quality` | `check_missing`, `check_duplicates`, `validate_ranges`, `clean_data` |
| `dataset_preparation` (덮어씀) | `merge_data`, `sample_data` (기본), `filter_rows`, `aggregate_by`, `split_by_zone` |
| `eda_analysis` (기본 그대로) | `compute_statistics`, `histogram_eda`, `boxplot_eda`, `correlation_analysis` |
| `statistical_test` | `normality_test`, `compare_groups_ttest`, `compare_groups_nonparametric`, `anova_test`, `chi_square_test` |
| `time_series` | `resample_series`, `rolling_stats`, `detect_change_points`, `decompose_series` |
| `spc` | `control_chart`, `process_capability` |
| `wafer_map` | `wafer_map_plot`, `zone_statistics`, `edge_effect_test` |
| `modeling` | `feature_importance`, `linear_regression`, `kmeans_clustering` |
| `test_tools` (시험 전용) | `slow_operation`, `fragile_transform` |

지식 문서: `analysis_datasets`, `fdc_sensor_data`, `yield_definitions`, `spc_basics` (기본 `semiconductor_test_data`도 그대로).

tool은 executor 커널에서 pandas, numpy, scipy, scikit-learn, statsmodels, matplotlib을 씁니다(로컬 executor 테스트 환경에 있음).

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

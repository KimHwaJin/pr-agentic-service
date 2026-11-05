---
name: anomaly_detection
description: 측정값·센서값에서 이상치(튀는 값)를 찾는 skill. 컬럼별 IQR·z-score 기준과, 여러 변수를 함께 보는 다변량 이상치(Isolation Forest)를 다룬다.
---

# Anomaly Detection

## capabilities

- 컬럼별 이상치 수, 그룹(설비 등)마다 기준을 따로 잡기, 행마다 `is_outlier` 표시 (`detect_outliers`)
- 여러 변수의 조합이 이상한 행 찾기, 행마다 `anomaly_score`·`is_anomaly` 표시 (`isolation_forest_outliers`)

## limitations

- 이상치를 지우거나 바꾸지 않음 (정리는 `data_quality`의 `clean_data`)
- 시간에 따른 평균 변화는 다루지 않음 (`time_series`, `spc`)
- 업무 규칙(정상 범위) 위반은 `data_quality`의 `validate_ranges`가 봄

## when_to_use

- "튀는 값이 있나", "이상한 웨이퍼·시점을 찾아줘"를 물을 때
- 모델링이나 검정 전에 극단값이 결과를 흔드는지 확인할 때

## not_for

- 결측·중복 점검 (`data_quality`)
- 관리 한계 기준 판단 (`spc`)

## typical_previous_skill

- `data_load`, `data_quality`

## typical_next_skills

- `data_quality`, `eda_analysis`, `visualization`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `detect_outliers` | 항상 실행 | 데이터가 준비된 경우 | 없음 | 컬럼별 이상치 |
| `isolation_forest_outliers` | 조건부 실행 | 수치형 변수가 2개 이상이고 변수 조합의 이상까지 봐야 할 때 | `detect_outliers` | 다변량 이상치 |

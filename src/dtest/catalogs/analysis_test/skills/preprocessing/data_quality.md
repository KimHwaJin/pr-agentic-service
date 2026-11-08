---
name: data_quality
description: 결측값, 중복 행, 허용 범위를 벗어난 값을 점검하고, 문제가 있으면 정리한 데이터를 만드는 skill.
---

# Data Quality

## capabilities

- 컬럼별 결측값 수와 비율 (`check_missing`)
- 중복 행 수 (`check_duplicates`)
- 허용 범위 위반 수 (`validate_ranges`, 기본은 음수 위반)
- 중복 제거, 결측 처리, 범위 위반 행 제거 (`clean_data`)

## limitations

- 결측값을 모델로 추정해 채우지 않음 (제거 또는 중앙값만)
- 업무 규칙(정상 범위)은 사용자가 알려 주지 않으면 음수만 위반으로 봄
- `clean_data`는 `clip_ranges`로 준 범위만 제거함. `validate_ranges`에서 나온 위반을 지우려면 그 범위를 `clip_ranges`로 넘겨야 함
- `clean_data`는 조건부라 그 출력을 항상 실행 tool의 입력으로 이을 수 없음. 정리된 데이터로 분석까지 요청받아도 계획은 `clean_data`까지만 세우고, 정리 후 분석은 실행 결과를 본 뒤 `run_custom_code`로 함 (결과 변수는 딕셔너리이므로 observations의 var에서 `["data"]`로 DataFrame을 꺼냄)

## when_to_use

- 사용자가 데이터 품질을 물을 때
- 분석 전에 데이터를 믿을 수 있는지 확인해야 할 때

## not_for

- 이미 정제된 데이터를 다시 점검할 때

## typical_previous_skill

- `data_load`, `anomaly_detection`

## typical_next_skills

- `eda_analysis`, `anomaly_detection`, `statistical_test`, `dataset_preparation`, `modeling`, `report_export`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `check_missing` | 항상 실행 | 데이터가 준비된 경우 | 없음 | 결측 점검 |
| `check_duplicates` | 항상 실행 | 데이터가 준비된 경우 | 없음 | 중복 점검 |
| `validate_ranges` | 항상 실행 | 데이터가 준비된 경우 | 없음 | 범위 위반 점검 |
| `clean_data` | 조건부 실행 | `check_missing`의 has_missing, `check_duplicates`의 has_duplicates, `validate_ranges`의 has_violations 중 하나라도 true일 때 (세 점검을 모두 본 뒤 판단) | `validate_ranges` | 정리된 데이터 생성 |

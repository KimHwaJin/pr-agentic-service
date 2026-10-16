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

## when_to_use

- 사용자가 데이터 품질을 물을 때
- 분석 전에 데이터를 믿을 수 있는지 확인해야 할 때

## not_for

- 이미 정제된 데이터를 다시 점검할 때

## typical_previous_skill

- `data_load`

## typical_next_skills

- `eda_analysis`, `statistical_test`, `dataset_preparation`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `check_missing` | 항상 실행 | 데이터가 준비된 경우 | 없음 | 결측 점검 |
| `check_duplicates` | 항상 실행 | 데이터가 준비된 경우 | 없음 | 중복 점검 |
| `validate_ranges` | 항상 실행 | 데이터가 준비된 경우 | 없음 | 범위 위반 점검 |
| `clean_data` | 조건부 실행 | 결측·중복·범위 위반 점검 결과 중 하나라도 문제가 있을 때 | `validate_ranges` | 정리된 데이터 생성 |

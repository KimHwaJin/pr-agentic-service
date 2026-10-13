---
name: data_load
description: 사용자 데이터 선택 조건으로 원천 데이터를 추출하고 데이터 유형별 wide 분석 형식으로 변환하는 skill. 분석의 첫 단계에서 사용한다.
---

# Data Load

## capabilities

- 사용자 선택 조건(data_type, lot_cd, process, 기간)을 `extract_data`에 전달
- NCE 데이터를 `transform_nce`, WT 데이터를 `transform_wt`로 wide 형식 변환
- 변환한 데이터를 다음 skill에 전달

## limitations

- 결합, 표본 추출, 품질 진단은 수행하지 않음
- S3에 없는 데이터는 데이터레이크에서 적재하므로 수시간 이상 걸릴 수 있음

## when_to_use

- 분석할 NCE 또는 WT 데이터를 새로 불러와야 하는 경우

## not_for

- 이미 커널에 로드된 데이터만 사용하는 경우

## typical_previous_skill

- 없음

## typical_next_skills

- `dataset_preparation`, `eda_analysis`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `extract_data` | 항상 실행 | 데이터 선택 조건이 확정된 경우 | 없음 | 원천 데이터 추출 |
| `transform_nce` | 항상 실행 | `data_type=nce` | 없음 | NCE wide 데이터 생성 |
| `transform_wt` | 항상 실행 | WT 계열 data type | 없음 | WT wide 데이터 생성 |

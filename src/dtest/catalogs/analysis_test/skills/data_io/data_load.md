---
name: data_load
description: 분석할 데이터(NCE 공정 측정, WT 웨이퍼 테스트, FDC 설비 센서 시계열, LOT·웨이퍼 수율)를 조건(LOT, 공정·설비, 기간, 행 수)대로 불러오는 skill. 분석의 첫 단계에서 사용한다.
---

# Data Load

## capabilities

- 데이터 유형과 조건(LOT, 공정 또는 설비, 기간, 최대 행 수)을 받아 wide 분석 형식(DataFrame)으로 불러옴 (`load_synthetic`)
- 데이터 유형: `nce`(die별 공정 마스크 측정값), `wt`(die별 테스트 pass/fail·bin), `fdc`(설비·챔버별 시간당 센서값), `yield`(LOT·웨이퍼별 수율과 공정 조건)

## limitations

- 결합, 표본 추출, 품질 정제는 하지 않음 (`dataset_preparation`, `data_quality`)
- 시험용 합성 데이터임 (같은 조건이면 같은 데이터)

## when_to_use

- 어떤 분석이든 데이터를 처음 불러올 때

## not_for

- 이미 불러온 데이터를 다시 가공할 때

## typical_previous_skill

- 없음

## typical_next_skills

- `data_quality`, `dataset_preparation`, `eda_analysis`, `time_series`, `spc`, `wafer_map`, `statistical_test`, `modeling`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `load_synthetic` | 항상 실행 | 분석할 데이터 유형과 조건이 정해진 경우 | 없음 | 조건에 맞는 데이터 불러오기 |

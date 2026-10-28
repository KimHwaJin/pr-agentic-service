---
name: time_series
description: 설비 센서처럼 시간에 따라 쌓인 값의 추세, 이동 평균, 평균이 바뀐 시점(변화점), 주기 성분을 분석하는 skill.
---

# Time Series

## capabilities

- 일정 간격으로 묶어 집계 (`resample_series`)
- 이동 평균·이동 표준편차와 그래프 (`rolling_stats`)
- 평균이 크게 바뀐 시점 찾기 (`detect_change_points`)
- 추세·주기·잔차 분해 (`decompose_series`)

## limitations

- 예측(forecast) 모델은 만들지 않음
- 한 그룹 안에서는 변화점을 하나만 찾음

## when_to_use

- "센서값이 언제부터 변했나", "drift가 있나", "추세가 있나"를 물을 때

## not_for

- 시간 순서가 없는 데이터 (`eda_analysis`, `statistical_test`)
- 규격 대비 관리 상태 판단 (`spc`)

## typical_previous_skill

- `data_load`

## typical_next_skills

- `spc`

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `resample_series` | 항상 실행 | 시계열을 일·시간 단위로 정리할 때 | 없음 | 간격별 집계 |
| `rolling_stats` | 항상 실행 | 추세를 볼 때 | 없음 | 이동 평균 |
| `detect_change_points` | 항상 실행 | 값이 바뀐 시점을 찾을 때 | 없음 | 변화점 탐지 |
| `decompose_series` | 조건부 실행 | 주기 성분(하루 주기 등)을 따로 봐야 하고, `resample_series` 결과 행 수가 주기의 2배 이상일 때 | `resample_series` | 추세·주기 분해 |

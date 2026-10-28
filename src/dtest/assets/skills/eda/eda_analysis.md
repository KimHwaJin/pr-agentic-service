---
name: eda_analysis
description: 기술 통계, 분포 시각화, 박스플롯, 상관분석으로 데이터를 탐색하는 skill.
---

# EDA Analysis

## capabilities

- 수치형 컬럼 기술 통계 (`compute_statistics`)
- 분포 히스토그램 (`histogram_eda`)
- 이상치 확인용 박스플롯 (`boxplot_eda`)
- 수치형 컬럼 간 상관분석 (`correlation_analysis`)

## limitations

- 인과 관계를 판단하지 않음
- 모델 학습은 수행하지 않음

## when_to_use

- 데이터의 분포, 이상치, 변수 간 관계를 처음 파악할 때

## not_for

- 이미 확정된 지표만 계산하면 되는 경우

## typical_previous_skill

- `data_load`, `dataset_preparation`

## typical_next_skills

- 없음

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `compute_statistics` | 항상 실행 | 입력 데이터가 준비된 경우 | 없음 | 기술 통계 계산 |
| `histogram_eda` | 항상 실행 | 수치형 컬럼이 있는 경우 | 없음 | 분포 확인 |
| `boxplot_eda` | 조건부 실행 | `compute_statistics` 결과에서 IQR 기준 이상치 비율이 1% 이상인 컬럼이 있을 때 | `compute_statistics` | 이상치 시각화 |
| `correlation_analysis` | 조건부 실행 | `compute_statistics` 결과에서 수치형 컬럼이 2개 이상일 때 | `compute_statistics` | 변수 간 상관 확인 |

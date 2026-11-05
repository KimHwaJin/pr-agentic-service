---
name: report_export
description: 분석 결과 표를 파일로 저장하는 skill. 사람이 보는 엑셀(.xlsx, 여러 시트)과, 큰 데이터를 다시 쓰기 좋은 Parquet 파일을 만든다.
---

# Report Export

## capabilities

- 하나 이상의 표를 시트별로 엑셀 파일에 저장, 머리글 굵게·열 너비 맞춤·첫 행 고정 (`export_excel`)
- 큰 DataFrame을 컬럼 타입을 유지한 Parquet 파일로 저장 (`export_parquet`)

## limitations

- 차트를 엑셀 안에 넣지 않음 (그림은 각 분석 tool이 png로 저장)
- 파일은 `artifacts/files` 아래에 저장함

## when_to_use

- 사용자가 "엑셀로 줘", "파일로 저장해줘", "결과 표를 내려받고 싶어"라고 할 때
- 다음 분석에서 다시 읽을 큰 중간 데이터를 남길 때 (Parquet)

## not_for

- 화면에 보여 주기만 하면 될 때

## typical_previous_skill

- `data_quality`, `dataset_preparation`, `yield_analysis`, `statistical_test`, `modeling`

## typical_next_skills

- 없음

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `export_excel` | 항상 실행 | 결과 표를 엑셀로 달라고 할 때 | 없음 | 엑셀 저장 |
| `export_parquet` | 항상 실행 | 큰 데이터를 파일로 남길 때 | 없음 | Parquet 저장 |

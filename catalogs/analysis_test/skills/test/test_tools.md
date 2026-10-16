---
name: test_tools
description: "[시험용] Agent 동작 시험 전용 tool 모음. 사용자가 시험이라고 분명히 요청할 때만 사용한다. 실제 분석에는 쓰지 않는다."
---

# Test Tools

## capabilities

- 지정한 시간 동안 기다리기 (`slow_operation`): 실행 대기·취소 시험
- 인자가 틀리면 분명한 오류를 내는 변환 (`fragile_transform`): 실패 복구 시험

## limitations

- 분석 결과를 만들지 않음

## when_to_use

- 사용자가 "시험", "테스트"로 이 tool을 지목할 때만

## not_for

- 모든 실제 분석

## typical_previous_skill

- `data_load`

## typical_next_skills

- 없음

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `slow_operation` | 항상 실행 | 시험 요청 시 | 없음 | 긴 실행 |
| `fragile_transform` | 항상 실행 | 시험 요청 시 | 없음 | 실패 유발 |

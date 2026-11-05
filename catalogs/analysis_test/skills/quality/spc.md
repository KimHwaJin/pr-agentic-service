---
name: spc
description: 공정 이상 여부를 관리도(개별값, X-bar·S, CUSUM)로 판단하고, 규격 한계가 있으면 공정능력(Cp, Cpk)을 계산하는 통계적 공정관리(SPC) skill.
---

# SPC (Statistical Process Control)

## capabilities

- 개별값 관리도와 관리 한계 이탈 점 (`control_chart`)
- 부분군(웨이퍼, LOT, 날짜)별 평균·산포 관리도 (`xbar_s_chart`)
- 작은 평균 이동(서서히 생기는 drift)을 일찍 잡는 CUSUM 관리도 (`cusum_chart`)
- 규격 하한·상한 대비 공정능력 Cp, Cpk (`process_capability`)

## limitations

- 관리 한계는 데이터 앞부분으로 정함 (기준 기간을 따로 받지 않음)
- 규격 한계는 사용자가 알려 줘야 함

## when_to_use

- "공정이 관리 상태인가", "관리 한계를 벗어났나", "Cpk가 얼마인가"를 물을 때
- 웨이퍼·LOT·날짜 단위로 평균과 산포를 함께 관리할 때
- 작은 drift를 관리도로 확인할 때

## not_for

- 그룹 간 차이의 유의성 (`statistical_test`)
- 변화 시점 탐지 (`time_series`)

## typical_previous_skill

- `data_load`, `time_series`

## typical_next_skills

- 없음

## Tool list

| Tool | 실행 방식 | 실행 조건 | condition_tool | 역할 |
|---|---|---|---|---|
| `control_chart` | 항상 실행 | 관리 상태를 볼 때 | 없음 | 관리도 |
| `xbar_s_chart` | 항상 실행 | 부분군(웨이퍼, LOT, 날짜) 단위로 관리할 때 | 없음 | 평균·산포 관리도 |
| `cusum_chart` | 조건부 실행 | `control_chart`의 out_of_control이 0이지만 작은 drift가 의심될 때 | `control_chart` | 작은 이동 탐지 |
| `process_capability` | 조건부 실행 | 규격 하한(lsl)과 상한(usl)을 알 때 | `control_chart` | 공정능력 계산 |

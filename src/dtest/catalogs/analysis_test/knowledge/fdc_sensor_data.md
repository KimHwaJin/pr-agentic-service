---
name: fdc_sensor_data
description: FDC(설비 이상 감지) 센서 데이터의 의미와 해석 주의점. 센서값 변화, drift, 설비 이상 질문에 사용한다.
---

# FDC 센서 데이터

- FDC(Fault Detection and Classification)는 설비가 공정 중 기록하는 센서값으로 설비 상태를 감시한다.
- `CH_PRESSURE`: 챔버 압력. 서서히 오르거나 내리는 drift는 부품 마모·누설의 신호일 수 있다.
- `CH_TEMP`: 챔버 온도. 하루 주기 변동이 있는 것이 정상이다.
- `RF_POWER`, `GAS_FLOW`: 공급 전력과 가스 유량. 음수는 계측 오류다.

## 해석 시 주의
- 시간당 값은 노이즈가 커서 이동 평균이나 일 단위 집계로 추세를 본다.
- drift는 "언제부터 바뀌었나"(변화점)와 "얼마나 바뀌었나"(변화 전후 평균)를 함께 보고한다.
- 설비(eqp_id)와 챔버(chamber_id)를 섞으면 변화가 희석되므로 나눠서 본다.

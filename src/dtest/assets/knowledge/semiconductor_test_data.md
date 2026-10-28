---
name: semiconductor_test_data
description: 반도체 테스트 데이터(NCE, WT)의 의미, 주요 컬럼, 해석 시 주의점을 설명하는 도메인 지식. NCE/WT 데이터나 수율·불량 관련 질문에 사용한다.
---

# 반도체 테스트 데이터 기초 (mock)

## NCE
- 공정별 마스크 매크로 측정값(`*.max_val`)을 die 좌표(x, y) 단위로 모은 데이터.
- 키: `alias_lot_id`, `wf_id`, `x`, `y`.
- 값이 클수록 해당 공정 마스크 영역의 측정 이상 가능성이 높다.

## WT (Wafer Test)
- die 단위 전기적 테스트 결과. symbol 형식은 die별 bin/symbol 값.
- NCE와 같은 키로 결합해 공정 측정값과 테스트 결과의 관계를 본다.

## 해석 시 주의
- 상관관계는 인과가 아니다. 공정 순서와 물리적 연관을 함께 확인한다.
- wafer edge die는 측정값 분포가 다르므로 좌표 기준으로 분리해 보는 것이 좋다.

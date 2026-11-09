# OPS-11 pr-batch EXECUTOR_API_KEY에 해시를 넣은 설정

| 항목 | 값 |
| --- | --- |
| 서비스구분 | OPS 장애·설정·부하 |
| 우선순위 | P1 |
| 화면 | 일부 화면 + 보조 확인 |
| 필요 권한 | 운영 |
| 단독 수행 | 예 |
| 연동 경로 | I7 |
| 11/01판 ID | - |

## 1. 목적
pr-batch의 EXECUTOR_API_KEY에 키 원문 대신 해시가 들어가면 배치 실행이 SUBMIT_REJECTED로 실패하고 화면·로그에 원인이 보이며, 원복하면 정상인지 확인합니다.

## 2. 사전 조건
- 운영 담당(pr-batch 설정 변경·재배포)
- BAT-02의 배치
- 단독 수행

## 3. 수행 절차
1. 운영 담당이 pr-batch EXECUTOR_API_KEY를 그 키의 SHA-256 해시(64자리 hex)로 바꿔 배포합니다.
2. A가 배치 목록에서 지금 실행을 누르고 실행 이력 창을 엽니다.
3. 실패한 실행의 상태에 마우스를 올려 사유를 봅니다.
4. 운영 담당이 pr-batch 로그에서 Run submission rejected를, executor 로그에서 그 시각의 401을 찾습니다.
5. 키 원문으로 되돌려 배포하고 A가 다시 지금 실행을 누릅니다.

## 4. 예상 결과
- 3: 실행 FAILED, 사유에 SUBMIT_REJECTED와 마지막 연결 오류(401). 다음 대기 실행은 막히지 않음
- 4: pr-batch ERROR "Run submission rejected … status=401", executor에 같은 시각 401 기록
- 5: SUBMITTED → RUNNING → COLLECTING → COMPLETED

## 5. 확인 방법
배치 실행 이력, 로그

## 6. 정리 (원상복구)
5단계(키 원복)

참고: frodo 11/08 배치 401 SUBMIT_REJECTED 재현

---

## 7. 수행 기록
| 환경 | 수행자 | 수행 일시 | 빌드(main / internal/gaia 커밋) | 결과 |
| --- | --- | --- | --- | --- |
| dev | | | | |
| prd | | | | |

## 8. 실제 결과와 증빙
- 단계별 실제 결과 (예상과 다르면 무엇이 달랐는지):
- 증빙 (화면 캡처, 응답 본문, request id, run id, 실행 ID):

## 9. 결함
| 결함번호 | 심각도 | 요약 | 재현 단계 | 예상 | 실제 | 발생 시각 | request id / run id |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

# PREP-03 해시 교환

| 항목 | 값 |
| --- | --- |
| 서비스구분 | PREP 사전 준비 |
| 우선순위 | P0 |
| 화면 | X 화면 밖 · 각 서비스 설정 |
| 필요 권한 | 운영 |
| 단독 수행 | 아니오 |
| 연동 경로 | - |
| 11/01판 ID | G0-3 |

## 1. 목적
각 서비스가 상대의 키를 알아보게 합니다.

## 2. 사전 조건
- PREP-02 완료

## 3. 수행 절차
1. executor `AUTH_CLIENTS`의 `pr-agentic-service`·`pr-batch`·`ops` 해시를 실제 값으로 바꿉니다.
2. pr-batch `AUTH_CLIENTS`의 `pr-agentic-service` 해시를 바꿉니다(`admin: true`, `allowed_tenants: ["*"]` 유지).
3. 키 원문을 우리 `EXECUTOR_API_KEY`·`EXECUTOR_ADMIN_API_KEY`·`BATCH_API_KEY`와 pr-batch `EXECUTOR_API_KEY`에 넣습니다(Deployment env 권장).
4. `EXECUTOR_API_KEY`·`BATCH_API_KEY` 같은 `*_API_KEY`에는 반드시 키 원문을, `AUTH_CLIENTS`의 `key_sha256`에는 해시를 넣습니다(바꿔 넣으면 401, 배치는 `SUBMIT_REJECTED`).

## 4. 예상 결과
- 세 서비스 설정에 0000… 해시가 남아 있지 않음
- `*_API_KEY` 값이 64자리 hex(해시 모양)가 아님. 원문의 SHA-256이 상대 서비스 `key_sha256`과 같음

## 5. 확인 방법
세 서비스 설정 diff

## 6. 정리 (원상복구)
없음

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

# PREP-04 우리 설정 채우기

| 항목 | 값 |
| --- | --- |
| 서비스구분 | PREP 사전 준비 |
| 우선순위 | P0 |
| 화면 | X 화면 밖 · 설정 파일 |
| 필요 권한 | 운영 |
| 단독 수행 | 아니오 |
| 연동 경로 | - |
| 11/01판 ID | G0-4 |

## 1. 목적
우리 서비스의 환경별 설정을 채웁니다.

## 2. 사전 조건
- DB·Redis·SSO·LLM·executor·pr-batch 주소

## 3. 수행 절차
1. `config.<env>.yml`의 `<...>` 자리를 모두 채웁니다(DATABASE_URL, REDIS_URL, PUBLIC_API_ORIGIN, FRONTEND_ORIGIN, CORS_ORIGINS, LLM_API_KEY, MODELS, EXECUTOR_BASE_URL, BATCH_BASE_URL).
2. `SSO_ALLOWED_ORIGINS`, `ADMIN_EMPLOYEE_IDS`(관리자 사번)를 채웁니다.
3. REDIS_URL이 executor가 이벤트를 쓰는 Redis와 같은지 확인합니다. `EXECUTOR_RESULT_ROOT`는 `/mnt/data/dtest`입니다.
4. prd는 `WEB_CONSOLE_ENABLED: true`인지 확인합니다(오픈 때 false).
5. 임베딩을 쓰면 `EMBEDDING_PROVIDER: openai`, `EMBEDDING_SEND_DIMENSIONS: false`로 두고 PowerShell에서 `scripts\check_embedding.ps1`로 확인합니다.

## 4. 예상 결과
- 설정 파일에 `<`가 남은 값 0개
- 임베딩 확인 스크립트 통과(쓰는 경우)

## 5. 확인 방법
설정 파일 검토, 확인 스크립트 출력

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

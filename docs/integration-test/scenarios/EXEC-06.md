# EXEC-06 일반키·마스터키의 조회 범위와 `X-User-Id` 필수

| 항목 | 값 |
| --- | --- |
| 서비스구분 | EXEC executor 연동 |
| 우선순위 | P1 |
| 화면 | O 우리 화면만 · API 호출 시험 화면 |
| 필요 권한 | 관리자 |
| 단독 수행 | 아니오 |
| 연동 경로 | I2 I3 |
| 11/01판 ID | C6 |

## 1. 목적
게이트웨이는 key 종류와 관계없이 `X-User-Id`를 요구하고(조회·쓰기 모두), 조회 범위는 key 종류가 정하는지 확인합니다. 일반키는 `X-User-Id` 사용자 것만, 마스터키는 tenant 전체(쿼리 `user_id`로 거르기)입니다.

## 2. 사전 조건
- 우리 tenant 일반키, 우리 tenant 마스터키 (PREP-09)
- 실행이 있는 사용자 두 명 (A: 내 사번, B: 다른 사번)

## 3. 수행 절차
1. 관리자로 **시스템 > API 호출 시험** 탭을 엽니다.
2. 시나리오 **EXEC-06**을 고르고(X-User-Id 꺼짐) 일반키로 보냅니다. 마스터키로도 보냅니다.
3. 방식을 POST, 경로를 `/api/v1/executor/executions`로 바꾸고 EXEC-02 본문을 붙여 보냅니다(X-User-Id 꺼짐).
4. 일반키, X-User-Id=A로 `GET /api/v1/executor/executions?limit=20`을 보내고, 이어서 `?user_id=B`를 붙여 보냅니다.
5. 마스터키, X-User-Id=A로 `GET /api/v1/executor/executions?limit=20`을 보내고, 이어서 `?user_id=B`를 붙여 보냅니다.
6. 마스터키, X-User-Id=A로 `GET /api/v1/executor/executions?limit=20&user_id=A%20B!`를 보냅니다.

## 4. 예상 결과
- 2: 두 key 모두 400 `INVALID_IDENTITY`
- 3: 400 `INVALID_IDENTITY`
- 4: 처음은 200, A의 실행만. `user_id=B`는 403 `FORBIDDEN`
- 5: 처음은 200, 여러 사용자의 실행. `user_id=B`는 200, B의 실행만
- 6: 400 `INVALID_IDENTITY` (details에 `query.user_id`)

## 5. 확인 방법
API 호출 시험 결과

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

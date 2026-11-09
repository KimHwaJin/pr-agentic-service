# BAT-11 일반키·마스터키의 배치 조회 범위와 X-User-Id 필수

| 항목 | 값 |
| --- | --- |
| 서비스구분 | BAT 배치 |
| 우선순위 | P1 |
| 화면 | O 우리 화면만 |
| 필요 권한 | 관리자 |
| 단독 수행 | 아니오 |
| 연동 경로 | I2 I6 |
| 11/01판 ID | - |

## 1. 목적
배치 게이트웨이도 key 종류와 관계없이 X-User-Id를 요구하고, 조회는 일반키면 그 사용자 것만, 마스터키면 tenant 전체(쿼리 user_id로 거르기), 쓰기는 X-User-Id 사용자로 되는지 확인합니다.

## 2. 사전 조건
- 우리 tenant 일반키·마스터키(PREP-09)
- 배치가 있는 A와 B(각자 BAT-02)
- A의 노트북 artifact ID(BAT-01)
- pr-batch 8dc99aa 이후(PREP-01)

## 3. 수행 절차
1. 관리자로 시스템 > API 호출 시험 탭을 엽니다. 직접 입력, GET /api/v1/batch/batches?limit=20을 우리 tenant 일반키, X-User-Id=A로 보냅니다.
2. 경로 끝에 &user_id=<B의 사번>을 붙여 보냅니다.
3. 키를 마스터키로 바꾸고(X-User-Id=A) GET /api/v1/batch/batches?limit=20을 보냅니다.
4. 경로 끝에 &user_id=<B의 사번>을 붙여 보냅니다.
5. X-User-Id 보내기를 끄고 마스터키로 3을 다시 보냅니다.
6. 마스터키, X-User-Id=A로 방식 POST, 경로 /api/v1/batch/scripts/from-notebook, 본문 {"artifact_id":"<A의 노트북 artifact ID>"}를 보냅니다. 이어서 일반키, X-User-Id=A로 GET /api/v1/batch/scripts를 보냅니다.

## 4. 예상 결과
- 1: 200, 모든 항목의 user_id가 A
- 2: 403 FORBIDDEN
- 3: 200, A와 B의 배치가 함께 나옴
- 4: 200, B의 배치만
- 5: 400 INVALID_IDENTITY
- 6: 스크립트가 A 소유(user_id A)로 만들어지고, 일반키·X-User-Id=A로 본 스크립트 목록에 보임

## 5. 확인 방법
API 호출 시험 결과

## 6. 정리 (원상복구)
6에서 만든 스크립트 삭제

참고: pr-batch의 tenant 전체 조회·user_id 필터(795cbd3) 필요

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

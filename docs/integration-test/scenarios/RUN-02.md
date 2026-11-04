# RUN-02 같은 흐름을 키 호출자로 (Swagger 가이드 1절)

| 항목 | 값 |
| --- | --- |
| 서비스구분 | RUN 세션·run 실행 |
| 우선순위 | P0 |
| 화면 | O 우리 화면만 · API 호출 시험 화면 |
| 필요 권한 | 관리자 |
| 단독 수행 | 아니오 |
| 연동 경로 | I2 I3 I5 |
| 11/01판 ID | B2 |

## 1. 목적
키 호출자(상위 에이전트)가 같은 분석 흐름을 API로 끝까지 돌릴 수 있는지 확인합니다.

## 2. 사전 조건
- 우리 tenant 키(PREP-09)
- 일반 A 사번과 A의 기본 프로젝트 ID(요청·응답 창의 `/users/me` 응답 `default_project_id`)

## 3. 수행 절차
1. 관리자로 **시스템 > API 호출 시험** 탭을 엽니다.
2. 시나리오 **RUN-02**를 고르고 키, A의 사번, 경로의 `<project_id>`를 넣어 보냅니다.
3. 응답의 세션 ID로 경로를 `GET /api/v1/sessions/<session_id>/events`로 바꿔 몇 번 보냅니다.
4. plan_approval이 오면 시나리오 **RUN-10** 본문 형식으로 `POST /api/v1/sessions/<session_id>/runs`에 `{"command":{"resume":{"interrupt_id":"<받은 id>","value":{"action":"approve"}}}}`를 보냅니다.
5. 끝날 때까지 3을 반복합니다. 이후 A로 로그인해 그 세션을 엽니다.

## 4. 예상 결과
- 2: 201, 세션 ID와 run ID
- 4: 202 `resumed: true`
- 5: run `succeeded`, `execution_completed`·`artifact` 이벤트. A 화면에 같은 대화와 첨부가 보임. 실행 이력의 사용자가 A의 사번

## 5. 확인 방법
API 호출 시험 결과, A 화면, 실행 이력

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

# executor 조회 API 중계 (BFF) 검토

상태: 구현됨 (`api_service/routers/executor.py`). 근거는 executor 레포의 `src/executor_service/interfaces/http/` 라우터입니다.

## 1. 원칙

- 프론트는 executor를 직접 부르지 않고 우리 API만 부릅니다. 우리는 **조회(GET)만** 그대로 건네고(바이패스), 응답 본문은 executor 것을 가공하지 않고 돌려줍니다.
- 실행을 만들거나 바꾸는 API(submit, append, cancel, retry, finalize, artifact 생성)는 중계하지 않습니다. 이것들은 지금처럼 에이전트만 씁니다.
- **권한은 우리가 확인합니다.** executor에는 사용자 인증이 없어서, 그대로 건네면 다른 사람의 실행도 보입니다. 실행의 `context`(`user_id`, `project_id`, `session_id`)로 소유를 확인합니다.

## 2. 중계할 API (제안)

경로는 executor와 같은 모양으로 우리 쪽 `/api/v1/executor/...` 아래에 둡니다. 예: executor `GET /api/v1/executions/{id}/steps` → 우리 `GET /api/v1/executor/executions/{id}/steps`.

### 2.1 필수: 화면에서 바로 쓰는 것

| 우리 경로 (`/api/v1/executor` 아래) | executor 설명 | 용도 |
| --- | --- | --- |
| `GET /executions?project_id&session_id&status&cursor&limit` | List execution history | 프로젝트·세션의 실행 목록. `user_id`는 우리가 로그인 사용자로 강제 |
| `GET /executions/{id}` | Get current execution state | 실행 상태, 진행 중인지, 커널 살아 있는지 |
| `GET /executions/{id}/steps` | List current execution Steps | 실행 단계 목록과 단계별 상태, lineage(skill, tool, 입력값) |
| `GET /executions/{id}/steps/{step_id}` | Get one current execution Step | 단계 하나의 상세(시간, 오류, 결과 위치) |
| `GET /executions/{id}/result` | Get the consolidated execution result | 실행 전체 결과 요약 |
| `GET /executions/{id}/events?after_sequence&cursor&limit` | List the durable Execution event timeline | 진행 타임라인(시작, 단계 완료·실패 등). 지난 실행 다시 보기 |
| `GET /executions/{id}/artifacts` | List execution Artifacts | 그 실행의 리포트·노트북 목록 (개별 조회·내려받기는 지금의 `/artifacts/{id}`, `/content`가 이미 있음) |
| `GET /executions/{id}/notebook` | Read Runtime-owned execution notebook cells | 노트북 셀(코드·출력) JSON. 자체 화면에서 노트북을 그릴 때 |

### 2.2 선택: 실행을 묶음 단위로 볼 때

| 경로 | executor 설명 | 용도 |
| --- | --- | --- |
| `GET /executions/{id}/operations` | List Agent-submitted execution Operations | MULTI 실행의 operation(= 에이전트가 한 번에 보낸 묶음) 목록 |
| `GET /executions/{id}/operations/{op_id}` | Get one execution Operation detail | operation 상세 |
| `GET /executions/{id}/operations/{op_id}/result` | Get one Operation and all of its Step results | operation 결과 + 단계 결과 한 번에 |
| `GET /executions/{id}/operations/{op_id}/steps` | List current Step results for one Operation | operation의 단계 결과 |
| `GET /executions/{id}/notebook/cells/{index}` | Read one notebook cell | 셀 하나만 |

### 2.3 운영·디버깅용 (관리자만, 선택)

| 경로 | executor 설명 | 비고 |
| --- | --- | --- |
| `GET /executions/{id}/diagnostics` | List failure observations | 실패 원인 분석 |
| `GET /executions/{id}/attempts`, `/attempts/{id}`, `/attempts/{id}/steps` | 재시도 이력(Attempt) | 장애·재시도 추적 |
| `GET /runtime-targets`, `/runtime-pools`, `/maintenance` | 런타임 상태, 점검 상태 | 운영 대시보드용. executor 관리 기능이라 일반 사용자에게는 열지 않음 |

### 2.4 중계하지 않음

- `POST /executions`, `/operations`, `/cancel`, `/retry`, `/finalize`, `POST /executions/{id}/artifacts`: 실행·변경. 취소는 우리 `POST /runs/{id}/cancel`로 합니다.
- `/maintenance/*`의 POST, `/runtime-targets/*`의 POST: executor 운영 조작.

## 3. 권한 확인 방법

| 요청 | 확인 |
| --- | --- |
| 목록 `GET /executions` | `user_id`를 로그인 사용자의 사번으로 강제. `project_id`나 `session_id`를 주면 그 프로젝트·세션의 멤버인지 먼저 확인 |
| 실행 하나 아래의 모든 경로 | 실행의 `context.project_id`가 사용자가 속한 프로젝트인지 확인 (지금은 프로젝트 소유자 = 실행 요청자라 `user_id`와 같지만, 프로젝트 공유를 대비해 프로젝트 멤버십 기준) |
| 관리자 경로 | `role=admin`만 |

- 실행 하나마다 소유 확인을 위해 executor를 한 번 더 부르지 않도록, 우리 DB(`code_sources`의 `execution_id → session_id`)를 먼저 보고, 없을 때(배치가 만든 실행 등)만 `GET /executions/{id}`로 `context`를 읽습니다. 결과는 짧게 캐시합니다(실행의 소유는 바뀌지 않음).
- pr-batch가 만든 실행도 `context.user_id`가 요청자 사번이면 같은 규칙으로 보입니다(pr-batch가 context를 어떻게 채우는지 확인 필요).

## 4. 중계 방식

- 허용 목록에 있는 GET만 받는 라우터 하나: `/api/v1/executor/{path:path}`에서 경로를 허용 목록 패턴과 맞춰 보고, 권한 확인 후 executor에 그대로 요청합니다. 쿼리 파라미터도 그대로 넘기되, 목록의 `user_id`만 덮어씁니다.
- 응답은 상태 코드와 본문을 그대로 돌려줍니다. 단, executor 연결 실패는 502 `{detail, code: "executor_unavailable"}`, executor 404는 우리 형식의 404로 바꿉니다. 노트북·결과처럼 큰 응답은 스트리밍으로 넘깁니다.
- 지금 배치 중계(`/api/v1/batch/{path}`)와 같은 구조라 코드가 비슷하게 갑니다.

## 5. 이미 있는 것과의 관계

- `/api/v1/artifacts/{id}`, `/content`, `/view/artifacts/{id}`: 그대로 둡니다(이미 소유 확인 포함).
- `/api/v1/sessions/{id}/outputs?execution_id&path`: 단계 출력 파일(이미지). executor API가 아니라 공유 볼륨을 읽는 것이라 그대로 둡니다.
- run에서 실행으로 가는 연결: 실행 목록을 `session_id`로 거르면 세션의 실행을 볼 수 있습니다. run 단위로 보려면 `code_sources`가 있지만, 앞서 run 기준 API는 두지 않기로 했습니다.

## 6. 결정 사항

- 범위: 2.1(필수 8개) + 2.3(관리자용: diagnostics, attempts, runtime-targets, runtime-pools, maintenance 조회) + **런타임 등록 `POST /runtime-targets`(관리자)**. 2.2(operation 단위)는 넣지 않음.
- 경로: `/api/v1/executor/...`에 executor와 같은 모양.
- 응답: executor 본문 그대로. 런타임 등록의 `actor`만 서버가 요청한 관리자(`USER`, 사번)로 덮어씀.
- 런타임 조작(probe, drain, activate, disable, purge)과 executor 점검 조작(maintenance drain, activate, runs 생성·조회)도 관리자 전용으로 열었음.

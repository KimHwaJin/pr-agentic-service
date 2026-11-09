# executor 게이트웨이: 코딩 에이전트용 가이드

이 문서는 pr-agentic-service의 **executor 게이트웨이**로 Python 코드를 실행하는 클라이언트를 만들 때 씁니다. 클라이언트를 만드는 데 이 파일 하나면 됩니다. 규칙을 먼저 읽고, 필드 계약은 끝의 TypeScript 타입(과 `openapi/executor-gateway.openapi.json`)을 그대로 따릅니다.

> 영문판 [executor-for-agents.md](executor-for-agents.md)와 내용이 같습니다. 코드, 경로, 필드 이름, 오류 코드는 번역하지 않았습니다.

- Base path: `{BASE_URL}/api/v1/executor`. `BASE_URL`은 쿠버네티스에 배포된 서비스 주소입니다. 클러스터 밖에서는 환경별 공개 주소 `https://<api-host>`, 클러스터 안에서는 `http://pr-agentic-service.<namespace>.svc.cluster.local`입니다. 설정(`AGENTIC_BASE_URL`)에서 읽고, 코드에 넣지 않습니다.
- 아래 경로는 모두 이 base path 기준입니다. 여기 없는 경로는 `404 NOT_FOUND`입니다.
- 게이트웨이는 executor로 중계합니다. 요청 본문과 성공 응답 본문은 executor 것을 그대로 씁니다. 게이트웨이는 key와 사용자를 확인하고, 신원 헤더를 직접 만들고, 조회 범위를 정합니다.

## 1. 규칙

### MUST (반드시)

1. 모든 요청에 `X-Api-Key: <key>`를 보냅니다. key는 설정이나 환경 변수(예: `AGENTIC_API_KEY`)에서 읽습니다. 코드에 넣거나 로그에 남기지 않습니다. 형식은 stg·prd가 `pas_live_…`, dev가 `pas_dev_…`입니다.
2. 조회를 포함한 **모든** 요청에 `X-User-Id: <사번>`을 보냅니다. 호출 서비스가 직접 인증한 사용자를 소문자로, `^[a-z0-9][a-z0-9._-]{0,63}$` 형식으로 넣습니다. 없거나 형식이 틀리면 `400 INVALID_IDENTITY`입니다.
3. 모든 POST에 `Content-Type: application/json`을 보냅니다.
4. 논리적인 쓰기 하나마다 `idempotency_key`(UUID 문자열, 1~255자)를 **첫 시도 전에** 한 번 만듭니다. 헤더가 아니라 JSON 본문에 넣습니다. 그 쓰기를 재시도할 때는 같은 key와 **같은 본문**을 씁니다.
5. 모든 쓰기(제출, operation 추가, finalize, cancel, retry)는 비동기입니다. `202`는 접수되어 큐에 들어갔다는 뜻입니다. 결과는 폴링으로 확인합니다(4장).
6. 분기는 `error.code`로 합니다. `error.message`나 HTTP 상태만 보고 분기하지 않습니다.
7. 코드 source는 `INLINE`을 씁니다: `{"type": "INLINE", "content": "<python>"}`.
8. 셀 출력 원문은 노트북 경로(`/notebook?view=FULL`, `/notebook/cells/{n}`)로만 읽습니다. 파일은 `/artifacts/{artifact_id}/content`로만 받습니다.
9. MULTI 명령에는 직전에 읽은 `state.version`을 `expected_version`으로 보냅니다.
10. `next_cursor`는 그대로 `cursor`로 다시 넘깁니다. `next_cursor`가 `null`이면 멈춥니다.

### MUST NOT (하지 않음)

1. 요청 본문에 `tenant_id`, `context`, `actor`, `created_by` 같은 모르는 필드를 넣지 않습니다. 요청 스키마는 모르는 필드를 `422 REQUEST_VALIDATION_ERROR`로 거절합니다.
2. `X-Tenant-Id`를 보내지 않습니다. key가 tenant를 정하므로 무시됩니다.
3. executor를 직접 부르거나 executor key를 쓰지 않습니다. 이 게이트웨이만 씁니다.
4. `result_ref.relative_path`를 열지 않습니다. 호출자가 읽을 수 없는 내부 저장 경로입니다.
5. `Range`(전달되지 않으며 파일은 항상 `200`으로 통째로 옵니다), `Idempotency-Key`, `If-Match`를 보내지 않습니다. 셋 다 전달되지 않습니다.
6. `PATH` 코드 source를 쓰지 않습니다. 외부 호출자는 executor 입력 저장소에 쓸 수 없습니다.
7. 2초보다 자주 폴링하지 않고, 4xx 오류를 그대로 재시도하지 않습니다(5장의 경우는 예외).
8. 같은 idempotency key를 다른 본문에 다시 쓰지 않습니다. `409 IDEMPOTENCY_CONFLICT`가 납니다.

## 2. 헤더

| 헤더 | 언제 | 값 |
| --- | --- | --- |
| `X-Api-Key` | 항상 | 발급받은 key |
| `X-User-Id` | 항상 | 호출한 사용자(사번). 쓰기는 이 사용자로 기록됩니다(`created_by`) |
| `X-Project-Id` | 선택 | `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$`, `unscoped`는 안 됨. `POST /executions`에서만 저장됩니다(`context.project_id`). 다른 경로에서는 형식만 보고 무시합니다 |
| `X-Session-Id` | 선택 | 형식은 같음. `X-Project-Id`가 함께 있어야 합니다(없으면 `400`). 제출할 때만 저장됩니다 |
| `Content-Type` | POST | `application/json` |

쓸 수 있는 응답 헤더: `Content-Type`, `ETag`(아티팩트 내용: SHA-256), `Location`(제출), `Content-Disposition`(아티팩트 파일 이름), `X-Request-ID`(문제를 알릴 때 함께 전달).

`Location`은 executor 기준 경로(`/api/v1/executions/{id}`)입니다. 따라가기 전에 `/api/v1/`을 `/api/v1/executor/`로 바꾸거나, 그냥 `execution_id`로 URL을 만듭니다.

key가 이 서비스 자신의 tenant(`dtest-agent-service`) 것이면 `X-User-Id`는 이 서비스의 활성 사용자여야 합니다(아니면 `403 FORBIDDEN`). `X-Project-Id`는 그 사용자가 멤버인 프로젝트, `X-Session-Id`는 그 프로젝트의 세션이어야 합니다(아니면 `404`). 다른 tenant의 key는 형식만 확인합니다.

## 3. 조회 범위: 일반키와 마스터키

key는 `standard`(일반키, 기본값) 또는 `master`(마스터키)입니다. 종류는 **조회 결과만** 바꿉니다. 쓰기는 둘 다 같습니다.

| | 일반키 | 마스터키 |
| --- | --- | --- |
| `GET /executions` | `X-User-Id` 사용자의 실행만 | tenant 전체 |
| 쿼리 `user_id` | 선택. 보내면 `X-User-Id`와 같아야 하고, 다르면 `403 FORBIDDEN` | 그 사용자 것으로 거릅니다 |
| 상세 경로 (`/executions/{id}/…`, `/artifacts/{id}…`) | 남의 실행 → `404` | tenant 안의 모든 실행 |
| 쓰기 | `X-User-Id`로 | `X-User-Id`로 |

- 쿼리 `user_id` 형식이 틀리면 `400 INVALID_IDENTITY`입니다.
- 쿼리 `tenant_id`는 언제나 버려집니다.
- `404`로는 "없음"과 "내 것이 아님·다른 tenant 것"을 구분할 수 없습니다.
- 클라이언트는 자기 key 종류를 몰라도 됩니다. 일반키로 `user_id` 필터를 쓰지 않는 것만 지키면 됩니다.

## 4. 흐름

### 4.1 SINGLE: 한 번 실행

```
POST /executions                        → 202 {execution_id, state:{status:"QUEUED", version}}
GET  /executions/{id}                   → state.status가 종료 상태가 될 때까지 2~5초마다
GET  /executions/{id}/result            → step별 상태, error_message, output_summary
GET  /executions/{id}/notebook?view=FULL → 코드와 출력 원문 (필요할 때만)
```

제출 본문 (최소):

```json
{
  "idempotency_key": "6f1c9a52-3d1e-4c55-9a43-1f0e2a7b9c10",
  "lifecycle": {"operation_mode": "SINGLE"},
  "trigger": {"type": "INTERACTIVE"},
  "runtime": {"type": "JUPYTER", "profile": "default"},
  "operation": {
    "operation_timeout_seconds": 600,
    "spec": {
      "schema_version": "1.0",
      "steps": [
        {"sequence": 0,
         "payload": {"type": "PYTHON_EXECUTE",
                     "source": {"type": "INLINE", "content": "import pandas as pd\nprint(pd.__version__)"}},
         "step_timeout_seconds": 300}
      ]
    },
    "metadata": {}
  },
  "metadata": {"caller_task_id": "t-100"}
}
```

필드 규칙:

- `trigger.type`: `INTERACTIVE`(온라인) 또는 `BATCH`. 커널 풀을 고릅니다. MULTI는 `INTERACTIVE`여야 합니다.
- `runtime.profile`: 커널 환경. 기본값은 `default`입니다. 쓸 수 있는 값은 `GET /api/v1/batch/runtimes`(같은 key)의 `profile`입니다.
- `steps`: operation당 1~100개, 실행당 1000개. `sequence`는 0부터 시작하고 **실행 전체에서** 이어집니다.
- `step_timeout_seconds`, `operation_timeout_seconds`는 1 이상이고 선택입니다(없으면 executor 최대 실행 시간까지 제한 없음).
- `lifecycle.operation_wait_timeout_seconds`는 MULTI 전용(30 이상)입니다. SINGLE에 보내면 422입니다.
- `metadata`: `^[a-z][a-z0-9_]{0,63}$` 형식 key 최대 32개, JSON 4096바이트 이하. 비밀 값은 넣지 않습니다.
- step의 `lineage`(`{skill_name?, tool_name?, input_parameters?}`)는 선택이고 받은 그대로 저장됩니다.

### 4.2 MULTI: 결과를 보고 이어서 실행

operation 사이에 커널이 살아 있으므로 변수가 유지됩니다.

```
POST /executions  lifecycle = {"operation_mode":"MULTI","operation_wait_timeout_seconds":600}, trigger.type = INTERACTIVE
GET  /executions/{id}            status == WAITING_FOR_OPERATION 까지; state.version을 기억
GET  /executions/{id}/operations/{operation_id}/result   (또는 /result, /notebook)
POST /executions/{id}/operations {idempotency_key, expected_version, spec:{schema_version:"1.0", steps:[{sequence: 다음 번호…}]}}
     … 끝날 때까지 반복 …
POST /executions/{id}/finalize   {idempotency_key, expected_version}
GET  /executions/{id}            SUCCEEDED / FAILED 까지
```

- operation 추가 본문은 `spec`, `operation_timeout_seconds`, `metadata`를 최상위에 둡니다. `lifecycle`, `trigger`, `runtime`, `operation`은 다시 보내지 **않습니다**.
- 다음 step의 `sequence`는 마지막 번호에서 이어집니다. 예를 들어 첫 operation이 0과 1을 썼으면 다음은 2부터입니다.
- `202` 응답에 새 `state.version`과 `operation.operation_id`가 옵니다.
- `expected_version`이 낡았으면 `409 EXECUTION_VERSION_CONFLICT`입니다. 상태를 다시 읽고 판단합니다. 버전 확인은 step 검증보다 먼저 합니다.
- `operation_wait_timeout_seconds` 안에 operation을 추가하거나 finalize해야 합니다. 그러지 않으면 실행이 저절로 끝납니다(`state.finalized_by = "WAIT_TIMEOUT"`). 조회는 기한(`deadlines.operation_wait_expires_at`)을 늘리지 않습니다.
- `finalize`는 마지막 operation이 **성공한** 뒤의 `WAITING_FOR_OPERATION`에서만 됩니다. 아니면 `409 INVALID_STATE_TRANSITION`입니다. operation이 실패했으면 고친 operation을 추가하거나 취소합니다.
- MULTI에서 추가 operation의 idempotency key 범위는 그 실행이고, 제출 key의 범위는 tenant입니다.

### 4.3 취소와 재시도

- `POST /executions/{id}/cancel` `{"idempotency_key", "reason"?}`(reason 2000자 이하) → `CANCEL_REQUESTED`, 그 뒤 `CANCELLED`(또는 `FAILED`)까지 폴링합니다.
  - 끝난 실행은 `409`입니다. 이미 `CANCEL_REQUESTED`인 실행은 현재 상태를 돌려줍니다.
  - 취소되면 실행 중인 step은 `CANCELLED`, 시작 전 step은 `SKIPPED`가 됩니다.
- `POST /executions/{id}/retry` `{"idempotency_key"}`: `FAILED`이고 `retry.strategy`가 `NOT_RETRYABLE`이 아닌 SINGLE 실행에만 됩니다. **같은** `execution_id`로 `retry.from_sequence`부터 다시 돌립니다. 아니면 `409`입니다. MULTI는 고친 operation을 추가합니다.

### 4.4 폴링과 이벤트

- 게이트웨이는 executor의 Redis 이벤트 스트림을 중계하지 않습니다.
- `GET /executions/{id}`를 2~5초마다 폴링합니다. 종료 상태는 `SUCCEEDED`, `FAILED`, `CANCELLED`입니다. MULTI는 `WAITING_FOR_OPERATION`에서도 일이 멈춥니다.
- 또는 새 이벤트를 읽습니다: `GET /executions/{id}/events?after_sequence=<마지막으로 본 event_sequence>&limit=200`(limit 1~500).
  - 결과는 `event_sequence` 오름차순입니다.
  - `next_cursor`가 있으면 `cursor=<next_cursor>`로(그리고 `after_sequence` 없이) 다시 부릅니다.
  - 이벤트는 깨어나는 신호로만 쓰고, 판단은 상태 조회로 합니다.

| `event_type` | 뜻 |
| --- | --- |
| `execution.started` | 커널 준비, 첫 실행 시작. 한 번만 오고 재시도 때는 다시 오지 않습니다. `payload.runtime = {provider, profile, target_id, kernel_id}`. 런타임 준비 전에 실패하면 오지 않을 수 있습니다 |
| `execution.operation_started` | operation 시작 |
| `execution.step_started`, `execution.step_completed` | step 시도 시작·종료 |
| `execution.step_handover_started`, `execution.step_handover_completed` | 다른 executor 워커가 실행 중인 step을 넘겨받음 |
| `execution.operation_completed` | operation 종료. `payload.status`; `payload.execution_status`(MULTI: `WAITING_FOR_OPERATION`) |
| `execution.completed` | 실행 종료: **성공, 실패, 취소 모두**. `payload.status`를 읽습니다 |

모르는 `event_type`은 무시합니다. 새 종류가 추가될 수 있습니다.

`kernel_id`(실행·attempt의 `runtime`과 started 이벤트에 있음)는 Jupyter 커널 id입니다. `X-Session-Id`와는 관계가 없고, 커널이 생기기 전과 정리된 뒤에는 `null`입니다.

### 4.5 결과 읽기 (가벼운 것부터)

1. `GET /executions/{id}`: `state.status`와 `failure`(`{type, message}` 또는 null).
2. `GET /executions/{id}/result`: 모든 operation과 step의 `result.status`, `error_message`, `output_summary`(`output_count`, `has_image`, `has_error`, `mime_types`, …)와 아티팩트 요약. 작고 페이지가 없습니다.
3. 출력 원문:
   - `GET /executions/{id}/notebook?view=SUMMARY&start_index=0&limit=20`으로 셀을 찾습니다.
   - 그다음 전체 코드와 `outputs[]`는 `view=FULL`로, 셀 하나 전체는 `GET /executions/{id}/notebook/cells/{index}`로 받습니다.
   - 출력은 Jupyter 형식(`stream`, `execute_result`, `display_data`, `error`)입니다. 이미지는 `data["image/png"]`에 base64로 있습니다.
   - 셀 index는 노트북 순서이고 step `sequence`와 다를 수 있습니다.
   - `page = {start_index, limit, total_count, has_more}`, `limit`은 1~200입니다.
4. 파일:
   - `GET /executions/{id}/artifacts`: 아티팩트 목록(limit 1~1000).
   - `GET /artifacts/{artifact_id}`: 아티팩트 하나의 메타데이터.
   - `GET /artifacts/{artifact_id}/content`: 내용 바이트. `Content-Type`은 파일 형식, `Content-Disposition`에 파일 이름, `ETag`는 SHA-256입니다.
   - 실행 노트북(`type: NOTEBOOK`)은 처음부터 있고, 실행 중에도 받을 수 있습니다.
   - `status: AVAILABLE`이 분석 성공을 뜻하지는 않습니다.
5. 직접 만든 텍스트(예: 리포트)를 **SUCCEEDED** 실행의 아티팩트로 저장:
   - `POST /executions/{id}/artifacts`에 `{"idempotency_key", "type": "REPORT", "source": {"type": "INLINE", "content": "<utf-8 텍스트>"}, "name"?, "description"?, "media_type"?, "append_to_notebook"?: true, "metadata"?}`를 보냅니다. `201`이 옵니다.
   - `type`은 `REPORT`, `NOTEBOOK`, `PLOT`, `METRIC`, `LOG`, `OTHER` 중 하나입니다.

노트북이 최신인지는 `GET /executions/{id}` → `workspace.notebook_projection.status`(`NOT_STARTED`, `PENDING`, `SUCCEEDED`, `FAILED`)로 봅니다.

## 5. 오류와 재시도

게이트웨이와 executor의 모든 오류는 이 모양입니다.

```json
{"error": {"code": "EXECUTION_VERSION_CONFLICT", "message": "human text, may change",
           "details": [{"location": ["body", "expected_version"], "type": "version_conflict",
                        "message": "…", "context": {"expected": 3, "current": 4}}],
           "context": {}}}
```

`details`는 항상 있습니다(비었으면 `[]`). `details[].location[0]`은 `body`, `header`, `query`, `path` 중 하나입니다. `details[].type`은 바뀌지 않는 snake_case 사유이고, `details[].context`에 한도와 실제 값이 있습니다.

| HTTP | `error.code` | 내는 곳 | 원인 | 클라이언트가 할 일 |
| --- | --- | --- | --- | --- |
| 400 | `INVALID_IDENTITY` | 게이트웨이 / executor | `X-User-Id` 없음·형식 오류, `X-Project-Id`·`X-Session-Id` 형식 오류, 프로젝트 없는 세션, 쿼리 `user_id` 형식 오류 | 요청을 고침. 재시도 안 함 |
| 401 | `LOGIN_REQUIRED` | 게이트웨이 | `X-Api-Key` 없음 | 설정을 고침 |
| 401 | `INVALID_API_KEY` | 게이트웨이 | 모르거나 폐기된 key | 멈추고 알림 |
| 403 | `FORBIDDEN` | 게이트웨이 | 모르거나 비활성인 사용자(우리 tenant), 일반키가 남의 `user_id`로 조회 | 재시도 안 함 |
| 404 | `NOT_FOUND` | 게이트웨이 | 목록에 없는 경로, 멤버가 아닌 프로젝트, 남의 세션 | 경로를 고침 |
| 404 | `EXECUTION_NOT_FOUND`, `ARTIFACT_NOT_FOUND`, 그 밖의 `*_NOT_FOUND` | executor | 없음, 다른 tenant, (일반키) 다른 사용자 | id 확인 |
| 409 | `EXECUTION_VERSION_CONFLICT` | executor | 낡은 `expected_version` | 상태를 GET, 판단, 새 버전과 **새** idempotency key로 보냄 |
| 409 | `INVALID_STATE_TRANSITION` | executor | 이 상태에서 안 됨(끝난 실행 취소, 대기 중이 아닐 때 추가, 실패한 operation 뒤 finalize, 재시도 불가) | 상태를 GET, 판단 |
| 409 | `IDEMPOTENCY_CONFLICT` | executor | 같은 key, 다른 본문 | 버그: 새 작업은 새 key |
| 413 | `TOO_LARGE` | 게이트웨이 | 본문 > 32 MB | 줄임 |
| 413 | `REQUEST_BODY_TOO_LARGE` | executor | 본문 > 30 MB | 줄임 |
| 422 | `REQUEST_VALIDATION_ERROR` | executor | 누락, 타입 오류, 길이·형식, 모르는 필드 | `details`대로 고침 |
| 422 | `INVALID_EXECUTION_SPEC` | executor | 규칙 위반. `details[].type`은 아래 표 | `details[].context`대로 고침 |
| 500 | `INTERNAL_ERROR` | executor | 버그 | `X-Request-ID`와 함께 알림 |
| 502 | `EXECUTOR_UNAVAILABLE` | 게이트웨이 | executor에 닿지 않음 | 간격을 늘려 재시도, 같은 key와 본문 |
| 503 | `DATABASE_UNAVAILABLE` | executor | 일시적인 DB 끊김 | 간격을 늘려 재시도, 같은 key와 본문 |
| 504 | `EXECUTOR_TIMEOUT` | 게이트웨이 | executor가 30초 넘게 걸림 | 간격을 늘려 재시도, 같은 key와 본문 |

`INVALID_EXECUTION_SPEC`의 `details[].type` 값:

| type | context |
| --- | --- |
| `too_many_steps` | `limit`, `actual` |
| `execution_step_limit_exceeded` | `limit`, `existing`, `requested`, `actual` |
| `inline_source_too_large` | `limit_bytes`, `actual_bytes`, `sequence` |
| `source_blank` | `sequence` |
| `steps_empty` | (없음) |
| `sequence_not_contiguous`, `first_sequence_not_zero` | `expected`, `actual` |
| `unsupported_schema_version` | `expected`, `actual` |
| `exceeds_max_runtime` | `limit_seconds`, `actual_seconds` |
| `not_allowed_for_single`, `required_for_multi` | `actual` |
| `multi_requires_interactive` | `expected`, `actual` |
| `session_without_project`, `reserved_value` | `actual` |

재시도 규칙:

- 네트워크 오류, 타임아웃, `502`, `503`, `504`에서만 지수 백오프(1초, 2초, 4초, … 최대 30초, 최대 5번)로 재시도합니다.
- **같은 idempotency key와 같은 본문**을 씁니다. 처음 결과가 그대로 돌아옵니다.
- 그 밖의 4xx는 그대로 재시도하지 않습니다.

## 6. 엔드포인트

모든 경로는 `/api/v1/executor` 아래에 있습니다.

| # | 메서드 | 경로 | 본문 | 성공 |
| --- | --- | --- | --- | --- |
| 1 | GET | `/executions?user_id=&project_id=&session_id=&trigger_type=&status=&cursor=&limit=` (limit 1~200, 기본 100) | – | 200 `ExecutionPageResponse` |
| 2 | POST | `/executions` | `ExecutionSubmitRequest` | 202 `ExecutionCommandResponse` + `Location` |
| 3 | GET | `/executions/{execution_id}` | – | 200 `ExecutionResponse` |
| 4 | GET | `/executions/{execution_id}/result` | – | 200 `ExecutionResultResponse` |
| 5 | GET | `/executions/{execution_id}/steps?cursor=&limit=` | – | 200 `ExecutionStepPageResponse` |
| 6 | GET | `/executions/{execution_id}/steps/{step_id}` | – | 200 `ExecutionStepResponse` |
| 7 | GET | `/executions/{execution_id}/operations?cursor=&limit=` | – | 200 `ExecutionOperationPageResponse` |
| 8 | POST | `/executions/{execution_id}/operations` | `ExecutionOperationCreateRequest` | 202 `ExecutionCommandResponse` |
| 9 | GET | `/executions/{execution_id}/operations/{operation_id}` | – | 200 `ExecutionOperationResponse` |
| 10 | GET | `/executions/{execution_id}/operations/{operation_id}/result` | – | 200 `ExecutionOperationResultResponse` |
| 11 | GET | `/executions/{execution_id}/operations/{operation_id}/steps?cursor=&limit=` | – | 200 `ExecutionStepPageResponse` |
| 12 | GET | `/executions/{execution_id}/events?after_sequence=&cursor=&limit=` | – | 200 `ExecutionEventPageResponse` |
| 13 | GET | `/executions/{execution_id}/artifacts?cursor=&limit=` | – | 200 `ExecutionArtifactPageResponse` |
| 14 | POST | `/executions/{execution_id}/artifacts` | `ExecutionArtifactMaterializeRequest` | 201 `ExecutionArtifactResponse` |
| 15 | GET | `/executions/{execution_id}/notebook?view=SUMMARY\|FULL&start_index=&limit=` | – | 200 `ExecutionNotebookResponse` |
| 16 | GET | `/executions/{execution_id}/notebook/cells/{cell_index}` | – | 200 `ExecutionNotebookCellResponse` |
| 17 | POST | `/executions/{execution_id}/finalize` | `ExecutionFinalizeRequest` | 202 `ExecutionCommandResponse` |
| 18 | POST | `/executions/{execution_id}/cancel` | `ExecutionCancelRequest` | 202 `ExecutionCommandResponse` |
| 19 | POST | `/executions/{execution_id}/retry` | `ExecutionRetryRequest` | 202 `ExecutionCommandResponse` |
| 20 | GET | `/artifacts/{artifact_id}` | – | 200 `ExecutionArtifactResponse` |
| 21 | GET | `/artifacts/{artifact_id}/content` | – | 200 파일 바이트 |

key로 부를 수 없는 경로(404): attempts, diagnostics, 런타임 타깃·풀, 점검(maintenance). 이 서비스 관리자만 씁니다.

상태:

- `ExecutionStatus`: `QUEUED`, `RUNNING`, `WAITING_FOR_OPERATION`, `FINALIZING`, `CANCEL_REQUESTED`, 그리고 종료 상태 `SUCCEEDED`, `FAILED`, `CANCELLED`.
- operation `result.status`: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`.
- step `result.status`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`, `CANCELLED`.
- `failure.type`:
  - `TOOL_ERROR`: 사용자 코드에서 예외가 났습니다.
  - 시간 초과: `STEP_TIMEOUT`, `OPERATION_TIMEOUT`, `OPERATION_WAIT_TIMEOUT`, `EXECUTION_TIMEOUT`, `QUEUE_TIMEOUT`.
  - `OUTPUT_LIMIT_EXCEEDED`.
  - 인프라: `RUNTIME_UNAVAILABLE`, `RUNTIME_SESSION_LOST`, `INFRASTRUCTURE_ERROR`, `WORKER_SHUTDOWN`, `LEASE_EXPIRED`, `INTERNAL_ERROR`.
  - `COMPLETION_FAILED`: 후처리가 실패했습니다. 재시도할 수 없습니다.

## 7. 참고 클라이언트 (Python, httpx)

코드는 영문판과 같습니다.

```python
"""Executor gateway client. Config: AGENTIC_BASE_URL, AGENTIC_API_KEY."""

import os
import time
import uuid
from typing import Any

import httpx

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
RETRYABLE_STATUS = {502, 503, 504}


class GatewayError(Exception):
    def __init__(self, status: int, body: dict[str, Any]):
        error = body.get("error", {}) if isinstance(body, dict) else {}
        self.status = status
        self.code = error.get("code", "UNKNOWN")
        self.details = error.get("details", [])
        self.context = error.get("context")
        super().__init__(f"{status} {self.code}: {error.get('message', '')}")


class ExecutorGateway:
    def __init__(self, user_id: str, *, project_id: str | None = None,
                 session_id: str | None = None):
        self.http = httpx.Client(
            base_url=os.environ["AGENTIC_BASE_URL"].rstrip("/") + "/api/v1/executor",
            timeout=httpx.Timeout(40.0, connect=5.0),  # gateway waits 30 s upstream
        )
        self.headers = {"X-Api-Key": os.environ["AGENTIC_API_KEY"],
                        "X-User-Id": user_id.lower()}
        if project_id:
            self.headers["X-Project-Id"] = project_id
            if session_id:
                self.headers["X-Session-Id"] = session_id

    # transport: retries only network errors and 502/503/504, same body
    def _call(self, method: str, path: str, *, json: Any = None,
              params: dict[str, Any] | None = None, raw: bool = False) -> Any:
        delay = 1.0
        for attempt in range(5):
            try:
                r = self.http.request(method, path, json=json, params=params,
                                      headers=self.headers)
            except httpx.TransportError:
                if attempt == 4:
                    raise
            else:
                if r.status_code < 400:
                    return r if raw else (r.json() if r.content else None)
                if r.status_code not in RETRYABLE_STATUS or attempt == 4:
                    try:
                        body = r.json()
                    except ValueError:
                        body = {}
                    raise GatewayError(r.status_code, body)
            time.sleep(delay)
            delay = min(delay * 2, 30)

    # commands (idempotency key made once per logical write)
    def submit(self, codes: list[str], *, mode: str = "SINGLE",
               wait_seconds: int | None = None, profile: str = "default",
               step_timeout: int | None = 300, metadata: dict | None = None) -> dict:
        lifecycle: dict[str, Any] = {"operation_mode": mode}
        if mode == "MULTI":
            lifecycle["operation_wait_timeout_seconds"] = wait_seconds or 600
        body = {
            "idempotency_key": str(uuid.uuid4()),
            "lifecycle": lifecycle,
            "trigger": {"type": "INTERACTIVE"},
            "runtime": {"type": "JUPYTER", "profile": profile},
            "operation": {"spec": self._spec(codes, start=0, timeout=step_timeout)},
            "metadata": metadata or {},
        }
        return self._call("POST", "/executions", json=body)

    def add_operation(self, execution_id: str, codes: list[str], *,
                      start: int, expected_version: int) -> dict:
        body = {"idempotency_key": str(uuid.uuid4()),
                "expected_version": expected_version,
                "spec": self._spec(codes, start=start, timeout=300)}
        return self._call("POST", f"/executions/{execution_id}/operations", json=body)

    def finalize(self, execution_id: str, expected_version: int) -> dict:
        return self._call("POST", f"/executions/{execution_id}/finalize",
                          json={"idempotency_key": str(uuid.uuid4()),
                                "expected_version": expected_version})

    def cancel(self, execution_id: str, reason: str | None = None) -> dict:
        body: dict[str, Any] = {"idempotency_key": str(uuid.uuid4())}
        if reason:
            body["reason"] = reason
        return self._call("POST", f"/executions/{execution_id}/cancel", json=body)

    def retry(self, execution_id: str) -> dict:
        return self._call("POST", f"/executions/{execution_id}/retry",
                          json={"idempotency_key": str(uuid.uuid4())})

    # reads
    def get(self, execution_id: str) -> dict:
        return self._call("GET", f"/executions/{execution_id}")

    def wait(self, execution_id: str, *, until: set[str] = TERMINAL,
             interval: float = 3.0, timeout: float = 3600) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            execution = self.get(execution_id)
            if execution["state"]["status"] in until:
                return execution
            if time.monotonic() > deadline:
                raise TimeoutError(execution_id)
            time.sleep(interval)

    def result(self, execution_id: str) -> dict:
        return self._call("GET", f"/executions/{execution_id}/result")

    def notebook(self, execution_id: str, *, full: bool = False) -> list[dict]:
        cells, start = [], 0
        while True:
            page = self._call("GET", f"/executions/{execution_id}/notebook",
                              params={"view": "FULL" if full else "SUMMARY",
                                      "start_index": start, "limit": 200})
            cells += page["cells"]
            if not page["page"]["has_more"]:
                return cells
            start = page["page"]["start_index"] + len(page["cells"])

    def artifacts(self, execution_id: str) -> list[dict]:
        items, cursor = [], None
        while True:
            params = {"limit": 1000, **({"cursor": cursor} if cursor else {})}
            page = self._call("GET", f"/executions/{execution_id}/artifacts", params=params)
            items += page["items"]
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    def download(self, artifact_id: str) -> bytes:
        return self._call("GET", f"/artifacts/{artifact_id}/content", raw=True).content

    @staticmethod
    def _spec(codes: list[str], *, start: int, timeout: int | None) -> dict:
        steps = []
        for i, code in enumerate(codes):
            step: dict[str, Any] = {
                "sequence": start + i,
                "payload": {"type": "PYTHON_EXECUTE",
                            "source": {"type": "INLINE", "content": code}},
            }
            if timeout:
                step["step_timeout_seconds"] = timeout
            steps.append(step)
        return {"schema_version": "1.0", "steps": steps}
```

idempotency key는 명령 메서드 안에서 만듭니다. `_call` 안의 재시도는 같은 `json` 객체를 다시 쓰므로 key와 본문이 그대로입니다. `_call` 밖에서 재시도를 더 한다면(예: 작업 큐) key를 작업마다 한 번 만들어 넘겨 줍니다.

사용 예:

```python
gw = ExecutorGateway("e12345", project_id="project-100")

# SINGLE
sub = gw.submit(["import pandas as pd", "print(pd.DataFrame({'a': [1, 2]}).sum())"])
done = gw.wait(sub["execution_id"])
if done["state"]["status"] != "SUCCEEDED":
    print(done["failure"])                       # {"type": "TOOL_ERROR", "message": ...}
for op in gw.result(sub["execution_id"])["operations"]:
    for step in op["steps"]:
        print(step["sequence"], step["result"]["status"], step["result"]["error_message"])
cells = gw.notebook(sub["execution_id"], full=True)   # raw outputs in cells[i]["outputs"]

# MULTI
sub = gw.submit(["df = 1 + 1"], mode="MULTI", wait_seconds=600)
eid = sub["execution_id"]
state = gw.wait(eid, until={"WAITING_FOR_OPERATION", *TERMINAL})
if state["state"]["status"] == "WAITING_FOR_OPERATION":
    try:
        gw.add_operation(eid, ["print(df)"], start=1, expected_version=state["state"]["version"])
    except GatewayError as e:
        if e.code != "EXECUTION_VERSION_CONFLICT":
            raise
        # re-read and decide
    state = gw.wait(eid, until={"WAITING_FOR_OPERATION", *TERMINAL})
    if state["state"]["status"] == "WAITING_FOR_OPERATION":
        gw.finalize(eid, state["state"]["version"])
gw.wait(eid)

# files
for a in gw.artifacts(eid):
    if a["type"] == "NOTEBOOK":
        open("execution.ipynb", "wb").write(gw.download(a["artifact_id"]))
```

## 8. 체크리스트 (자주 하는 실수)

- [ ] 조회를 포함한 모든 요청에 `X-User-Id`.
- [ ] `idempotency_key`는 본문에, 논리적인 쓰기마다 한 번 만들고, 재시도 때는 같은 본문과 함께 다시 씀.
- [ ] 본문에 `actor`, `context`, `tenant_id` 없음. `X-Tenant-Id` 없음.
- [ ] step `sequence`는 operation이 바뀌어도 이어짐(MULTI). 0부터 다시 시작하지 않음.
- [ ] MULTI: `trigger.type = INTERACTIVE`, `operation_wait_timeout_seconds ≥ 30`. SINGLE: `operation_wait_timeout_seconds` 없음.
- [ ] `expected_version`은 가장 최근 조회 값. `409` 충돌이면 다시 읽고, 무작정 다시 보내지 않음.
- [ ] `execution.completed` / `FAILED` / `CANCELLED`는 모두 "끝". `state.status`와 `failure`를 확인.
- [ ] 출력은 `/notebook`, 파일은 `/artifacts/{id}/content`에서. `result_ref`는 쓰지 않음.
- [ ] `Location`은 `/api/v1/` → `/api/v1/executor/`로 바꾼 뒤에만 따라감.
- [ ] 일반키: `user_id` 필터를 쓰지 않거나, 정확히 자기 `X-User-Id`만.
- [ ] 모르는 응답 필드와 모르는 `event_type`은 무시.
- [ ] `Range`를 요청하지 않음. 다운로드는 항상 통째로.

## 9. 타입

executor OpenAPI에서 자동으로 만든 부분입니다. 손으로 고치지 않습니다. `unknown fields → 422`가 붙은 interface는 요청 본문입니다. 응답 타입에는 필드가 늘 수 있으니 모르는 필드는 무시합니다. `string` 시각은 시간대가 있는 ISO 8601이고, id는 UUID 문자열입니다.

<!-- gen:begin types -->
```ts
interface ArtifactLineage {
  parent_artifact_id: string | null;
  external_parent_asset_id: string | null;
}
interface ArtifactProducer {
  execution_id: string;
  execution_attempt_id: string | null;
  execution_step_id: string | null;
  execution_step_attempt_id: string | null;
}
type ArtifactStatus = "AVAILABLE" | "INCOMPLETE" | "DELETED";
interface ArtifactStorage {
  type: ArtifactStorageType;
  uri: string;
  relative_path: string | null;
  media_type: string | null;
  size_bytes: number | null;
  checksum_sha256: string | null;
}
interface ArtifactStorageSummary {
  type: ArtifactStorageType;
  media_type: string | null;
  size_bytes: number | null;
}
type ArtifactStorageType = "PV" | "S3";
type ArtifactType = "DATASET" | "NOTEBOOK" | "REPORT" | "PLOT" | "MODEL" | "METRIC" | "LOG" | "OTHER";
interface AttemptState {
  status: AttemptStatus;
}
type AttemptStatus = "RUNNING" | "WAITING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
type CodeSourceType = "INLINE" | "PATH";
interface DeadlinesResponse {
  operation_wait_expires_at: string | null;
  execution_expires_at: string | null;
}
interface EventDelivery {
  status: OutboxStatus;
  attempt_count: number;
  available_at: string;
  published_at: string | null;
  last_error: string | null;
}
interface ExecutionArtifactMaterializeRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  type: "NOTEBOOK" | "REPORT" | "PLOT" | "METRIC" | "LOG" | "OTHER";
  source: InlineArtifactSource | PathArtifactSource;
  name?: string | null; // 길이 ≥ 1, 길이 ≤ 255
  description?: string | null; // 길이 ≤ 4000
  media_type?: string | null; // 길이 ≥ 1, 길이 ≤ 255
  append_to_notebook?: boolean; // default false
  metadata?: Record<string, unknown>;
}
interface ExecutionArtifactPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionArtifactSummaryResponse[];
}
interface ExecutionArtifactResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  artifact_id: string;
  name: string;
  description: string | null;
  type: ArtifactType;
  status: ArtifactStatus;
  produced_by: ArtifactProducer;
  lineage: ArtifactLineage;
  storage: ArtifactStorage;
  metadata: Record<string, unknown>;
}
interface ExecutionArtifactSummaryResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  artifact_id: string;
  name: string;
  type: ArtifactType;
  status: ArtifactStatus;
  produced_by: ArtifactProducer;
  storage: ArtifactStorageSummary;
}
interface ExecutionAttemptResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  attempt_id: string;
  execution_id: string;
  attempt_number: number;
  state: AttemptState;
  failure: FailureResponse | null;
  lifecycle: Lifecycle;
  step_count: number;
}
interface ExecutionCancelRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  reason?: string | null; // 길이 ≤ 2000
}
interface ExecutionCommandResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  execution_id: string;
  operation: ExecutionOperationReceipt | null;
  state: ExecutionCommandState;
}
interface ExecutionCommandState {
  status: ExecutionStatus;
  version: number;
}
interface ExecutionContext {
  user_id: string;
  project_id: string | null;
  session_id: string | null;
}
interface ExecutionEventPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionEventResponse[];
}
interface ExecutionEventResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  event_id: string;
  execution_id: string;
  event_sequence: number;
  schema_version: string;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  delivery: EventDelivery | null;
}
interface ExecutionFinalizeRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  expected_version: number; // ≥ 0
}
interface ExecutionLifecycleInput { // unknown fields → 422
  operation_mode: OperationMode;
  operation_wait_timeout_seconds?: number | null; // ≥ 30
}
interface ExecutionLifecycleResponse {
  operation_mode: OperationMode;
  operation_wait_timeout_seconds: number | null;
  started_at: string | null;
  finished_at: string | null;
}
interface ExecutionNotebookCellResponse {
  execution_id: string;
  cell: NotebookCellResponse;
}
interface ExecutionNotebookResponse {
  execution_id: string;
  view: "SUMMARY" | "FULL";
  metadata: Record<string, unknown>;
  cells: (NotebookCellSummaryResponse | NotebookCellResponse)[];
  page: NotebookPage;
}
interface ExecutionOperationCreateRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  expected_version: number; // ≥ 0
  operation_timeout_seconds?: number | null; // ≥ 1
  spec: ExecutionSpec;
  metadata?: Record<string, unknown>;
}
interface ExecutionOperationInput { // unknown fields → 422
  operation_timeout_seconds?: number | null; // ≥ 1
  spec: ExecutionSpec;
  metadata?: Record<string, unknown>;
}
interface ExecutionOperationPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionOperationSummaryResponse[];
}
interface ExecutionOperationReceipt {
  operation_id: string;
  steps: ExecutionStepReceipt[];
}
interface ExecutionOperationResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  operation_id: string;
  execution_id: string;
  operation_number: number;
  schema_version: string;
  sequence_range: OperationSequenceRange;
  operation_timeout_seconds: number | null;
  metadata: Record<string, unknown>;
  execution_attempt_id: string | null;
  result: OperationResult;
  lifecycle: Lifecycle;
  step_count: number;
}
interface ExecutionOperationResultResponse {
  execution: ExecutionResultExecutionResponse;
  operation: ExecutionResultOperationResponse;
}
interface ExecutionOperationSummaryResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  operation_id: string;
  operation_number: number;
  sequence_range: OperationSequenceRange;
  result: OperationResult;
  lifecycle: Lifecycle;
  step_count: number;
}
interface ExecutionPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionSummaryResponse[];
}
interface ExecutionResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  execution_id: string;
  trigger_type: TriggerType;
  trigger: ExecutionTrigger;
  tenant_id: string;
  context: ExecutionContext;
  metadata: Record<string, unknown>;
  runtime: ExecutionRuntime;
  state: ExecutionState;
  workspace: WorkspaceResponse;
  failure: FailureResponse | null;
  retry: RetryResponse;
  recovery: RecoveryResponse;
  deadlines: DeadlinesResponse;
  lifecycle: ExecutionLifecycleResponse;
}
interface ExecutionResultExecutionResponse {
  execution_id: string;
  state: ExecutionCommandState;
}
interface ExecutionResultOperationResponse {
  operation_id: string;
  operation_number: number;
  sequence_range: OperationSequenceRange;
  result: OperationResult;
  lifecycle: Lifecycle;
  steps: ExecutionResultStepResponse[];
}
interface ExecutionResultResponse {
  execution: ExecutionResultExecutionResponse;
  operations: ExecutionResultOperationResponse[];
  attempts: ExecutionAttemptResponse[];
  artifacts: ExecutionArtifactSummaryResponse[];
}
interface ExecutionResultStepResponse {
  step_id: string;
  sequence: number;
  lineage: ToolReference;
  result: StepResult;
  lifecycle: Lifecycle;
}
interface ExecutionRetryRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
}
interface ExecutionRuntime {
  type: RuntimeType;
  pool: RuntimePool;
  profile: string;
  target_id: string | null;
  kernel_id: string | null;
}
interface ExecutionRuntimeInput { // unknown fields → 422
  type: RuntimeType;
  profile: string; // 길이 ≥ 1, 길이 ≤ 128
}
interface ExecutionSpec { // unknown fields → 422
  schema_version: "1.0";
  steps: ExecutionStepInput[]; // 항목 ≥ 1
}
interface ExecutionState {
  status: ExecutionStatus;
  version: number;
  cancellation_reason: string | null;
  finalized_by?: FinalizedBy | null;
}
type ExecutionStatus = "QUEUED" | "RUNNING" | "WAITING_FOR_OPERATION" | "FINALIZING" | "CANCEL_REQUESTED" | "CANCELLED" | "SUCCEEDED" | "FAILED";
interface ExecutionStepInput { // unknown fields → 422
  sequence: number; // ≥ 0
  payload: PythonExecutePayload;
  step_timeout_seconds?: number | null; // ≥ 1
  lineage?: StepLineage | null;
}
interface ExecutionStepPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionStepSummaryResponse[];
}
interface ExecutionStepReceipt {
  sequence: number;
  step_id: string;
}
interface ExecutionStepResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  step_id: string;
  execution_id: string;
  sequence: number;
  code_hash: string | null;
  source: StepSourceResponse;
  step_timeout_seconds: number | null;
  lineage: ToolReference;
  result: StepResult;
  lifecycle: Lifecycle;
}
interface ExecutionStepSummaryResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  step_id: string;
  execution_id: string;
  sequence: number;
  lineage: ToolReference;
  result: StepResultSummary;
  lifecycle: Lifecycle;
}
interface ExecutionSubmitRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  lifecycle: ExecutionLifecycleInput;
  trigger: ExecutionTriggerInput;
  runtime: ExecutionRuntimeInput;
  operation: ExecutionOperationInput;
  metadata?: Record<string, unknown>;
}
interface ExecutionSummaryResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  execution_id: string;
  operation_mode: OperationMode;
  trigger_type: TriggerType;
  trigger: ExecutionTrigger;
  tenant_id: string;
  context: ExecutionContext;
  metadata: Record<string, unknown>;
  state: ExecutionCommandState;
  lifecycle: Lifecycle;
  step_count: number;
}
interface ExecutionTrigger {
  type: TriggerType;
}
interface ExecutionTriggerInput { // unknown fields → 422
  type: TriggerType;
}
interface FailureResponse {
  type: FailureType;
  message: string;
}
type FailureType = "TOOL_ERROR" | "INFRASTRUCTURE_ERROR" | "WORKER_SHUTDOWN" | "RUNTIME_UNAVAILABLE" | "LEASE_EXPIRED" | "INTERNAL_ERROR" | "OPERATION_WAIT_TIMEOUT" | "OPERATION_TIMEOUT" | "STEP_TIMEOUT" | "EXECUTION_TIMEOUT" | "QUEUE_TIMEOUT" | "OUTPUT_LIMIT_EXCEEDED" | "RUNTIME_SESSION_LOST" | "COMPLETION_FAILED";
type FinalizedBy = "AGENT" | "WAIT_TIMEOUT" | "MAX_RUNTIME";
interface InlineArtifactSource { // unknown fields → 422
  type: "INLINE";
  content: string; // 길이 ≥ 1
}
interface InlineStepSource { // unknown fields → 422
  type: "INLINE";
  content: string; // 길이 ≥ 1
}
interface Lifecycle {
  started_at: string | null;
  finished_at: string | null;
}
interface NotebookCellResponse {
  index: number;
  id: string | null;
  type: string;
  execution_count: number | null;
  source: string;
  line_count: number;
  metadata: Record<string, unknown>;
  output_summary: OutputSummary;
  outputs: Record<string, unknown>[];
}
interface NotebookCellSummaryResponse {
  index: number;
  id: string | null;
  type: string;
  execution_count: number | null;
  source_preview: string;
  source_truncated: boolean;
  line_count: number;
  metadata: Record<string, unknown>;
  output_summary: OutputSummary;
}
interface NotebookPage {
  start_index: number;
  limit: number;
  total_count: number;
  has_more: boolean;
}
interface NotebookProjectionResponse {
  status: NotebookProjectionStatus;
  attempt_count: number;
  error_message: string | null;
  projected_at: string | null;
}
type NotebookProjectionStatus = "NOT_STARTED" | "PENDING" | "SUCCEEDED" | "FAILED";
type OperationMode = "SINGLE" | "MULTI";
interface OperationResult {
  status: OperationStatus;
  error_message: string | null;
}
interface OperationSequenceRange {
  first: number;
  last: number;
}
type OperationStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
type OutboxStatus = "PENDING" | "PUBLISHED";
interface OutputSummary {
  output_count: number; // ≥ 0
  output_types: Record<string, unknown>;
  stream_names: string[];
  mime_types: string[];
  has_image: boolean;
  image_count: number; // ≥ 0
  has_error: boolean;
}
interface PathArtifactSource { // unknown fields → 422
  type: "PATH";
  path: string; // 길이 ≥ 1, 길이 ≤ 4096
  sha256: string; // `^[0-9a-fA-F]{64}$`
}
interface PathStepSource { // unknown fields → 422
  type: "PATH";
  path: string; // 길이 ≥ 1, 길이 ≤ 4096
  sha256: string; // `^[0-9a-fA-F]{64}$`
}
interface PythonExecutePayload { // unknown fields → 422
  type: "PYTHON_EXECUTE";
  source: InlineStepSource | PathStepSource;
}
interface RecoveryResponse {
  count: number;
  runtime_session_cleanup_status: RuntimeSessionCleanupStatus;
  runtime_abort_status: RuntimeAbortStatus;
}
interface RetryResponse {
  strategy: RetryStrategy;
  count: number;
  from_sequence: number | null;
  retained_runtime_session_until: string | null;
}
type RetryStrategy = "NOT_RETRYABLE" | "FROM_FAILED_STEP" | "FROM_START";
type RuntimeAbortStatus = "NOT_REQUIRED" | "PENDING" | "IDLE_CONFIRMED" | "SESSION_DELETED" | "SESSION_MISSING" | "FAILED";
type RuntimePool = "INTERACTIVE" | "BATCH";
type RuntimeSessionCleanupStatus = "NOT_REQUIRED" | "PENDING" | "SUCCEEDED" | "FAILED";
type RuntimeType = "JUPYTER";
interface StepLineage { // unknown fields → 422
  skill_name?: string | null; // 길이 ≤ 255
  tool_name?: string | null; // 길이 ≤ 255
  input_parameters?: Record<string, unknown>;
}
interface StepResult {
  status: StepStatus;
  output_summary: OutputSummary;
  error_message: string | null;
  result_ref: StepResultReference | null;
}
interface StepResultReference {
  storage?: "SHARED_PV"; // default "SHARED_PV"
  execution_id: string;
  step_id: string;
  attempt_id: string;
  fencing_token: number;
  relative_path: string;
  checksum_sha256: string;
  size_bytes: number;
  complete: boolean;
  representation_count: number;
  total_size_bytes: number;
}
interface StepResultSummary {
  status: StepStatus;
  output_summary: OutputSummary;
  error_message: string | null;
}
interface StepSourceResponse {
  type: CodeSourceType;
  path: string | null;
  sha256: string;
}
type StepStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED" | "CANCELLED";
interface ToolReference {
  skill_name: string | null;
  tool_name: string | null;
  input_parameters: Record<string, unknown>;
}
type TriggerType = "INTERACTIVE" | "BATCH";
interface WorkspaceResponse {
  path: string | null;
  notebook_path: string | null;
  notebook_projection: NotebookProjectionResponse;
}
```
<!-- gen:end types -->

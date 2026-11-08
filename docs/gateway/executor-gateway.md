# executor 게이트웨이 API (`/api/v1/executor/…`)

pr-agentic-service를 거쳐 executor를 부르는 API입니다. executor는 Python 코드를 Jupyter 커널에서 실행하고, 결과(노트북, 출력, 아티팩트)를 보관합니다. 호출자는 executor 주소와 key를 모르고, 이 서비스의 key와 `X-User-Id`로 부릅니다.

먼저 [00-common.md](00-common.md)를 읽습니다. 주소, key 종류, `X-User-Id`, 조회 범위, 오류 형식, 넘어가는 헤더는 거기에 있고 여기서는 반복하지 않습니다.

## 1. 개념

```
Execution 1──* Operation 1──* Step           (Step 하나 = 코드 셀 하나)
Execution 1──* Attempt                         (재시도·복구 시도, 관리자 화면 전용)
Execution 1──* Artifact                        (노트북, 리포트, 그림, 파일)
Execution 1──1 Notebook                        (실행한 셀과 출력이 쌓이는 .ipynb)
```

| 개념 | 설명 |
| --- | --- |
| Execution | 실행 한 건. 커널 하나를 잡고 Operation을 차례로 실행합니다. 호출자의 tenant, `X-User-Id`(소유자), `X-Project-Id`, `X-Session-Id`가 `context`로 붙고 바뀌지 않습니다 |
| Operation | 한 번에 제출하는 Step 묶음. 최초 제출에 하나가 들어 있고, MULTI에서는 이후 계속 추가합니다 |
| Step | 실행할 Python 코드 하나. `sequence`는 Execution 전체에서 0부터 이어지는 번호입니다 |
| SINGLE | 제출한 Operation을 끝까지 실행하고 Execution을 끝냅니다 |
| MULTI | Operation이 끝나면 커널을 살려 둔 채 `WAITING_FOR_OPERATION`으로 기다립니다. 다음 Operation을 붙이거나 finalize해서 끝냅니다. 변수가 커널에 남아 있어서 이전 Step의 결과를 이어서 씁니다 |
| Artifact | 실행이 남긴 파일. 노트북(`NOTEBOOK`)은 처음 저장될 때부터 등록되고 실행 중에도 받을 수 있습니다 |

모든 명령(제출, 추가, finalize, 취소, 재시도)은 **비동기**입니다. `202 Accepted`는 "저장되어 대기열에 들어갔다"는 뜻이고, 결과는 조회로 확인합니다.

## 2. 엔드포인트 한눈에 보기

API key로 부를 수 있는 21개입니다. 이 밖의 `/api/v1/executor/…` 경로는 404입니다. 아래 표는 레퍼런스(10장)와 같은 순서이고, 요청·응답 이름은 11장 스키마로 이어집니다.

<!-- gen:begin summary -->
| # | Method | Path | 요청 본문 | 성공 응답 |
| --- | --- | --- | --- | --- |
| 1 | GET | `/api/v1/executor/executions` | - | 200 ExecutionPageResponse |
| 2 | POST | `/api/v1/executor/executions` | ExecutionSubmitRequest | 202 ExecutionCommandResponse |
| 3 | GET | `/api/v1/executor/executions/{execution_id}` | - | 200 ExecutionResponse |
| 4 | GET | `/api/v1/executor/executions/{execution_id}/result` | - | 200 ExecutionResultResponse |
| 5 | GET | `/api/v1/executor/executions/{execution_id}/steps` | - | 200 ExecutionStepPageResponse |
| 6 | GET | `/api/v1/executor/executions/{execution_id}/steps/{step_id}` | - | 200 ExecutionStepResponse |
| 7 | GET | `/api/v1/executor/executions/{execution_id}/operations` | - | 200 ExecutionOperationPageResponse |
| 8 | POST | `/api/v1/executor/executions/{execution_id}/operations` | ExecutionOperationCreateRequest | 202 ExecutionCommandResponse |
| 9 | GET | `/api/v1/executor/executions/{execution_id}/operations/{operation_id}` | - | 200 ExecutionOperationResponse |
| 10 | GET | `/api/v1/executor/executions/{execution_id}/operations/{operation_id}/result` | - | 200 ExecutionOperationResultResponse |
| 11 | GET | `/api/v1/executor/executions/{execution_id}/operations/{operation_id}/steps` | - | 200 ExecutionStepPageResponse |
| 12 | GET | `/api/v1/executor/executions/{execution_id}/events` | - | 200 ExecutionEventPageResponse |
| 13 | GET | `/api/v1/executor/executions/{execution_id}/artifacts` | - | 200 ExecutionArtifactPageResponse |
| 14 | POST | `/api/v1/executor/executions/{execution_id}/artifacts` | ExecutionArtifactMaterializeRequest | 201 ExecutionArtifactResponse |
| 15 | GET | `/api/v1/executor/executions/{execution_id}/notebook` | - | 200 ExecutionNotebookResponse |
| 16 | GET | `/api/v1/executor/executions/{execution_id}/notebook/cells/{cell_index}` | - | 200 ExecutionNotebookCellResponse |
| 17 | POST | `/api/v1/executor/executions/{execution_id}/finalize` | ExecutionFinalizeRequest | 202 ExecutionCommandResponse |
| 18 | POST | `/api/v1/executor/executions/{execution_id}/cancel` | ExecutionCancelRequest | 202 ExecutionCommandResponse |
| 19 | POST | `/api/v1/executor/executions/{execution_id}/retry` | ExecutionRetryRequest | 202 ExecutionCommandResponse |
| 20 | GET | `/api/v1/executor/artifacts/{artifact_id}` | - | 200 ExecutionArtifactResponse |
| 21 | GET | `/api/v1/executor/artifacts/{artifact_id}/content` | - | 200 string (binary) |
<!-- gen:end summary -->

| 구분 | 경로 (`/api/v1/executor` 뒤) | 하는 일 |
| --- | --- | --- |
| 실행 | `POST /executions`, `GET /executions`, `GET /executions/{id}` | 제출, 목록, 상태 |
| 명령 | `POST /executions/{id}/operations`, `/finalize`, `/cancel`, `/retry` | MULTI 추가·종료, 취소, SINGLE 재시도 |
| 결과 | `GET /executions/{id}/result`, `/steps`, `/steps/{step_id}`, `/operations`, `/operations/{operation_id}`, `/operations/{operation_id}/result`, `/operations/{operation_id}/steps` | 상태·출력 요약 |
| 노트북 | `GET /executions/{id}/notebook`, `/notebook/cells/{n}` | 셀 코드와 **출력 원문** |
| 이벤트 | `GET /executions/{id}/events` | 진행 이벤트 이력 (폴링) |
| 아티팩트 | `GET·POST /executions/{id}/artifacts`, `GET /artifacts/{artifact_id}`, `GET /artifacts/{artifact_id}/content` | 목록, 리포트 저장, 상세, 파일 받기 |

## 3. 기본 흐름

공통 헤더(아래 예시에서는 한 번만 적습니다):

```http
X-Api-Key: pas_live_xxxxxxxx
X-User-Id: e12345
X-Project-Id: project-100        (선택)
X-Session-Id: session-100        (선택, X-Project-Id가 있어야 함)
Content-Type: application/json   (POST)
```

### 3.1 SINGLE: 한 번 실행하고 끝

```
POST /api/v1/executor/executions                        → 202 {execution_id, state: QUEUED}
GET  /api/v1/executor/executions/{id}                   → state.status 가 SUCCEEDED / FAILED / CANCELLED 가 될 때까지 (2~5초 간격)
GET  /api/v1/executor/executions/{id}/result            → Step별 상태와 출력 요약
GET  /api/v1/executor/executions/{id}/notebook?view=FULL → 셀 코드와 출력 원문
```

```json
POST /api/v1/executor/executions
{
  "idempotency_key": "report-agent-7f3c2a10",
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
    }
  },
  "metadata": {"caller_task_id": "t-100"}
}
```

```json
202 Accepted
Location: /api/v1/executions/0b1e…        (executor 기준 경로, 00-common 5.2)
{
  "execution_id": "0b1e…",
  "operation": {"operation_id": "5c2d…", "steps": [{"sequence": 0, "step_id": "9a7f…"}]},
  "state": {"status": "QUEUED", "version": 0},
  "created_by": "e12345", "created_by_client": "…",
  "updated_by": "e12345", "updated_by_client": "…",
  "created_at": "2026-11-08T05:00:00Z", "updated_at": "2026-11-08T05:00:00Z"
}
```

### 3.2 MULTI: 결과를 보고 이어서 실행

```
POST /executions  (lifecycle.operation_mode = MULTI, operation_wait_timeout_seconds = 600)
  ↓ 202
GET  /executions/{id}                         → WAITING_FOR_OPERATION 이 될 때까지. state.version 을 기억
GET  /executions/{id}/result (또는 /notebook) → 결과 확인
POST /executions/{id}/operations              → {expected_version: <방금 version>, spec: {steps: [sequence 1…]}}
  ↓ 202, 다시 WAITING_FOR_OPERATION 까지 반복
POST /executions/{id}/finalize                → {expected_version: <최신 version>}
GET  /executions/{id}                         → SUCCEEDED / FAILED
```

- 다음 Operation의 Step 번호는 Execution 전체에서 이어집니다. 첫 Operation이 0, 1을 썼으면 다음은 2부터입니다.
- `expected_version`은 직전에 읽은 `state.version`입니다. 그 사이 상태가 바뀌었으면 409 `EXECUTION_VERSION_CONFLICT`이고, 다시 읽은 뒤 판단합니다.
- `operation_wait_timeout_seconds`(30초 이상) 안에 아무것도 안 보내면 Execution이 스스로 끝납니다(`finalized_by: WAIT_TIMEOUT`). 조회는 대기 기한을 늘리지 않습니다.
- 마지막 Operation이 실패했으면 finalize는 409입니다. 고친 코드로 Operation을 하나 더 성공시킨 뒤 finalize하거나 cancel합니다.

### 3.3 취소와 재시도

- 취소: `POST /executions/{id}/cancel` `{"idempotency_key", "reason"?}` → `CANCEL_REQUESTED` → 조회로 `CANCELLED`(또는 `FAILED`) 확인. 끝난 실행은 409.
- 재시도: SINGLE이 `FAILED`이고 `retry.strategy`가 `NOT_RETRYABLE`이 아닐 때만 `POST /executions/{id}/retry`. 새 Execution을 만들지 않고 같은 ID로 다시 돕니다. MULTI는 재시도 대신 고친 Operation을 붙입니다.

### 3.4 진행 상황 보기

이 게이트웨이는 executor 이벤트 스트림(Redis)을 중계하지 않습니다. 다음 둘 중 하나로 확인합니다.

- `GET /executions/{id}`를 2~5초 간격으로 읽습니다. 가장 간단합니다.
- `GET /executions/{id}/events?after_sequence=<마지막으로 본 event_sequence>`로 새 이벤트만 읽습니다. 응답의 `next_cursor`가 있으면 그대로 `cursor`로 넘겨 이어 읽습니다(이때 `after_sequence`는 빼고).

## 4. 상태

### 4.1 Execution `state.status`

| 값 | 뜻 | 끝? |
| --- | --- | --- |
| `QUEUED` | 대기 (커널 배정 전) | |
| `RUNNING` | 실행 중 | |
| `WAITING_FOR_OPERATION` | MULTI: 다음 Operation이나 finalize를 기다림 | |
| `FINALIZING` | finalize 처리 중 | |
| `CANCEL_REQUESTED` | 취소 요청 받음, 정리 중 | |
| `SUCCEEDED` | 성공 | 예 |
| `FAILED` | 실패 (`failure.type`에 이유) | 예 |
| `CANCELLED` | 취소 확정 | 예 |

- `state.version`은 상태가 바뀔 때마다 늘어납니다. MULTI 명령의 `expected_version`에 씁니다.
- `failure.type`: `TOOL_ERROR`(코드 오류), `STEP_TIMEOUT`, `OPERATION_TIMEOUT`, `OPERATION_WAIT_TIMEOUT`, `EXECUTION_TIMEOUT`(전체 7일), `QUEUE_TIMEOUT`(대기 24시간), `OUTPUT_LIMIT_EXCEEDED`, `RUNTIME_UNAVAILABLE`, `RUNTIME_SESSION_LOST`, `INFRASTRUCTURE_ERROR`, `WORKER_SHUTDOWN`, `LEASE_EXPIRED`, `COMPLETION_FAILED`(노트북·아티팩트 후처리 실패, 재시도 불가), `INTERNAL_ERROR`.
- `retry.strategy`: `NOT_RETRYABLE`, `FROM_FAILED_STEP`(보존한 커널에서 실패한 Step부터, 보존 1시간), `FROM_START`(새 커널에서 처음부터). executor가 정하고 호출자는 고르지 않습니다.
- `CANCELLED`라도 커널 정리가 끝났다는 보장은 없습니다(`recovery.runtime_session_cleanup_status`).

### 4.2 Operation과 Step

| 대상 | 값 |
| --- | --- |
| Operation `result.status` | `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED` |
| Step `result.status` | `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`(앞 Step 실패나 취소로 실행 안 됨), `CANCELLED`(실행 중 취소) |

## 5. 경로별 상세 설명

경로는 모두 `/api/v1/executor` 뒤에 붙습니다. 헤더는 3장의 공통 헤더이고, 필드 전체 목록은 10장 레퍼런스와 11장 스키마에 있습니다.

### 5.1 `POST /executions` 실행 제출

새 Execution과 첫 Operation을 만듭니다. 성공하면 `202`와 [ExecutionCommandResponse](#schema-executioncommandresponse)입니다.

| 본문 필드 | 필수 | 설명 |
| --- | --- | --- |
| `idempotency_key` | O | 1~255자. **tenant 안에서** 구분합니다. 같은 키·같은 본문이면 같은 Execution을 돌려주고, 같은 키·다른 본문은 409 |
| `lifecycle.operation_mode` | O | `SINGLE` 또는 `MULTI` |
| `lifecycle.operation_wait_timeout_seconds` | MULTI만 | MULTI에서 다음 요청을 기다리는 시간(초, 30 이상). SINGLE에 넣으면 422 |
| `trigger.type` | O | `INTERACTIVE`(대화형·온라인) 또는 `BATCH`(일괄). 커널 풀이 이 값으로 정해집니다. MULTI는 `INTERACTIVE`만 |
| `runtime.type` | O | `JUPYTER` |
| `runtime.profile` | O | 커널 환경. 기본 `default`. 쓸 수 있는 값은 `GET /api/v1/batch/runtimes`의 `profile`로 확인합니다 |
| `operation.spec.schema_version` | O | `"1.0"` |
| `operation.spec.steps[]` | O | 1개 이상, 한 Operation에 최대 100개, Execution 전체 1000개. `sequence`는 0부터 빈틈없이 |
| `steps[].payload` | O | `{"type": "PYTHON_EXECUTE", "source": {"type": "INLINE", "content": "<코드>"}}` |
| `steps[].step_timeout_seconds` | | Step 하나의 제한(초, 1 이상). 없으면 제한 없음 |
| `steps[].lineage` | | `{skill_name?, tool_name?, input_parameters?}` 추적용. 그대로 저장됩니다 |
| `operation.operation_timeout_seconds` | | Operation 전체 제한(초). 없으면 제한 없음 |
| `operation.metadata`, `metadata` | | 호출자 값. 키 32개 이하(`^[a-z][a-z0-9_]{0,63}$`), JSON 4096바이트 이하. 조회 결과와 완료 이벤트에 그대로 나옵니다. 비밀값을 넣지 않습니다 |

- 본문에 `context`, `tenant_id`, `actor`를 넣지 않습니다(422). 사용자·프로젝트·세션·tenant는 헤더로 정해지고, 누가 했는지(`created_by`)는 `X-User-Id`로 기록됩니다.
- **코드는 `INLINE`으로 보냅니다.** `PATH` source(executor 입력 저장소의 `.py` 파일)는 그 저장소에 파일을 쓸 수 있는 우리 내부 서비스만 씁니다.
- 한도를 넘으면 422 `INVALID_EXECUTION_SPEC`이고 `details[].context`에 한도와 실제 값이 들어갑니다.

### 5.2 `GET /executions` 실행 목록

최신순 목록입니다. 쿼리: `user_id`, `project_id`, `session_id`, `trigger_type`, `status`, `cursor`, `limit`(1~200, 기본 100). 필터는 AND입니다.

- `user_id`는 마스터키에서 소유자로 거를 때 씁니다. 일반키는 빼거나 `X-User-Id`와 같은 값만 넣을 수 있고, 다르면 403 `FORBIDDEN`입니다. 형식이 틀리면 400 `INVALID_IDENTITY`입니다.
- `project_id`, `session_id`는 `X-Project-Id`, `X-Session-Id`와 같은 형식 검사를 받습니다.

- 일반키는 `X-User-Id`의 실행만, 마스터키는 tenant 전체 실행입니다([00-common 4.2](00-common.md#42-조회-범위는-key-종류가-정합니다)).
- 각 항목은 [ExecutionSummaryResponse](#schema-executionsummaryresponse)입니다. `context.user_id`로 소유자를 압니다.

### 5.3 `GET /executions/{execution_id}` 실행 상태

현재 상태의 원본입니다. [ExecutionResponse](#schema-executionresponse)의 주요 필드:

| 필드 | 설명 |
| --- | --- |
| `state` | `status`, `version`, `cancellation_reason`, `finalized_by`(`AGENT`·`WAIT_TIMEOUT`·`MAX_RUNTIME`·null) |
| `lifecycle` | `operation_mode`, `operation_wait_timeout_seconds`, `started_at`, `finished_at` |
| `failure` | 실패하면 `{type, message}`, 아니면 null |
| `retry` | `strategy`, `count`, `from_sequence`, `retained_runtime_session_until` |
| `deadlines` | `operation_wait_expires_at`(MULTI 대기 기한), `execution_expires_at` |
| `context` | `user_id`, `project_id`, `session_id` |
| `runtime` | `type`, `pool`, `profile`, `target_id`, `kernel_id`. `kernel_id`는 Jupyter 커널 ID(`/api/kernels/{id}`)로, 호출자의 `X-Session-Id`와 무관합니다. 커널을 만들기 전과 정리한 뒤에는 null입니다 |
| `workspace` | `path`, `notebook_path`, `notebook_projection{status, attempt_count, error_message, projected_at}` |
| `recovery` | 커널 정리 상태 (`runtime_session_cleanup_status`, `runtime_abort_status`) |
| `trigger`, `metadata`, `tenant_id` | 제출할 때의 값 |
| `created_by`, `updated_by` | 그 쓰기를 한 `X-User-Id` |
| `created_by_client`, `updated_by_client` | executor가 본 API key의 클라이언트 이름. 이 게이트웨이를 거친 요청은 모두 우리 서비스 이름입니다(호출자 key 이름이 아닙니다). 예전 행은 null |

### 5.4 `GET /executions/{execution_id}/result` 통합 결과

Execution 상태와 모든 Operation, Step, Attempt 요약, Artifact 요약을 한 번에 돌려줍니다(페이지 없음). [ExecutionResultResponse](#schema-executionresultresponse).

- `operations[].steps[].result`: `status`, `error_message`, `output_summary`(출력 종류·개수, `has_image`, `has_error`), `result_ref`.
- **`result_ref`는 executor와 우리 서비스가 함께 쓰는 내부 저장소(SHARED_PV) 경로라 호출자는 열 수 없습니다.** 출력 원문은 노트북 API(5.9)로 읽습니다.

### 5.5 Step과 Operation 조회

| 경로 | 응답 | 용도 |
| --- | --- | --- |
| `GET /executions/{id}/steps` | [ExecutionStepPageResponse](#schema-executionsteppageresponse) | 모든 Step의 현재 상태 (페이지) |
| `GET /executions/{id}/steps/{step_id}` | [ExecutionStepResponse](#schema-executionstepresponse) | Step 하나: 실행한 코드 출처(`source`), lineage, 결과 |
| `GET /executions/{id}/operations` | [ExecutionOperationPageResponse](#schema-executionoperationpageresponse) | Operation 이력 |
| `GET /executions/{id}/operations/{operation_id}` | [ExecutionOperationResponse](#schema-executionoperationresponse) | Operation 하나 |
| `GET /executions/{id}/operations/{operation_id}/result` | [ExecutionOperationResultResponse](#schema-executionoperationresultresponse) | Operation과 그 Step 결과 전부 |
| `GET /executions/{id}/operations/{operation_id}/steps` | [ExecutionStepPageResponse](#schema-executionsteppageresponse) | 그 Operation의 Step (페이지) |

MULTI에서 방금 붙인 Operation의 결과만 볼 때는 `/operations/{operation_id}/result`가 편합니다. `operation_id`는 추가 응답의 `operation.operation_id`입니다.

### 5.6 `POST /executions/{execution_id}/operations` MULTI 다음 Operation

`WAITING_FOR_OPERATION`인 MULTI에만 됩니다. 본문 [ExecutionOperationCreateRequest](#schema-executionoperationcreaterequest):

```json
{
  "idempotency_key": "report-agent-7f3c2a10-op2",
  "expected_version": 4,
  "operation_timeout_seconds": 600,
  "spec": {"schema_version": "1.0",
           "steps": [{"sequence": 1, "payload": {"type": "PYTHON_EXECUTE",
                      "source": {"type": "INLINE", "content": "df.describe()"}}}]},
  "metadata": {}
}
```

- 최초 제출과 달리 `operation`·`lifecycle`·`runtime`·`trigger`를 다시 보내지 않습니다. `spec`과 시간 제한을 본문 바로 아래에 둡니다.
- 멱등키는 **Execution 안에서** 구분합니다.
- 응답 202의 `state.version`이 새 버전이고, `operation.operation_id`가 새 Operation입니다.
- 같은 `expected_version`으로 두 요청이 동시에 오면 하나만 성공하고 나머지는 409입니다. 버전 확인이 Step 검사보다 먼저라, 오래된 버전이면 Step 번호 오류(422)보다 409가 먼저 납니다.

### 5.7 `POST /executions/{execution_id}/finalize` MULTI 종료

`{"idempotency_key", "expected_version"}`. `WAITING_FOR_OPERATION`이고 마지막 Operation이 성공했을 때만 됩니다. 202 뒤 `FINALIZING` → `SUCCEEDED`(또는 후처리 실패 시 `FAILED / COMPLETION_FAILED`). 최종 리포트를 만들어 주는 API가 아니라 Execution을 닫는 명령입니다.

### 5.8 `POST /executions/{execution_id}/cancel`, `/retry`

- cancel: `{"idempotency_key", "reason"?}`(사유 2000자 이하). 이미 `CANCEL_REQUESTED`면 현재 상태를 그대로 돌려주고, 끝난 실행은 409입니다. 확정되면 실행 중이던 Step은 `CANCELLED`, 시작 전 Step은 `SKIPPED`입니다.
- retry: `{"idempotency_key"}`. 조건은 3.3. 시작 Step은 상태 조회의 `retry.from_sequence`로 확인합니다. 조건이 안 맞으면 409입니다.

### 5.9 노트북: 셀 코드와 출력 원문

| 경로 | 설명 |
| --- | --- |
| `GET /executions/{id}/notebook?view=SUMMARY&start_index=0&limit=20` | 셀 목록. `SUMMARY`(기본)는 코드 미리보기와 출력 요약만 |
| `GET /executions/{id}/notebook?view=FULL` | 페이지 안 셀의 **코드 전체와 출력 전체**(`outputs[]`, Jupyter 출력 형식: `stream`, `execute_result`, `display_data`, `error`) |
| `GET /executions/{id}/notebook/cells/{cell_index}` | 셀 하나, 항상 전체 |

- `limit`은 1~200(기본 20)입니다. 응답의 `page`(`start_index`, `limit`, `total_count`, `has_more`)로 다음 페이지를 압니다.
- 출력 원문을 읽는 방법은 이것뿐입니다. 이미지는 `display_data.data["image/png"]`(base64)로 옵니다.
- 노트북은 실행 중·실패 후에도 읽을 수 있습니다. 최신 출력이 반영됐는지는 상태 조회의 `workspace.notebook_projection.status`로 봅니다.

### 5.10 이벤트 이력

`GET /executions/{id}/events?after_sequence=&cursor=&limit=`(limit 1~500, 기본 200). `event_sequence` 오름차순입니다. [ExecutionEventResponse](#schema-executioneventresponse)의 `event_type`:

| event_type | 언제 |
| --- | --- |
| `execution.started` | 런타임을 준비하고 처음 실행을 시작할 때 한 번(재시도에서는 다시 오지 않음). `payload.runtime`은 `{provider, profile, target_id, kernel_id}`입니다. 런타임 준비 전에 실패하면 이 이벤트 없이 `execution.completed`가 옵니다 |
| `execution.operation_started` | Operation 시작 |
| `execution.step_started` / `execution.step_completed` | Step 시작 / 끝 (시도마다) |
| `execution.step_handover_started` / `…_completed` | 실행 중 Step의 담당 서버가 바뀜 |
| `execution.operation_completed` | Operation 끝. `payload.status`, `payload.execution_status`(MULTI는 `WAITING_FOR_OPERATION`) |
| `execution.completed` | Execution 끝. **성공뿐 아니라 실패·취소도** 이 이벤트입니다. `payload.status`를 봅니다 |

이벤트는 깨우는 신호로만 쓰고, 최종 판단은 상태 조회로 합니다.

### 5.11 아티팩트

| 경로 | 설명 |
| --- | --- |
| `GET /executions/{id}/artifacts` | 그 실행의 아티팩트 목록 (limit 1~1000, 기본 100) |
| `GET /artifacts/{artifact_id}` | 아티팩트 하나: `name`, `type`(`NOTEBOOK`·`REPORT`·`PLOT`·`DATASET`·`MODEL`·`METRIC`·`LOG`·`OTHER`), `status`, `storage`, `produced_by`, `lineage`, `metadata` |
| `GET /artifacts/{artifact_id}/content` | **파일 내용**. `Content-Type`은 파일 종류, `Content-Disposition`에 파일 이름, `ETag`는 내용의 SHA-256 |
| `POST /executions/{id}/artifacts` | 호출자가 쓴 텍스트(리포트 등)를 그 실행의 아티팩트로 저장 |

- 파일은 받을 때의 **현재 전체 내용**입니다. 게이트웨이는 `Range`를 넘기지 않으므로 항상 200 전체입니다.
- 실행 노트북(`NOTEBOOK`, `notebooks/execution.ipynb`)은 실행 중에도 받을 수 있지만, `AVAILABLE`이 분석 성공을 뜻하지는 않습니다.
- `POST /executions/{id}/artifacts` 본문 [ExecutionArtifactMaterializeRequest](#schema-executionartifactmaterializerequest): `idempotency_key`, `type`(`REPORT`·`NOTEBOOK`·`PLOT`·`METRIC`·`LOG`·`OTHER`, `DATASET`·`MODEL`은 안 됨), `source`(`{"type": "INLINE", "content": "<UTF-8 텍스트>"}`), `name`?, `description`?, `media_type`?, `append_to_notebook`?(true면 Markdown 셀로 노트북 끝에 붙임), `metadata`?. **성공한(`SUCCEEDED`) 실행에만** 됩니다. 응답 201 [ExecutionArtifactResponse](#schema-executionartifactresponse).

## 6. 결과를 읽는 순서 (권장)

1. `GET /executions/{id}`로 끝났는지와 `failure`를 봅니다.
2. `GET /executions/{id}/result`로 Step별 `status`, `error_message`, `output_summary`를 봅니다. 여기까지는 응답이 작습니다.
3. 출력 원문이 필요할 때만 `GET /executions/{id}/notebook?view=FULL`(또는 `/cells/{n}`)을 읽습니다. 셀 번호는 노트북 순서이고 Step `sequence`와 같지 않을 수 있으니, `SUMMARY`로 먼저 셀을 찾습니다.
4. 파일은 `/artifacts` 목록에서 찾아 `/artifacts/{artifact_id}/content`로 받습니다.

## 7. 오류 코드

게이트웨이 오류(400·401·403·404·413·502·504)는 [00-common 6.1](00-common.md#61-우리게이트웨이가-내는-오류)입니다. executor가 내는 주요 코드는 이렇습니다.

| HTTP | code | 뜻 | 대처 |
| --- | --- | --- | --- |
| 404 | `EXECUTION_NOT_FOUND`, `ARTIFACT_NOT_FOUND` 등 `*_NOT_FOUND` | 없거나, 다른 tenant·(일반키) 다른 사용자 것 | ID 확인 |
| 409 | `EXECUTION_VERSION_CONFLICT` | `expected_version`이 현재와 다름 | 상태를 다시 읽고 판단 |
| 409 | `INVALID_STATE_TRANSITION` | 지금 상태에서 할 수 없음 (끝난 실행 취소, 대기 중이 아닌데 추가 등) | 상태 확인 |
| 409 | `IDEMPOTENCY_CONFLICT` | 같은 멱등키에 다른 본문 | 새 작업은 새 키 |
| 413 | `REQUEST_BODY_TOO_LARGE` | 본문 30MB 초과 | 코드 줄이기 |
| 422 | `REQUEST_VALIDATION_ERROR` | 필수 값 누락, 타입·길이·패턴 오류, 모르는 필드 | `details`대로 고치기 |
| 422 | `INVALID_EXECUTION_SPEC` | 규칙 위반: Step 수·크기·시간 한도, `sequence` 순서, SINGLE·MULTI 규칙 | `details[].type`·`context`대로 고치기 |
| 500 | `INTERNAL_ERROR` | executor 내부 오류 | 담당자에게 `X-Request-ID`와 함께 문의 |
| 503 | `DATABASE_UNAVAILABLE` | executor DB 일시 장애 | 같은 멱등키로 잠시 뒤 |

`INVALID_EXECUTION_SPEC`의 `details[].type`: `too_many_steps`, `execution_step_limit_exceeded`, `inline_source_too_large`, `source_blank`, `steps_empty`, `sequence_not_contiguous`, `first_sequence_not_zero`, `unsupported_schema_version`, `exceeds_max_runtime`, `not_allowed_for_single`, `required_for_multi`, `multi_requires_interactive`, `session_without_project`, `reserved_value` 등.

## 8. API key로 부를 수 없는 경로

아래는 executor에 있지만 우리 관리자 화면(SSO 로그인, 관리자 역할)에서만 쓰는 경로입니다. key로 부르면 404입니다.

| 구분 | 경로 (`/api/v1/executor` 뒤) |
| --- | --- |
| 재시도·진단 이력 | `GET /executions/{id}/attempts`, `/attempts/{attempt_id}`, `/attempts/{attempt_id}/steps`, `/diagnostics` |
| 런타임 서버 | `GET·POST /runtime-targets`, `GET /runtime-targets/{id}`, `POST /runtime-targets/{id}/probe`·`/drain`·`/activate`·`/disable`, `DELETE /runtime-targets/{id}`(등록 삭제), `GET /runtime-pools` |
| 점검 | `GET /maintenance`, `POST /maintenance/drain`·`/activate`·`/runs`, `GET /maintenance/runs/{id}`, `/maintenance/runs/{id}/targets` |

브라우저(SSO)로 부를 때는 조회만 열려 있고(실행 목록·상세·결과·노트북 등, 프로젝트 멤버만), 쓰기와 `/artifacts/*`는 key 호출자만 씁니다.

## 9. 알려진 제약

- **이벤트 스트림 없음:** 실시간 이벤트(Redis)는 중계하지 않습니다. 상태 조회나 `/events`로 폴링합니다(3.4).
- **Step 결과 파일(`result_ref`)은 열 수 없음:** 노트북 API로 출력을 읽습니다(5.9).
- **`Range` 미지원:** 파일은 항상 전체로 받습니다.
- **`Location`은 executor 기준 경로:** `/api/v1/` → `/api/v1/executor/`로 바꿔 씁니다.
- **`PATH` source:** 외부 호출자는 executor 입력 저장소에 쓸 수 없으므로 `INLINE`만 씁니다.

## 10. 레퍼런스: 경로별 파라미터와 응답

`X-Api-Key`, `X-User-Id`(필수), `X-Project-Id`, `X-Session-Id`(선택)는 모든 경로에 공통이라 표에서 뺐습니다. 모든 경로는 00-common 6.1의 게이트웨이 오류와 422(요청 형식 오류)를 낼 수 있습니다. 쿼리 `user_id`는 목록 조회에만 적었습니다(00-common 4.2 규칙).

<!-- gen:begin endpoints -->
#### `GET /api/v1/executor/executions`

List execution history

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| query | `user_id` | string \| null |  |  | `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` | Reads only. Master key: narrows the tenant-wide read to this user. Standard key: may only repeat X-User-Id (anything else is 403). |
| query | `project_id` | string \| null |  |  | `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$` |  |
| query | `session_id` | string \| null |  |  | `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$` |  |
| query | `trigger_type` | [TriggerType](#schema-triggertype) \| null |  |  |  |  |
| query | `status` | [ExecutionStatus](#schema-executionstatus) \| null |  |  |  |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 2048 |  |
| query | `limit` | integer |  | `100` | ≥ 1, ≤ 200 |  |

- 응답 `200` (`application/json`): [ExecutionPageResponse](#schema-executionpageresponse)

#### `POST /api/v1/executor/executions`

Submit an asynchronous execution

- 요청 본문 (`application/json`): [ExecutionSubmitRequest](#schema-executionsubmitrequest)
- 응답 `202` (`application/json`): [ExecutionCommandResponse](#schema-executioncommandresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}`

Get current execution state

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [ExecutionResponse](#schema-executionresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/result`

Get the consolidated execution result for Agent reporting

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [ExecutionResultResponse](#schema-executionresultresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/steps`

List current execution Steps

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 2048 |  |
| query | `limit` | integer |  | `100` | ≥ 1, ≤ 200 |  |

- 응답 `200` (`application/json`): [ExecutionStepPageResponse](#schema-executionsteppageresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/steps/{step_id}`

Get one current execution Step

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| path | `step_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [ExecutionStepResponse](#schema-executionstepresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/operations`

List Agent-submitted execution Operations

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 2048 |  |
| query | `limit` | integer |  | `100` | ≥ 1, ≤ 200 |  |

- 응답 `200` (`application/json`): [ExecutionOperationPageResponse](#schema-executionoperationpageresponse)
- 이 경로의 그 밖의 오류: `409`

#### `POST /api/v1/executor/executions/{execution_id}/operations`

Append the next Operation to a MULTI execution

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |

- 요청 본문 (`application/json`): [ExecutionOperationCreateRequest](#schema-executionoperationcreaterequest)
- 응답 `202` (`application/json`): [ExecutionCommandResponse](#schema-executioncommandresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/operations/{operation_id}`

Get one execution Operation detail

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| path | `operation_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [ExecutionOperationResponse](#schema-executionoperationresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/operations/{operation_id}/result`

Get one Operation and all of its Step results

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| path | `operation_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [ExecutionOperationResultResponse](#schema-executionoperationresultresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/operations/{operation_id}/steps`

List current Step results for one Operation

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| path | `operation_id` | string (uuid) | O |  |  |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 2048 |  |
| query | `limit` | integer |  | `100` | ≥ 1, ≤ 200 |  |

- 응답 `200` (`application/json`): [ExecutionStepPageResponse](#schema-executionsteppageresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/events`

List the durable Execution event timeline

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| query | `after_sequence` | integer |  | `0` | ≥ 0 |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 2048 |  |
| query | `limit` | integer |  | `200` | ≥ 1, ≤ 500 |  |

- 응답 `200` (`application/json`): [ExecutionEventPageResponse](#schema-executioneventpageresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/artifacts`

List execution Artifacts

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 2048 |  |
| query | `limit` | integer |  | `100` | ≥ 1, ≤ 1000 |  |

- 응답 `200` (`application/json`): [ExecutionArtifactPageResponse](#schema-executionartifactpageresponse)
- 이 경로의 그 밖의 오류: `409`

#### `POST /api/v1/executor/executions/{execution_id}/artifacts`

Materialize Agent-authored text as a Runtime-owned Artifact

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |

- 요청 본문 (`application/json`): [ExecutionArtifactMaterializeRequest](#schema-executionartifactmaterializerequest)
- 응답 `201` (`application/json`): [ExecutionArtifactResponse](#schema-executionartifactresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/notebook`

Read Runtime-owned execution notebook cells

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| query | `view` | "SUMMARY" \| "FULL" |  | `"SUMMARY"` |  |  |
| query | `start_index` | integer |  | `0` | ≥ 0 |  |
| query | `limit` | integer |  | `20` | ≥ 1, ≤ 200 |  |

- 응답 `200` (`application/json`): [ExecutionNotebookResponse](#schema-executionnotebookresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/executions/{execution_id}/notebook/cells/{cell_index}`

Read one Runtime-owned execution notebook cell

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |
| path | `cell_index` | integer | O |  | ≥ 0 |  |

- 응답 `200` (`application/json`): [ExecutionNotebookCellResponse](#schema-executionnotebookcellresponse)
- 이 경로의 그 밖의 오류: `409`

#### `POST /api/v1/executor/executions/{execution_id}/finalize`

Finalize a waiting MULTI execution

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |

- 요청 본문 (`application/json`): [ExecutionFinalizeRequest](#schema-executionfinalizerequest)
- 응답 `202` (`application/json`): [ExecutionCommandResponse](#schema-executioncommandresponse)
- 이 경로의 그 밖의 오류: `409`

#### `POST /api/v1/executor/executions/{execution_id}/cancel`

Request asynchronous cancellation

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |

- 요청 본문 (`application/json`): [ExecutionCancelRequest](#schema-executioncancelrequest)
- 응답 `202` (`application/json`): [ExecutionCommandResponse](#schema-executioncommandresponse)
- 이 경로의 그 밖의 오류: `409`

#### `POST /api/v1/executor/executions/{execution_id}/retry`

Retry a failed execution

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `execution_id` | string (uuid) | O |  |  |  |

- 요청 본문 (`application/json`): [ExecutionRetryRequest](#schema-executionretryrequest)
- 응답 `202` (`application/json`): [ExecutionCommandResponse](#schema-executioncommandresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/artifacts/{artifact_id}`

Get one execution Artifact and lineage references

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `artifact_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [ExecutionArtifactResponse](#schema-executionartifactresponse)
- 이 경로의 그 밖의 오류: `409`

#### `GET /api/v1/executor/artifacts/{artifact_id}/content`

Stream registered Artifact content

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `artifact_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/octet-stream`): string (binary)
- 이 경로의 그 밖의 오류: `409`
<!-- gen:end endpoints -->

## 11. 스키마

executor OpenAPI에서 만든 표입니다. 필드 설명은 executor 원문(영문)이고, 뜻은 5장에 한국어로 적었습니다.

<!-- gen:begin schemas -->
<a id="schema-artifactlineage"></a>
#### ArtifactLineage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `parent_artifact_id` | string (uuid) \| null | O |  |  |  |
| `external_parent_asset_id` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-artifactproducer"></a>
#### ArtifactProducer

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `execution_id` | string (uuid) | O |  |  |  |
| `execution_attempt_id` | string (uuid) \| null | O |  |  |  |
| `execution_step_id` | string (uuid) \| null | O |  |  |  |
| `execution_step_attempt_id` | string (uuid) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-artifactstatus"></a>
#### ArtifactStatus

값: `AVAILABLE`, `INCOMPLETE`, `DELETED`

<a id="schema-artifactstorage"></a>
#### ArtifactStorage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | [ArtifactStorageType](#schema-artifactstoragetype) | O |  |  |  |
| `uri` | string | O |  |  |  |
| `relative_path` | string \| null | O |  |  |  |
| `media_type` | string \| null | O |  |  |  |
| `size_bytes` | integer \| null | O |  |  |  |
| `checksum_sha256` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-artifactstoragesummary"></a>
#### ArtifactStorageSummary

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | [ArtifactStorageType](#schema-artifactstoragetype) | O |  |  |  |
| `media_type` | string \| null | O |  |  |  |
| `size_bytes` | integer \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-artifactstoragetype"></a>
#### ArtifactStorageType

값: `PV`, `S3`

<a id="schema-artifacttype"></a>
#### ArtifactType

값: `DATASET`, `NOTEBOOK`, `REPORT`, `PLOT`, `MODEL`, `METRIC`, `LOG`, `OTHER`

<a id="schema-attemptstate"></a>
#### AttemptState

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | [AttemptStatus](#schema-attemptstatus) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-attemptstatus"></a>
#### AttemptStatus

값: `RUNNING`, `WAITING`, `SUCCEEDED`, `FAILED`, `CANCELLED`

<a id="schema-codesourcetype"></a>
#### CodeSourceType

값: `INLINE`, `PATH`

<a id="schema-deadlinesresponse"></a>
#### DeadlinesResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `operation_wait_expires_at` | string (date-time) \| null | O |  |  |  |
| `execution_expires_at` | string (date-time) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-eventdelivery"></a>
#### EventDelivery

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | [OutboxStatus](#schema-outboxstatus) | O |  |  |  |
| `attempt_count` | integer | O |  |  |  |
| `available_at` | string (date-time) | O |  |  |  |
| `published_at` | string (date-time) \| null | O |  |  |  |
| `last_error` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionartifactmaterializerequest"></a>
#### ExecutionArtifactMaterializeRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `idempotency_key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255 |  |
| `type` | "NOTEBOOK" \| "REPORT" \| "PLOT" \| "METRIC" \| "LOG" \| "OTHER" | O |  |  |  |
| `source` | [InlineArtifactSource](#schema-inlineartifactsource) \| [PathArtifactSource](#schema-pathartifactsource) | O |  |  | 구분 필드 `type`. |
| `name` | string \| null |  |  | 길이 ≥ 1, 길이 ≤ 255 |  |
| `description` | string \| null |  |  | 길이 ≤ 4000 |  |
| `media_type` | string \| null |  |  | 길이 ≥ 1, 길이 ≤ 255 |  |
| `append_to_notebook` | boolean |  | `false` |  |  |
| `metadata` | object |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionartifactpageresponse"></a>
#### ExecutionArtifactPageResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `next_cursor` | string \| null | O |  |  |  |
| `has_more` | boolean | O |  |  |  |
| `items` | [ExecutionArtifactSummaryResponse](#schema-executionartifactsummaryresponse)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionartifactresponse"></a>
#### ExecutionArtifactResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `artifact_id` | string (uuid) | O |  |  |  |
| `name` | string | O |  |  |  |
| `description` | string \| null | O |  |  |  |
| `type` | [ArtifactType](#schema-artifacttype) | O |  |  |  |
| `status` | [ArtifactStatus](#schema-artifactstatus) | O |  |  |  |
| `produced_by` | [ArtifactProducer](#schema-artifactproducer) | O |  |  |  |
| `lineage` | [ArtifactLineage](#schema-artifactlineage) | O |  |  |  |
| `storage` | [ArtifactStorage](#schema-artifactstorage) | O |  |  |  |
| `metadata` | object | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionartifactsummaryresponse"></a>
#### ExecutionArtifactSummaryResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `artifact_id` | string (uuid) | O |  |  |  |
| `name` | string | O |  |  |  |
| `type` | [ArtifactType](#schema-artifacttype) | O |  |  |  |
| `status` | [ArtifactStatus](#schema-artifactstatus) | O |  |  |  |
| `produced_by` | [ArtifactProducer](#schema-artifactproducer) | O |  |  |  |
| `storage` | [ArtifactStorageSummary](#schema-artifactstoragesummary) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionattemptresponse"></a>
#### ExecutionAttemptResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `attempt_id` | string (uuid) | O |  |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `attempt_number` | integer | O |  |  |  |
| `state` | [AttemptState](#schema-attemptstate) | O |  |  |  |
| `failure` | [FailureResponse](#schema-failureresponse) \| null | O |  |  |  |
| `lifecycle` | [Lifecycle](#schema-lifecycle) | O |  |  |  |
| `step_count` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executioncancelrequest"></a>
#### ExecutionCancelRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `idempotency_key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255 |  |
| `reason` | string \| null |  |  | 길이 ≤ 2000 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executioncommandresponse"></a>
#### ExecutionCommandResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `operation` | [ExecutionOperationReceipt](#schema-executionoperationreceipt) \| null | O |  |  |  |
| `state` | [ExecutionCommandState](#schema-executioncommandstate) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executioncommandstate"></a>
#### ExecutionCommandState

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | [ExecutionStatus](#schema-executionstatus) | O |  |  |  |
| `version` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executioncontext"></a>
#### ExecutionContext

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | O |  |  |  |
| `project_id` | string \| null | O |  |  |  |
| `session_id` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executioneventpageresponse"></a>
#### ExecutionEventPageResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `next_cursor` | string \| null | O |  |  |  |
| `has_more` | boolean | O |  |  |  |
| `items` | [ExecutionEventResponse](#schema-executioneventresponse)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executioneventresponse"></a>
#### ExecutionEventResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `event_id` | string (uuid) | O |  |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `event_sequence` | integer | O |  |  |  |
| `schema_version` | string | O |  |  |  |
| `event_type` | string | O |  |  |  |
| `payload` | object | O |  |  |  |
| `occurred_at` | string (date-time) | O |  |  |  |
| `delivery` | [EventDelivery](#schema-eventdelivery) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionfinalizerequest"></a>
#### ExecutionFinalizeRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `idempotency_key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255 |  |
| `expected_version` | integer | O |  | ≥ 0 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionlifecycleinput"></a>
#### ExecutionLifecycleInput

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `operation_mode` | [OperationMode](#schema-operationmode) | O |  |  |  |
| `operation_wait_timeout_seconds` | integer \| null |  |  | ≥ 30 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionlifecycleresponse"></a>
#### ExecutionLifecycleResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `operation_mode` | [OperationMode](#schema-operationmode) | O |  |  |  |
| `operation_wait_timeout_seconds` | integer \| null | O |  |  |  |
| `started_at` | string (date-time) \| null | O |  |  |  |
| `finished_at` | string (date-time) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionnotebookcellresponse"></a>
#### ExecutionNotebookCellResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `execution_id` | string (uuid) | O |  |  |  |
| `cell` | [NotebookCellResponse](#schema-notebookcellresponse) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionnotebookresponse"></a>
#### ExecutionNotebookResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `execution_id` | string (uuid) | O |  |  |  |
| `view` | "SUMMARY" \| "FULL" | O |  |  |  |
| `metadata` | object | O |  |  |  |
| `cells` | [NotebookCellSummaryResponse](#schema-notebookcellsummaryresponse) \| [NotebookCellResponse](#schema-notebookcellresponse)[] | O |  |  |  |
| `page` | [NotebookPage](#schema-notebookpage) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionoperationcreaterequest"></a>
#### ExecutionOperationCreateRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `idempotency_key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255 |  |
| `expected_version` | integer | O |  | ≥ 0 |  |
| `operation_timeout_seconds` | integer \| null |  |  | ≥ 1 |  |
| `spec` | [ExecutionSpec](#schema-executionspec) | O |  |  |  |
| `metadata` | object |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionoperationinput"></a>
#### ExecutionOperationInput

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `operation_timeout_seconds` | integer \| null |  |  | ≥ 1 |  |
| `spec` | [ExecutionSpec](#schema-executionspec) | O |  |  |  |
| `metadata` | object |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionoperationpageresponse"></a>
#### ExecutionOperationPageResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `next_cursor` | string \| null | O |  |  |  |
| `has_more` | boolean | O |  |  |  |
| `items` | [ExecutionOperationSummaryResponse](#schema-executionoperationsummaryresponse)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionoperationreceipt"></a>
#### ExecutionOperationReceipt

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `operation_id` | string (uuid) | O |  |  |  |
| `steps` | [ExecutionStepReceipt](#schema-executionstepreceipt)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionoperationresponse"></a>
#### ExecutionOperationResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `operation_id` | string (uuid) | O |  |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `operation_number` | integer | O |  |  |  |
| `schema_version` | string | O |  |  |  |
| `sequence_range` | [OperationSequenceRange](#schema-operationsequencerange) | O |  |  |  |
| `operation_timeout_seconds` | integer \| null | O |  |  |  |
| `metadata` | object | O |  |  |  |
| `execution_attempt_id` | string (uuid) \| null | O |  |  |  |
| `result` | [OperationResult](#schema-operationresult) | O |  |  |  |
| `lifecycle` | [Lifecycle](#schema-lifecycle) | O |  |  |  |
| `step_count` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionoperationresultresponse"></a>
#### ExecutionOperationResultResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `execution` | [ExecutionResultExecutionResponse](#schema-executionresultexecutionresponse) | O |  |  |  |
| `operation` | [ExecutionResultOperationResponse](#schema-executionresultoperationresponse) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionoperationsummaryresponse"></a>
#### ExecutionOperationSummaryResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `operation_id` | string (uuid) | O |  |  |  |
| `operation_number` | integer | O |  |  |  |
| `sequence_range` | [OperationSequenceRange](#schema-operationsequencerange) | O |  |  |  |
| `result` | [OperationResult](#schema-operationresult) | O |  |  |  |
| `lifecycle` | [Lifecycle](#schema-lifecycle) | O |  |  |  |
| `step_count` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionpageresponse"></a>
#### ExecutionPageResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `next_cursor` | string \| null | O |  |  |  |
| `has_more` | boolean | O |  |  |  |
| `items` | [ExecutionSummaryResponse](#schema-executionsummaryresponse)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionresponse"></a>
#### ExecutionResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `trigger_type` | [TriggerType](#schema-triggertype) | O |  |  |  |
| `trigger` | [ExecutionTrigger](#schema-executiontrigger) | O |  |  |  |
| `tenant_id` | string | O |  |  |  |
| `context` | [ExecutionContext](#schema-executioncontext) | O |  |  |  |
| `metadata` | object | O |  |  |  |
| `runtime` | [ExecutionRuntime](#schema-executionruntime) | O |  |  |  |
| `state` | [ExecutionState](#schema-executionstate) | O |  |  |  |
| `workspace` | [WorkspaceResponse](#schema-workspaceresponse) | O |  |  |  |
| `failure` | [FailureResponse](#schema-failureresponse) \| null | O |  |  |  |
| `retry` | [RetryResponse](#schema-retryresponse) | O |  |  |  |
| `recovery` | [RecoveryResponse](#schema-recoveryresponse) | O |  |  |  |
| `deadlines` | [DeadlinesResponse](#schema-deadlinesresponse) | O |  |  |  |
| `lifecycle` | [ExecutionLifecycleResponse](#schema-executionlifecycleresponse) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionresultexecutionresponse"></a>
#### ExecutionResultExecutionResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `execution_id` | string (uuid) | O |  |  |  |
| `state` | [ExecutionCommandState](#schema-executioncommandstate) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionresultoperationresponse"></a>
#### ExecutionResultOperationResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `operation_id` | string (uuid) | O |  |  |  |
| `operation_number` | integer | O |  |  |  |
| `sequence_range` | [OperationSequenceRange](#schema-operationsequencerange) | O |  |  |  |
| `result` | [OperationResult](#schema-operationresult) | O |  |  |  |
| `lifecycle` | [Lifecycle](#schema-lifecycle) | O |  |  |  |
| `steps` | [ExecutionResultStepResponse](#schema-executionresultstepresponse)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionresultresponse"></a>
#### ExecutionResultResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `execution` | [ExecutionResultExecutionResponse](#schema-executionresultexecutionresponse) | O |  |  |  |
| `operations` | [ExecutionResultOperationResponse](#schema-executionresultoperationresponse)[] | O |  |  |  |
| `attempts` | [ExecutionAttemptResponse](#schema-executionattemptresponse)[] | O |  |  |  |
| `artifacts` | [ExecutionArtifactSummaryResponse](#schema-executionartifactsummaryresponse)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionresultstepresponse"></a>
#### ExecutionResultStepResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `step_id` | string (uuid) | O |  |  |  |
| `sequence` | integer | O |  |  |  |
| `lineage` | [ToolReference](#schema-toolreference) | O |  |  |  |
| `result` | [StepResult](#schema-stepresult) | O |  |  |  |
| `lifecycle` | [Lifecycle](#schema-lifecycle) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionretryrequest"></a>
#### ExecutionRetryRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `idempotency_key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionruntime"></a>
#### ExecutionRuntime

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | [RuntimeType](#schema-runtimetype) | O |  |  |  |
| `pool` | [RuntimePool](#schema-runtimepool) | O |  |  |  |
| `profile` | string | O |  |  |  |
| `target_id` | string (uuid) \| null | O |  |  |  |
| `kernel_id` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionruntimeinput"></a>
#### ExecutionRuntimeInput

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | [RuntimeType](#schema-runtimetype) | O |  |  |  |
| `profile` | string | O |  | 길이 ≥ 1, 길이 ≤ 128 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionspec"></a>
#### ExecutionSpec

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `schema_version` | "1.0" | O |  |  |  |
| `steps` | [ExecutionStepInput](#schema-executionstepinput)[] | O |  | 항목 ≥ 1 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionstate"></a>
#### ExecutionState

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | [ExecutionStatus](#schema-executionstatus) | O |  |  |  |
| `version` | integer | O |  |  |  |
| `cancellation_reason` | string \| null | O |  |  |  |
| `finalized_by` | [FinalizedBy](#schema-finalizedby) \| null |  |  |  | What ended the Execution: AGENT (finalize call), WAIT_TIMEOUT (no next MULTI Operation before the wait deadline) or MAX_RUNTIME (EXECUTION_MAX_RUNTIME_SECONDS reached). Null while open, for a SINGLE Execution that ended normally, and for cancellation. |

모르는 필드는 422로 거절합니다.

<a id="schema-executionstatus"></a>
#### ExecutionStatus

값: `QUEUED`, `RUNNING`, `WAITING_FOR_OPERATION`, `FINALIZING`, `CANCEL_REQUESTED`, `CANCELLED`, `SUCCEEDED`, `FAILED`

<a id="schema-executionstepinput"></a>
#### ExecutionStepInput

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `sequence` | integer | O |  | ≥ 0 |  |
| `payload` | [PythonExecutePayload](#schema-pythonexecutepayload) | O |  |  | 구분 필드 `type`. |
| `step_timeout_seconds` | integer \| null |  |  | ≥ 1 |  |
| `lineage` | [StepLineage](#schema-steplineage) \| null |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionsteppageresponse"></a>
#### ExecutionStepPageResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `next_cursor` | string \| null | O |  |  |  |
| `has_more` | boolean | O |  |  |  |
| `items` | [ExecutionStepSummaryResponse](#schema-executionstepsummaryresponse)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionstepreceipt"></a>
#### ExecutionStepReceipt

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `sequence` | integer | O |  |  |  |
| `step_id` | string (uuid) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionstepresponse"></a>
#### ExecutionStepResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `step_id` | string (uuid) | O |  |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `sequence` | integer | O |  |  |  |
| `code_hash` | string \| null | O |  |  |  |
| `source` | [StepSourceResponse](#schema-stepsourceresponse) | O |  |  |  |
| `step_timeout_seconds` | integer \| null | O |  |  |  |
| `lineage` | [ToolReference](#schema-toolreference) | O |  |  |  |
| `result` | [StepResult](#schema-stepresult) | O |  |  |  |
| `lifecycle` | [Lifecycle](#schema-lifecycle) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionstepsummaryresponse"></a>
#### ExecutionStepSummaryResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `step_id` | string (uuid) | O |  |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `sequence` | integer | O |  |  |  |
| `lineage` | [ToolReference](#schema-toolreference) | O |  |  |  |
| `result` | [StepResultSummary](#schema-stepresultsummary) | O |  |  |  |
| `lifecycle` | [Lifecycle](#schema-lifecycle) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executionsubmitrequest"></a>
#### ExecutionSubmitRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `idempotency_key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255 |  |
| `lifecycle` | [ExecutionLifecycleInput](#schema-executionlifecycleinput) | O |  |  |  |
| `trigger` | [ExecutionTriggerInput](#schema-executiontriggerinput) | O |  |  |  |
| `runtime` | [ExecutionRuntimeInput](#schema-executionruntimeinput) | O |  |  |  |
| `operation` | [ExecutionOperationInput](#schema-executionoperationinput) | O |  |  |  |
| `metadata` | object |  |  |  | Caller-owned identifiers such as batch or run IDs, stored as given and echoed in execution.completed. At most 32 keys matching ^[a-z][a-z0-9_]{0,63}$, 4096 serialized bytes. |

모르는 필드는 422로 거절합니다.

<a id="schema-executionsummaryresponse"></a>
#### ExecutionSummaryResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_by_client` | string \| null | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `operation_mode` | [OperationMode](#schema-operationmode) | O |  |  |  |
| `trigger_type` | [TriggerType](#schema-triggertype) | O |  |  |  |
| `trigger` | [ExecutionTrigger](#schema-executiontrigger) | O |  |  |  |
| `tenant_id` | string | O |  |  |  |
| `context` | [ExecutionContext](#schema-executioncontext) | O |  |  |  |
| `metadata` | object | O |  |  |  |
| `state` | [ExecutionCommandState](#schema-executioncommandstate) | O |  |  |  |
| `lifecycle` | [Lifecycle](#schema-lifecycle) | O |  |  |  |
| `step_count` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executiontrigger"></a>
#### ExecutionTrigger

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | [TriggerType](#schema-triggertype) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executiontriggerinput"></a>
#### ExecutionTriggerInput

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | [TriggerType](#schema-triggertype) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-failureresponse"></a>
#### FailureResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | [FailureType](#schema-failuretype) | O |  |  |  |
| `message` | string | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-failuretype"></a>
#### FailureType

값: `TOOL_ERROR`, `INFRASTRUCTURE_ERROR`, `WORKER_SHUTDOWN`, `RUNTIME_UNAVAILABLE`, `LEASE_EXPIRED`, `INTERNAL_ERROR`, `OPERATION_WAIT_TIMEOUT`, `OPERATION_TIMEOUT`, `STEP_TIMEOUT`, `EXECUTION_TIMEOUT`, `QUEUE_TIMEOUT`, `OUTPUT_LIMIT_EXCEEDED`, `RUNTIME_SESSION_LOST`, `COMPLETION_FAILED`

<a id="schema-finalizedby"></a>
#### FinalizedBy

What ended a MULTI Execution, or any Execution past its lifetime.

값: `AGENT`, `WAIT_TIMEOUT`, `MAX_RUNTIME`

<a id="schema-inlineartifactsource"></a>
#### InlineArtifactSource

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | "INLINE" | O |  |  |  |
| `content` | string | O |  | 길이 ≥ 1 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-inlinestepsource"></a>
#### InlineStepSource

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | "INLINE" | O |  |  |  |
| `content` | string | O |  | 길이 ≥ 1 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-lifecycle"></a>
#### Lifecycle

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `started_at` | string (date-time) \| null | O |  |  |  |
| `finished_at` | string (date-time) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-notebookcellresponse"></a>
#### NotebookCellResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `index` | integer | O |  |  |  |
| `id` | string \| null | O |  |  |  |
| `type` | string | O |  |  |  |
| `execution_count` | integer \| null | O |  |  |  |
| `source` | string | O |  |  |  |
| `line_count` | integer | O |  |  |  |
| `metadata` | object | O |  |  |  |
| `output_summary` | [OutputSummary](#schema-outputsummary) | O |  |  |  |
| `outputs` | object[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-notebookcellsummaryresponse"></a>
#### NotebookCellSummaryResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `index` | integer | O |  |  |  |
| `id` | string \| null | O |  |  |  |
| `type` | string | O |  |  |  |
| `execution_count` | integer \| null | O |  |  |  |
| `source_preview` | string | O |  |  |  |
| `source_truncated` | boolean | O |  |  |  |
| `line_count` | integer | O |  |  |  |
| `metadata` | object | O |  |  |  |
| `output_summary` | [OutputSummary](#schema-outputsummary) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-notebookpage"></a>
#### NotebookPage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `start_index` | integer | O |  |  |  |
| `limit` | integer | O |  |  |  |
| `total_count` | integer | O |  |  |  |
| `has_more` | boolean | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-notebookprojectionresponse"></a>
#### NotebookProjectionResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | [NotebookProjectionStatus](#schema-notebookprojectionstatus) | O |  |  |  |
| `attempt_count` | integer | O |  |  |  |
| `error_message` | string \| null | O |  |  |  |
| `projected_at` | string (date-time) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-notebookprojectionstatus"></a>
#### NotebookProjectionStatus

값: `NOT_STARTED`, `PENDING`, `SUCCEEDED`, `FAILED`

<a id="schema-operationmode"></a>
#### OperationMode

값: `SINGLE`, `MULTI`

<a id="schema-operationresult"></a>
#### OperationResult

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | [OperationStatus](#schema-operationstatus) | O |  |  |  |
| `error_message` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-operationsequencerange"></a>
#### OperationSequenceRange

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `first` | integer | O |  |  |  |
| `last` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-operationstatus"></a>
#### OperationStatus

값: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`

<a id="schema-outboxstatus"></a>
#### OutboxStatus

값: `PENDING`, `PUBLISHED`

<a id="schema-outputsummary"></a>
#### OutputSummary

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `output_count` | integer | O |  | ≥ 0 |  |
| `output_types` | object<string, integer> | O |  |  |  |
| `stream_names` | string[] | O |  |  |  |
| `mime_types` | string[] | O |  |  |  |
| `has_image` | boolean | O |  |  |  |
| `image_count` | integer | O |  | ≥ 0 |  |
| `has_error` | boolean | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-pathartifactsource"></a>
#### PathArtifactSource

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | "PATH" | O |  |  |  |
| `path` | string | O |  | 길이 ≥ 1, 길이 ≤ 4096 | Input file path relative to STORAGE_ROOT; no prefix is added. |
| `sha256` | string | O |  | `^[0-9a-fA-F]{64}$` |  |

모르는 필드는 422로 거절합니다.

<a id="schema-pathstepsource"></a>
#### PathStepSource

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | "PATH" | O |  |  |  |
| `path` | string | O |  | 길이 ≥ 1, 길이 ≤ 4096 | Python file path relative to STORAGE_ROOT; no prefix is added. |
| `sha256` | string | O |  | `^[0-9a-fA-F]{64}$` |  |

모르는 필드는 422로 거절합니다.

<a id="schema-pythonexecutepayload"></a>
#### PythonExecutePayload

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | "PYTHON_EXECUTE" | O |  |  |  |
| `source` | [InlineStepSource](#schema-inlinestepsource) \| [PathStepSource](#schema-pathstepsource) | O |  |  | 구분 필드 `type`. |

모르는 필드는 422로 거절합니다.

<a id="schema-recoveryresponse"></a>
#### RecoveryResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `count` | integer | O |  |  |  |
| `runtime_session_cleanup_status` | [RuntimeSessionCleanupStatus](#schema-runtimesessioncleanupstatus) | O |  |  |  |
| `runtime_abort_status` | [RuntimeAbortStatus](#schema-runtimeabortstatus) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-retryresponse"></a>
#### RetryResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `strategy` | [RetryStrategy](#schema-retrystrategy) | O |  |  |  |
| `count` | integer | O |  |  |  |
| `from_sequence` | integer \| null | O |  |  |  |
| `retained_runtime_session_until` | string (date-time) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-retrystrategy"></a>
#### RetryStrategy

값: `NOT_RETRYABLE`, `FROM_FAILED_STEP`, `FROM_START`

<a id="schema-runtimeabortstatus"></a>
#### RuntimeAbortStatus

값: `NOT_REQUIRED`, `PENDING`, `IDLE_CONFIRMED`, `SESSION_DELETED`, `SESSION_MISSING`, `FAILED`

<a id="schema-runtimepool"></a>
#### RuntimePool

값: `INTERACTIVE`, `BATCH`

<a id="schema-runtimesessioncleanupstatus"></a>
#### RuntimeSessionCleanupStatus

값: `NOT_REQUIRED`, `PENDING`, `SUCCEEDED`, `FAILED`

<a id="schema-runtimetype"></a>
#### RuntimeType

값: `JUPYTER`

<a id="schema-steplineage"></a>
#### StepLineage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `skill_name` | string \| null |  |  | 길이 ≤ 255 |  |
| `tool_name` | string \| null |  |  | 길이 ≤ 255 |  |
| `input_parameters` | object |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-stepresult"></a>
#### StepResult

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | [StepStatus](#schema-stepstatus) | O |  |  |  |
| `output_summary` | [OutputSummary](#schema-outputsummary) | O |  |  |  |
| `error_message` | string \| null | O |  |  |  |
| `result_ref` | [StepResultReference](#schema-stepresultreference) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-stepresultreference"></a>
#### StepResultReference

Immutable Step result manifest in the Agent/Executor shared volume.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `storage` | "SHARED_PV" |  | `"SHARED_PV"` |  |  |
| `execution_id` | string (uuid) | O |  |  |  |
| `step_id` | string (uuid) | O |  |  |  |
| `attempt_id` | string (uuid) | O |  |  |  |
| `fencing_token` | integer | O |  |  |  |
| `relative_path` | string | O |  |  |  |
| `checksum_sha256` | string | O |  |  |  |
| `size_bytes` | integer | O |  |  |  |
| `complete` | boolean | O |  |  |  |
| `representation_count` | integer | O |  |  |  |
| `total_size_bytes` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-stepresultsummary"></a>
#### StepResultSummary

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | [StepStatus](#schema-stepstatus) | O |  |  |  |
| `output_summary` | [OutputSummary](#schema-outputsummary) | O |  |  |  |
| `error_message` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-stepsourceresponse"></a>
#### StepSourceResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | [CodeSourceType](#schema-codesourcetype) | O |  |  |  |
| `path` | string \| null | O |  |  |  |
| `sha256` | string | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-stepstatus"></a>
#### StepStatus

값: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`, `CANCELLED`

<a id="schema-toolreference"></a>
#### ToolReference

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `skill_name` | string \| null | O |  |  |  |
| `tool_name` | string \| null | O |  |  |  |
| `input_parameters` | object | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-triggertype"></a>
#### TriggerType

값: `INTERACTIVE`, `BATCH`

<a id="schema-workspaceresponse"></a>
#### WorkspaceResponse

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `path` | string \| null | O |  |  |  |
| `notebook_path` | string \| null | O |  |  |  |
| `notebook_projection` | [NotebookProjectionResponse](#schema-notebookprojectionresponse) | O |  |  |  |

모르는 필드는 422로 거절합니다.
<!-- gen:end schemas -->

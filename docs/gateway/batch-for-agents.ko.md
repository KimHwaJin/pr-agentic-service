# 배치 게이트웨이: 코딩 에이전트용 가이드

이 문서는 pr-agentic-service의 **배치 게이트웨이**로 Jupyter 노트북을 올리고, 예약(또는 수동)으로 실행하는 클라이언트를 만들 때 씁니다. 클라이언트를 만드는 데 이 파일 하나면 됩니다. 규칙을 먼저 읽고, 필드 계약은 끝의 TypeScript 타입(과 `openapi/batch-gateway.openapi.json`)을 그대로 따릅니다.

> 영문판 [batch-for-agents.md](batch-for-agents.md)와 내용이 같습니다. 코드, 경로, 필드 이름, 오류 코드는 번역하지 않았습니다.

- Base path:
  - `{BASE_URL}/api/v1/batch`는 pr-batch로 중계합니다(스크립트, 배치, 실행, 런타임).
  - `{BASE_URL}/api/v1/batch-reports`와 `{BASE_URL}/api/v1/batch/scripts/from-notebook`은 pr-agentic-service가 직접 처리하는 배치 경로입니다.
- `BASE_URL`은 쿠버네티스에 배포된 서비스 주소입니다. 클러스터 밖에서는 환경별 공개 주소 `https://<api-host>`, 클러스터 안에서는 `http://pr-agentic-service.<namespace>.svc.cluster.local`입니다. 설정(`AGENTIC_BASE_URL`)에서 읽고, 코드에 넣지 않습니다.
- 6장에 없는 경로는 `404 NOT_FOUND`입니다.
- 요청 본문과 성공 응답 본문은 pr-batch 것을 그대로 씁니다. 게이트웨이는 key와 사용자를 확인하고, 신원 헤더를 직접 만들고, 조회 범위를 정합니다.
- pr-batch는 노트북을 보관하고, 일정을 관리하고, 실행을 추적합니다. 코드는 executor에서 돌아갑니다. 실행 결과(실행된 노트북)는 같은 key로 **executor 게이트웨이**에서 받습니다(4.4).

## 1. 규칙

### MUST (반드시)

1. 모든 요청에 `X-Api-Key: <key>`를 보냅니다. 설정이나 환경 변수(예: `AGENTIC_API_KEY`)에서 읽습니다. 코드에 넣거나 로그에 남기지 않습니다.
2. 조회를 포함한 **모든** 요청에 `X-User-Id: <사번>`을 보냅니다. 소문자로, `^[a-z0-9][a-z0-9._-]{0,63}$` 형식입니다. 없거나 형식이 틀리면 `400 INVALID_IDENTITY`입니다. 모든 스크립트·배치·실행은 (key의 tenant, 이 사용자) 것입니다.
3. `/api/v1/batch/…`의 모든 POST, PATCH, DELETE에 `Idempotency-Key` **헤더**를 보냅니다(1~255자, ASCII, 공백 없음. UUID를 씁니다).
   - 논리적인 쓰기마다 첫 시도 전에 한 번 만듭니다.
   - 재시도 때는 같은 본문과 함께 다시 씁니다.
   - 예외: `scripts/from-notebook`과 `/batch-reports/…/retry`는 필요 없습니다.
4. 스크립트 이름 변경·삭제, 배치 수정·삭제·켜기·끄기에 `If-Match: <ETag>`를 보냅니다.
   - ETag는 상세 GET이나 직전 쓰기 응답에서 받습니다.
   - **따옴표까지 그대로** 보냅니다. 예: `If-Match: "3"`.
5. 배치의 `runtime`은 `GET /api/v1/batch/runtimes` 항목 하나를 그대로 씁니다.
6. 새 배치는 **꺼져 있습니다**. 일정을 시작하려면 `enable`을 부릅니다.
7. 실행 폴링은 5초 이상 간격으로 합니다. `COMPLETED`, `FAILED`, `CANCELLED`, `SKIPPED`에서 멈춥니다.
8. 분기는 `error.code`로 합니다. `error.message`로 하지 않습니다.
9. `next_cursor`는 그대로 `cursor`로 다시 넘깁니다. `next_cursor`가 `null`이면 멈춥니다.

### MUST NOT (하지 않음)

1. 모르는 필드를 보내지 않습니다. JSON 본문은 `422 VALIDATION_ERROR`로 거절합니다. 본문에 `tenant_id`, `user_id`, `owner_id`, `actor`를 넣지 않습니다. 소유자는 언제나 `X-User-Id`입니다.
2. `X-Tenant-Id`를 보내지 않습니다. key가 tenant를 정하므로 무시됩니다.
3. pr-batch나 executor를 직접 부르지 않습니다. 이 게이트웨이들만 씁니다.
4. 같은 `Idempotency-Key`를 다른 본문에 다시 쓰지 않습니다(`409 IDEMPOTENCY_CONFLICT`). `409 REVISION_CONFLICT` 뒤에도 다시 쓰지 않습니다. 새 ETag를 받고 **새** key를 씁니다.
5. ETag에서 따옴표를 빼지 않습니다(`422 INVALID_REVISION`).
6. PATCH에서 바뀌지 않은 `schedule`을 다시 보내지 않습니다. 다시 보내면 간격 일정이 지금부터 다시 셉니다. 필드를 빼고 보냅니다.
7. 고른 `mode`가 쓰지 않는 policy 필드를 보내지 않습니다(422).

## 2. 헤더

| 헤더 | 언제 | 값 |
| --- | --- | --- |
| `X-Api-Key` | 항상 | 발급받은 key |
| `X-User-Id` | 항상 | 호출한 사용자. 만드는 것의 소유자 |
| `Idempotency-Key` | `/api/v1/batch/` 아래 POST, PATCH, DELETE | 논리적인 쓰기마다 UUID. pr-batch가 7일 보관 |
| `If-Match` | 스크립트 이름 변경·삭제, 배치 수정·삭제·켜기·끄기 | ETag, 따옴표 포함 |
| `X-Project-Id` | 선택, `POST /batches`만 | 배치에 저장되고 바뀌지 않습니다. 이 서비스 자신의 tenant면 사용자가 멤버인 프로젝트여야 합니다 |
| `Content-Type` | JSON 본문 | `application/json`. 업로드는 `multipart/form-data` |
| `Accept` | 선택 | 그대로 전달 |

`X-Session-Id`는 전달되지 않습니다.

응답 헤더: `ETag`(상세와 쓰기 응답), `Location`(생성), `Content-Type`, `X-Request-ID`. `Location`은 pr-batch 기준 경로(`/api/v1/batches/{id}`)입니다. 따라가기 전에 `/api/v1/` → `/api/v1/batch/`로 바꿉니다. `Content-Disposition`은 전달되지 **않으므로** 받은 파일 이름은 직접 정합니다.

## 3. 조회 범위: 일반키와 마스터키

| | 일반키 | 마스터키 |
| --- | --- | --- |
| `GET /scripts`, `GET /batches` | `X-User-Id` 사용자 것만 | tenant 전체 |
| 쿼리 `user_id` | 선택. `X-User-Id`와 같아야 하고, 다르면 `403 FORBIDDEN` | 그 사용자 것으로 거릅니다 |
| 상세 경로 | 남의 것 → `404` | tenant 안의 모든 것 |
| 쓰기 | `X-User-Id`로 | `X-User-Id`로 |

쿼리 `user_id` 형식이 틀리면 `400 INVALID_IDENTITY`입니다. 모든 Script, Version, Batch, Run에는 `user_id`(소유자, Version에는 없음), `created_by`/`updated_by`(변경한 `X-User-Id`), `created_by_client`/`updated_by_client`(호출한 key 이름, 이 게이트웨이로 오면 `pr-agentic-service`)가 있습니다. 예약 실행이나 상태 반영처럼 사람이 하지 않은 변경은 둘 다 `null`입니다. `GET /runtimes`는 누구에게나 같은 목록이지만 `X-User-Id`는 보내야 합니다.

## 4. 흐름

### 4.1 올리기, 등록, 한 번 실행해 보기, 켜기

```
GET   /api/v1/batch/runtimes                        → {"items":[{"type":"JUPYTER","profile":"default"}, …]}
POST  /api/v1/batch/scripts          multipart       → 201 ScriptView (latest_version.version_number = 1)
POST  /api/v1/batch/batches          CreateBatch     → 201 BatchView (enabled: false), ETag "1"
POST  /api/v1/batch/batches/{id}/runs                → 202 RunView (status WAITING/QUEUED)
GET   /api/v1/batch/batches/{id}/runs/{run_id}       → 종료될 때까지 5초 이상 간격으로 폴링
GET   /api/v1/batch/batches/{id}                     → ETag, can_enable, enable_blocked_reason
POST  /api/v1/batch/batches/{id}/enable   If-Match   → 200 BatchView (enabled: true, next_run_at)
```

업로드 (multipart 폼 필드):

- `file`: `.ipynb`(nbformat v4).
- `type`: `NOTEBOOK`.
- `name`: 선택.

같은 바이트를 다시 올리면 새 버전을 만들지 않습니다.

노트북 제한:

| 규칙 | 기본값 | 오류 |
| --- | --- | --- |
| 파일이 `.ipynb`, nbformat v4 JSON | 해당 없음 | 422 `INVALID_NOTEBOOK` |
| 파일 크기 | 10 MiB | 413 `UPLOAD_TOO_LARGE` / `REQUEST_TOO_LARGE` |
| 전체 셀(markdown 포함) | 1000 | 422 `TOO_MANY_CELLS` |
| 비어 있지 않은 코드 셀(하나가 executor step 하나) | 100 | 422 `TOO_MANY_CELLS` |
| 코드 셀 하나 | 1 MiB | 422 `CELL_TOO_LARGE` |
| 코드 셀 최소 하나 | 해당 없음 | 422 `EMPTY_NOTEBOOK` |
| 커널 언어를 적었다면 Python | 해당 없음 | 422 `UNSUPPORTED_LANGUAGE` |

CreateBatch:

```jsonc
{
  "name": "Weekdays 08:00 line report",          // 필수, 1~255자, 제어 문자 없음
  "script_id": "<uuid>",                          // 필수
  "script_version_number": 2,                     // 선택. 빼면 등록 시점의 최신 버전
  "runtime": {"type": "JUPYTER", "profile": "default"},   // 필수. GET /runtimes에서
  "schedule": {                                   // 선택. 빼면 수동 실행만 (켤 수 없음)
    "definition": {"kind": "CRON", "expression": "0 8 * * MON-FRI"},
    "timezone": "Asia/Seoul",                     // 선택. 허용되는 값은 이것 하나
    "start_at": null, "end_at": null              // 선택, 오프셋 있는 ISO 8601. 시작은 포함, 끝은 제외
  },
  "policy": {                                     // 선택. 기본값 overlap SKIP, misfire SKIP
    "overlap": {"mode": "QUEUE", "max_queued": 100},
    "misfire": {"mode": "LATEST", "grace_seconds": 300}
  }
}
```

일정 `definition` (`kind` 하나를 고름):

```jsonc
{"kind": "ONCE", "at": "2026-12-01T09:00:00+09:00"}
{"kind": "INTERVAL", "seconds": 1800, "anchor": null}                 // 60~31536000
{"kind": "CALENDAR", "frequency": "DAILY", "at": "08:00:00"}           // 서울 현지 시각, 오프셋 없음
{"kind": "CALENDAR", "frequency": "WEEKLY", "at": "08:00:00", "weekdays": ["MON", "FRI"]}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "month_days": [1, 15]}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "last_day": true}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "nth_weekdays": [{"weekday": "MON", "nth": 1}]}  // nth 1~5 또는 -1
{"kind": "CRON", "expression": "*/10 9-17 * * MON-FRI"}               // 5필드 또는 @hourly 등. 초 필드와 L/W/#는 안 됨
```

Policy (고른 mode의 필드만 보냄):

| 구간 | mode | 필드 (기본값, 범위) |
| --- | --- | --- |
| `overlap` (이전 실행이 안 끝남) | `SKIP` | (없음) |
| | `QUEUE` | `max_queued` (100, 1~10000) |
| | `PARALLEL` | `max_concurrent` (필수, 1~100), `max_queued` (100) |
| | `REPLACE` | (없음). 실행 중인 run을 취소하고 새 run을 시작 |
| `misfire` (예약 시각을 놓침) | `SKIP` | `grace_seconds` (300, 1~86400) |
| | `LATEST` | `grace_seconds` |
| | `CATCH_UP` | `grace_seconds`, `max_runs` (10, 1~1000), `max_age_seconds` (86400, 60~31536000) |

### 4.2 켜기와 끄기

- 켜기 전에 BatchView의 `can_enable`과 `enable_blocked_reason`을 읽습니다. 켤 때 날 수 있는 오류:
  - `409 SCHEDULE_REQUIRED`
  - `422 NO_FUTURE_OCCURRENCE`, `UNKNOWN_RUNTIME`, `RUNTIME_NOT_SUPPORTED`
  - `503 EXECUTOR_NOT_CONFIGURED`, `RUNTIMES_NOT_CONFIGURED`
- 켜진 배치를 켜거나 꺼진 배치를 끄면 바뀌는 것 없이 `200`입니다.
- 켜면 지금부터 셉니다. 꺼져 있는 동안 놓친 시각은 채우지 않습니다.
- `disabled_reason`은 다음 중 하나입니다.
  - `OWNER`: 직접 껐습니다.
  - `USER_DEACTIVATED`: 소유자가 비활성화되었습니다. 수동 실행은 `409 OWNER_DEACTIVATED`입니다.
  - `TENANT_REVOKED`: tenant의 key가 폐기되었습니다. 수동 실행은 `409 TENANT_REVOKED`입니다.
- 위 두 경우를 빼면, 꺼진 배치와 일정 없는 배치도 수동 실행할 수 있습니다.

### 4.3 수정 (PATCH)

- 바꿀 필드만 보냅니다. `{}`는 422입니다.
- `name`, `script_id`, `runtime`, `policy`는 `null`이 될 수 없습니다.
- `script_version_number: null`은 최신 버전으로 다시 고정합니다.
- `schedule: null`은 일정을 지웁니다. 켜진 배치면 `409 SCHEDULE_REQUIRED`입니다.
- `policy`는 구간별로 합쳐집니다. 구간의 `mode`를 바꾸면 그 구간이 새 mode의 기본값으로 바뀝니다.
- 스크립트에 새 버전이 생겨도 기존 배치는 바뀌지 않습니다. 옮기려면 `script_version_number`를 PATCH합니다.

### 4.4 실행과 결과

Run 상태:

```
WAITING → QUEUED → RUNNING → COLLECTING → COMPLETED | FAILED
WAITING / QUEUED / RUNNING → CANCELLED        (취소는 이 상태에서만)
SKIPPED                                       (정책이 실행하지 않기로 함. 만들어질 때부터 종료 상태)
```

- `POST /batches/{id}/runs`는 본문이 없거나 `{}`이고 `202 RunView`를 돌려줍니다.
- 수동 실행이 동시 실행 한도에 걸리면 게이트웨이는 `409`와 `{"error": {"code": "CONFLICT", "message": "pr-batch refused the request.", "details": [], "context": <RunView>}}`로 답합니다. 그 `context`의 `status`는 `"SKIPPED"`, `skip_reason`은 `"SKIPPED_CAPACITY"`입니다. 실행 중인 run이 끝난 뒤 다시 시도합니다.
- run 취소는 `POST /batches/{id}/runs/{run_id}/cancel`과 `Idempotency-Key`로 합니다.
  - QUEUED나 RUNNING run이면 `202`와 `cancel_requested: true`, 그리고 **같은** 상태가 옵니다. `CANCELLED`까지 폴링합니다.
  - 끝난 run은 `409 NOT_CANCELLABLE`입니다.
- `notebook_status`는 run이 끝난 뒤에만 읽습니다.
- 결과 노트북: run이 `COMPLETED`면 `result.notebook_artifact_id`를 executor 게이트웨이에서 `GET /api/v1/executor/artifacts/{notebook_artifact_id}/content`로 받습니다. key와 `X-User-Id`는 같은 값을 씁니다.
- 실행 상세는 `GET /api/v1/executor/executions/{execution_id}`입니다. 노트북과 셀 경로는 `executor-for-agents.ko.md`를 봅니다.
- 쓰게 될 RunView 필드: `id`, `batch_id`, `user_id`(소유자), `status`, `skip_reason`, `failure_type`, `cancel_requested`, `trigger`(`MANUAL` 또는 `SCHEDULED`), `scheduled_for`, `execution_id`, `notebook_status`, `result.notebook_artifact_id`, `last_error`, `completed_at`.
- RunDetail에는 `steps[]`(`sequence`, `original_index` = 노트북 셀 index, `status`)가 더 있습니다.

### 4.5 채팅 노트북을 스크립트로 (이 서비스의 경로)

- `POST /api/v1/batch/scripts/from-notebook`에 `{"artifact_id": "<executor NOTEBOOK 아티팩트 id>", "name"?: "…"}`를 보냅니다. `201 ScriptView`가 옵니다.
- 이 서비스 자신의 tenant key만 쓸 수 있고, `X-User-Id`는 그 아티팩트를 볼 수 있는 활성 사용자여야 합니다.
- 노트북이 아닌 아티팩트는 422입니다.
- `Idempotency-Key`는 필요 없습니다. 서비스가 아티팩트와 그 내용으로 만듭니다.

### 4.6 배치 리포트 (이 서비스의 경로)

이 서비스 tenant의 배치 run이 성공하면, 서비스가 분석 리포트를 쓰고 executor 아티팩트로 저장해 run 노트북 끝에 붙입니다. 실패한 run은 리포트가 없습니다. 소유자(실행의 `context.user_id`)만 자기 리포트를 보고, `X-User-Id`는 이 서비스의 활성 사용자여야 합니다.

| 경로 | 내용 |
| --- | --- |
| `GET /api/v1/batch-reports?batch_id=&execution_id=&status=&cursor=&limit=` | 최신순. `status`는 `QUEUED`, `COLLECTING`, `GENERATING`, `MATERIALIZING`, `SUCCEEDED`, `FAILED` 중 하나 이상, 쉼표로 구분 |
| `GET /api/v1/batch-reports/{report_id}` | `markdown`, `summary`, `artifact_id`, `error`, `failed_stage`, `owner`, `execution` |
| `GET /api/v1/batch-reports/{report_id}/events?types=` | 저장된 진행 이벤트(`token`과 `activity`는 저장하지 않음) |
| `GET /api/v1/batch-reports/{report_id}/stream` | Server-Sent Events: 저장된 이벤트 다음에 실시간 이벤트. `Last-Event-ID` 헤더(또는 `?after=`)로 이어 받습니다. 서버가 15초마다 `: keep-alive`를 보냅니다 |
| `POST /api/v1/batch-reports/{report_id}/retry` | `FAILED` 리포트를 다시 큐에 넣음 → 202. 다른 상태는 409 |

이벤트 종류:

- `run_status`: `queued` → `running` → (`waiting_executor`) → `succeeded` 또는 `failed`.
- `token`, `activity`, `tool_call`.
- `artifact`: 리포트 또는 노트북.
- `message_final`: 리포트 Markdown.
- `run_error`.

## 5. 오류와 재시도

모든 오류(pr-batch와 게이트웨이)는 한 모양입니다.

```json
{"error": {"code": "REVISION_CONFLICT", "message": "human text, may change",
           "details": [{"location": ["header", "If-Match"], "type": "revision_conflict",
                        "message": "…", "context": {"expected": 3, "current": 4}}],
           "context": {}}}
```

| HTTP | `error.code` | 원인 | 클라이언트가 할 일 |
| --- | --- | --- | --- |
| 400 | `INVALID_IDENTITY` | `X-User-Id`나 `user_id` 없음·형식 오류 | 고침. 재시도 안 함 |
| 401 | `LOGIN_REQUIRED`, `INVALID_API_KEY` | key 없음, 모르거나 폐기된 key | 설정을 고침. 멈춤 |
| 403 | `FORBIDDEN` | 모르거나 비활성인 사용자(이 서비스 tenant), 일반키가 남의 `user_id`로 조회, 다른 tenant 사용자의 이 서비스 경로 호출 | 재시도 안 함 |
| 404 | `NOT_FOUND` | 목록에 없는 경로. 없음, 삭제됨, 다른 tenant, (일반키) 다른 사용자 | 경로나 id 확인 |
| 409 | `IDEMPOTENCY_CONFLICT` | 같은 key, 다른 본문 | 새 작업은 새 key |
| 409 | `REVISION_CONFLICT` | 낡은 `If-Match`(`details[0].context.expected`, `current`) | GET, 새 ETag로, **새** key로 보냄 |
| 409 | `SCRIPT_IN_USE`, `SCRIPT_HAS_ACTIVE_RUNS`, `BATCH_HAS_ACTIVE_RUNS`, `SCHEDULE_REQUIRED`, `NOT_CANCELLABLE`, `OWNER_DEACTIVATED`, `TENANT_REVOKED` | 이 상태에서 안 됨 | 상태부터 바꿈 |
| 409 | `CONFLICT` (`context`에 RunView) | 수동 실행이 동시 실행 한도에 걸림 | 실행 중인 run을 기다림 |
| 413 | `TOO_LARGE`(게이트웨이, 32 MB), `REQUEST_TOO_LARGE`, `UPLOAD_TOO_LARGE`(10 MiB) | 너무 큼 | 줄임 |
| 422 | `VALIDATION_ERROR` | 누락, 타입 오류, 범위 밖, 모르는 필드, `If-Match` 없음 | `details`대로 고침 |
| 422 | `INVALID_BODY` | 같은 오류가 이 서비스 경로(`from-notebook`, `batch-reports`)에서 남. 또는 `from-notebook`에 노트북이 아닌 아티팩트 | `details`대로 고침 |
| 422 | `INVALID_REVISION`, `INVALID_CURSOR`, `INVALID_POLICY`, `INVALID_NOTEBOOK`, `TOO_MANY_CELLS`, `CELL_TOO_LARGE`, `EMPTY_NOTEBOOK`, `UNSUPPORTED_LANGUAGE`, `UNKNOWN_RUNTIME`, `RUNTIME_NOT_SUPPORTED`, `NO_FUTURE_OCCURRENCE` | 잘못된 값 | 고침 |
| 500 | `INTERNAL_ERROR` | 버그(`details[0].context.error_id`) | `X-Request-ID`와 함께 알림 |
| 502 | `BAD_GATEWAY` | pr-batch에 닿지 않음 | 간격을 늘려 재시도, 같은 key와 본문 |
| 503 | `DATABASE_UNAVAILABLE`, `STORAGE_UNAVAILABLE`, `INCONSISTENT_STATE` | 일시적 | 간격을 늘려 재시도, 같은 key와 본문 |
| 503 | `EXECUTOR_NOT_CONFIGURED`, `RUNTIMES_NOT_CONFIGURED` | 서버 설정 | 알리고 나중에 재시도 |
| 504 | `ERROR` | pr-batch가 60초 넘게 걸림 | 간격을 늘려 재시도, 같은 key와 본문 |

재시도는 네트워크 오류, `502`, `503`(설정 코드 둘은 제외), `504`에서만 지수 백오프(1초, 2초, 4초, … 최대 30초, 최대 5번)로 합니다. **같은 `Idempotency-Key`와 같은 본문**을 쓰면 처음 응답이 그대로 돌아옵니다.

## 6. 엔드포인트

1~22번은 `/api/v1/batch` 아래에서 pr-batch로 중계합니다. 23~28번은 이 서비스가 직접 처리합니다. "IK"는 `Idempotency-Key` 헤더가, "IM"은 `If-Match`가 필요하다는 뜻입니다.

| # | 메서드 | 경로 | 본문 | 헤더 | 성공 |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/v1/batch/runtimes` | – | | 200 `RuntimeList` |
| 2 | POST | `/api/v1/batch/scripts` | multipart `file`, `type`, `name`? | IK | 201 `ScriptView` |
| 3 | GET | `/api/v1/batch/scripts?limit=&cursor=&user_id=` (limit 1~100, 기본 50) | – | | 200 `ScriptPage` |
| 4 | GET | `/api/v1/batch/scripts/{script_id}` | – | | 200 `ScriptView` + `ETag` |
| 5 | PATCH | `/api/v1/batch/scripts/{script_id}` | `RenameScript` `{"name"}` | IK, IM | 200 `ScriptView` |
| 6 | DELETE | `/api/v1/batch/scripts/{script_id}` | – | IK, IM | 204 |
| 7 | POST | `/api/v1/batch/scripts/{script_id}/versions` | multipart `file` | IK | 201 `VersionView` (같은 바이트면 200) |
| 8 | GET | `/api/v1/batch/scripts/{script_id}/versions?limit=&cursor=` | – | | 200 `VersionPage` (최신순) |
| 9 | GET | `/api/v1/batch/scripts/{script_id}/versions/{version_id}` | – | | 200 `VersionDetail` |
| 10 | GET | `/api/v1/batch/scripts/{script_id}/versions/{version_id}/content` | – | | 200 `.ipynb` 바이트 |
| 11 | POST | `/api/v1/batch/batches` | `CreateBatch` | IK, `X-Project-Id`? | 201 `BatchView` |
| 12 | GET | `/api/v1/batch/batches?limit=&cursor=&script_id=&user_id=` | – | | 200 `BatchPage` |
| 13 | GET | `/api/v1/batch/batches/{batch_id}` | – | | 200 `BatchView` + `ETag` |
| 14 | PATCH | `/api/v1/batch/batches/{batch_id}` | `UpdateBatch` | IK, IM | 200 `BatchView` |
| 15 | DELETE | `/api/v1/batch/batches/{batch_id}` | – | IK, IM | 204 |
| 16 | POST | `/api/v1/batch/batches/{batch_id}/enable` | – | IK, IM | 200 `BatchView` |
| 17 | POST | `/api/v1/batch/batches/{batch_id}/disable` | – | IK, IM | 200 `BatchView` |
| 18 | GET | `/api/v1/batch/batches/{batch_id}/skipped-windows?limit=&cursor=` | – | | 200 `SkippedPage` |
| 19 | POST | `/api/v1/batch/batches/{batch_id}/runs` | 없음 또는 `{}` | IK | 202 `RunView` |
| 20 | GET | `/api/v1/batch/batches/{batch_id}/runs?limit=&cursor=` | – | | 200 `RunPage` |
| 21 | GET | `/api/v1/batch/batches/{batch_id}/runs/{run_id}` | – | | 200 `RunDetail` |
| 22 | POST | `/api/v1/batch/batches/{batch_id}/runs/{run_id}/cancel` | – | IK | 202 `RunView` |
| 23 | GET | `/api/v1/batch-reports?batch_id=&execution_id=&status=&cursor=&limit=` | – | | 200 `BatchReportPage` |
| 24 | GET | `/api/v1/batch-reports/{report_id}` | – | | 200 `BatchReportDetail` |
| 25 | GET | `/api/v1/batch-reports/{report_id}/events?types=` | – | | 200 `BatchReportEvents` |
| 26 | GET | `/api/v1/batch-reports/{report_id}/stream` | – | `Last-Event-ID`? | 200 `text/event-stream` |
| 27 | POST | `/api/v1/batch-reports/{report_id}/retry` | – | | 202 `BatchReportDetail` |
| 28 | POST | `/api/v1/batch/scripts/from-notebook` | `BatchScriptFromNotebook` | | 201 `ScriptView` |

경로별 정확한 쿼리 파라미터, 한도, 응답 코드는 `openapi/batch-gateway.openapi.json`에 있습니다. pr-batch의 `batches:disable-by-owner`, `batches:disable-by-tenant`는 게이트웨이로 부를 수 없습니다(404).

## 7. 참고 클라이언트 (Python, httpx)

코드는 영문판과 같습니다.

```python
"""Batch gateway client. Config: AGENTIC_BASE_URL, AGENTIC_API_KEY."""

import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "SKIPPED"}
RETRY_CODES = {"BAD_GATEWAY", "DATABASE_UNAVAILABLE", "STORAGE_UNAVAILABLE",
               "INCONSISTENT_STATE", "ERROR", "EXECUTOR_UNAVAILABLE", "EXECUTOR_TIMEOUT"}


class GatewayError(Exception):
    def __init__(self, status: int, body: Any):
        error = body.get("error", {}) if isinstance(body, dict) else {}
        self.status, self.code = status, error.get("code", "UNKNOWN")
        self.details, self.context = error.get("details", []), error.get("context")
        super().__init__(f"{status} {self.code}: {error.get('message', '')}")


class BatchGateway:
    def __init__(self, user_id: str):
        self.http = httpx.Client(base_url=os.environ["AGENTIC_BASE_URL"].rstrip("/"),
                                 timeout=httpx.Timeout(70.0, connect=5.0))  # gateway waits 60 s
        self.base = {"X-Api-Key": os.environ["AGENTIC_API_KEY"], "X-User-Id": user_id.lower()}

    def _call(self, method: str, path: str, *, write: bool = False,
              etag: str | None = None, headers: dict | None = None, **kw) -> httpx.Response:
        h = {**self.base, **(headers or {})}
        if write:
            h["Idempotency-Key"] = str(uuid.uuid4())   # once per logical write
        if etag:
            h["If-Match"] = etag                       # quotes kept, e.g. "3"
        delay = 1.0
        for attempt in range(5):
            try:
                r = self.http.request(method, path, headers=h, **kw)
            except httpx.TransportError:
                if attempt == 4:
                    raise
            else:
                if r.status_code < 400:
                    return r
                try:
                    body = r.json()
                except ValueError:
                    body = {}
                err = GatewayError(r.status_code, body)
                if err.code not in RETRY_CODES or attempt == 4:
                    raise err
            time.sleep(delay)                          # same key, same body
            delay = min(delay * 2, 30)

    # scripts
    def runtimes(self) -> list[dict]:
        return self._call("GET", "/api/v1/batch/runtimes").json()["items"]

    def upload(self, notebook: Path, name: str | None = None) -> dict:
        data = {"type": "NOTEBOOK", **({"name": name} if name else {})}
        files = {"file": (notebook.name, notebook.read_bytes(), "application/x-ipynb+json")}
        return self._call("POST", "/api/v1/batch/scripts", write=True,
                          data=data, files=files).json()

    def add_version(self, script_id: str, notebook: Path) -> dict:
        files = {"file": (notebook.name, notebook.read_bytes(), "application/x-ipynb+json")}
        return self._call("POST", f"/api/v1/batch/scripts/{script_id}/versions",
                          write=True, files=files).json()

    # batches
    def create_batch(self, body: dict, project_id: str | None = None) -> dict:
        headers = {"X-Project-Id": project_id} if project_id else None
        return self._call("POST", "/api/v1/batch/batches", write=True,
                          headers=headers, json=body).json()

    def get_batch(self, batch_id: str) -> tuple[dict, str]:
        r = self._call("GET", f"/api/v1/batch/batches/{batch_id}")
        return r.json(), r.headers["ETag"]

    def _with_etag(self, method: str, path: str, batch_id: str, **kw) -> dict:
        for _ in range(3):  # a stale ETag: read again, new key, try again
            _, etag = self.get_batch(batch_id)
            try:
                r = self._call(method, path, write=True, etag=etag, **kw)
                return r.json() if r.content else {}
            except GatewayError as e:
                if e.code != "REVISION_CONFLICT":
                    raise
        raise RuntimeError("batch keeps changing")

    def enable(self, batch_id: str) -> dict:
        return self._with_etag("POST", f"/api/v1/batch/batches/{batch_id}/enable", batch_id)

    def disable(self, batch_id: str) -> dict:
        return self._with_etag("POST", f"/api/v1/batch/batches/{batch_id}/disable", batch_id)

    def update(self, batch_id: str, changes: dict) -> dict:   # only changed fields
        return self._with_etag("PATCH", f"/api/v1/batch/batches/{batch_id}", batch_id,
                               json=changes)

    # runs
    def run_now(self, batch_id: str) -> dict:
        try:
            return self._call("POST", f"/api/v1/batch/batches/{batch_id}/runs",
                              write=True, json={}).json()
        except GatewayError as e:
            if e.code == "CONFLICT" and (e.context or {}).get("skip_reason") == "SKIPPED_CAPACITY":
                return e.context                        # a SKIPPED RunView
            raise

    def wait_run(self, batch_id: str, run_id: str, *, interval: float = 5.0,
                 timeout: float = 6 * 3600) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            run = self._call("GET", f"/api/v1/batch/batches/{batch_id}/runs/{run_id}").json()
            if run["status"] in TERMINAL:
                return run
            if time.monotonic() > deadline:
                raise TimeoutError(run_id)
            time.sleep(max(interval, 5.0))

    def result_notebook(self, run: dict) -> bytes | None:
        artifact = (run.get("result") or {}).get("notebook_artifact_id")
        if run["status"] != "COMPLETED" or not artifact:
            return None
        return self._call("GET", f"/api/v1/executor/artifacts/{artifact}/content").content

    def list_all(self, path: str, **params) -> list[dict]:
        items, cursor = [], None
        while True:
            q = {**params, **({"cursor": cursor} if cursor else {})}
            page = self._call("GET", path, params=q).json()
            items += page["items"]
            cursor = page.get("next_cursor")
            if not cursor:
                return items
```

사용 예:

```python
gw = BatchGateway("e12345")
runtime = gw.runtimes()[0]                                  # {"type": "JUPYTER", "profile": "default"}
script = gw.upload(Path("daily.ipynb"), name="Daily line report")
batch = gw.create_batch({
    "name": "Weekdays 08:00",
    "script_id": script["id"],
    "runtime": runtime,
    "schedule": {"definition": {"kind": "CRON", "expression": "0 8 * * MON-FRI"}},
    "policy": {"overlap": {"mode": "SKIP"}, "misfire": {"mode": "LATEST", "grace_seconds": 600}},
}, project_id="project-100")

run = gw.run_now(batch["id"])                               # try once while still disabled
run = gw.wait_run(batch["id"], run["id"])
if run["status"] == "COMPLETED":
    Path("result.ipynb").write_bytes(gw.result_notebook(run))
else:
    print(run["status"], run["skip_reason"], run["failure_type"], run["last_error"])

view, _ = gw.get_batch(batch["id"])
if view["can_enable"]:
    gw.enable(batch["id"])
else:
    print("cannot enable:", view["enable_blocked_reason"])

gw.update(batch["id"], {"script_version_number": None})    # re-pin to latest; schedule left out
```

## 8. 체크리스트 (자주 하는 실수)

- [ ] 조회를 포함한 모든 요청에 `X-User-Id`.
- [ ] `/api/v1/batch/` 아래 모든 POST, PATCH, DELETE에 `Idempotency-Key` 헤더. 재시도는 같은 key, `REVISION_CONFLICT` 뒤에는 새 key.
- [ ] `If-Match`는 따옴표 포함, 가장 최근 GET이나 쓰기 응답 값.
- [ ] `runtime`은 `GET /runtimes`에서 그대로 복사.
- [ ] 새 배치는 꺼져 있음. `can_enable`을 먼저 보고 `enable`을 부름.
- [ ] PATCH는 바뀐 필드만. 바뀌지 않은 `schedule`은 다시 보내지 않음.
- [ ] 수동 실행 `409 CONFLICT`는 `error.context`에 SKIPPED RunView가 있음.
- [ ] run 폴링은 5초 이상 간격. `SKIPPED`도 종료 상태.
- [ ] 결과 노트북은 executor 게이트웨이에서: `/api/v1/executor/artifacts/{notebook_artifact_id}/content`.
- [ ] `Location`은 `/api/v1/` → `/api/v1/batch/`로 바꾼 뒤에만 따라감.
- [ ] 일반키: `user_id` 필터를 쓰지 않거나, 정확히 자기 `X-User-Id`만.
- [ ] 모르는 응답 필드와 모르는 이벤트 종류는 무시.

## 9. 타입

pr-batch OpenAPI와 이 서비스의 경로에서 자동으로 만든 부분입니다. 손으로 고치지 않습니다.

- `unknown fields → 422`가 붙은 interface는 요청 본문입니다. 응답 타입에는 필드가 늘 수 있으니 모르는 필드는 무시합니다.
- `string` 시각은 시간대가 있는 ISO 8601이고, id는 UUID 문자열입니다.
- `BatchReportEvents.items`는 이 서비스의 실행 이벤트 타입(`*Event` / `*Data`)을 씁니다.
- 이 서비스 경로의 스키마 이름이 pr-batch 것과 겹치면 우리 스키마 앞에 `Agentic`을 붙입니다.

<!-- gen:begin types -->
```ts
interface ActivityData {
  id: string;
  kind: string;
  state: "started" | "finished" | "failed" | "paused";
  label?: string | null;
  elapsed_ms?: number | null;
}
interface ActivityEvent {
  id: number;
  type: "activity";
  data: ActivityData;
  created_at: string;
}
interface AgentSwitchedData {
  agent: "main" | "analyst";
  task?: string | null;
}
interface AgentSwitchedEvent {
  id: number;
  type: "agent_switched";
  data: AgentSwitchedData;
  created_at: string;
}
interface ArtifactAttachment {
  kind: "report" | "notebook";
  artifact_id: string;
  title: string;
  lab_url?: string | null;
}
interface ArtifactEvent {
  id: number;
  type: "artifact";
  data: ArtifactAttachment;
  created_at: string;
}
interface BatchPage {
  items: BatchView[];
  next_cursor: string | null;
}
interface BatchReportDetail {
  id: string;
  execution_id: string;
  batch_id: string | null;
  batch_run_id: string | null;
  state: "QUEUED" | "COLLECTING" | "GENERATING" | "MATERIALIZING" | "SUCCEEDED" | "FAILED";
  failed_stage: string | null;
  title: string | null;
  artifact_id: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  owner: BatchReportOwner;
  markdown: string | null;
  summary: string | null;
  execution: Record<string, unknown>;
}
interface BatchReportEvents {
  report_id: string;
  state: "QUEUED" | "COLLECTING" | "GENERATING" | "MATERIALIZING" | "SUCCEEDED" | "FAILED";
  items: (RunStatusEvent | TokenEvent | MessageFinalEvent | ToolCallEvent | AgentSwitchedEvent | PlanApprovedEvent | PlanAutoApprovedEvent | PlanRevisedEvent | ExecutionProgressEvent | ExecutionCompletedEvent | HitlRequestEvent | HitlResolvedEvent | ArtifactEvent | MemoryUpdatedEvent | WorkflowSavedEvent | RunErrorEvent | SessionTitledEvent | ActivityEvent | ContextSummarizedEvent)[];
}
interface BatchReportOwner {
  id: string;
  employee_id: string;
  name: string;
}
interface BatchReportPage {
  items: BatchReportRead[];
  next_cursor: string | null;
}
interface BatchReportRead {
  id: string;
  execution_id: string;
  batch_id: string | null;
  batch_run_id: string | null;
  state: "QUEUED" | "COLLECTING" | "GENERATING" | "MATERIALIZING" | "SUCCEEDED" | "FAILED";
  failed_stage: string | null;
  title: string | null;
  artifact_id: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}
interface BatchScriptFromNotebook { // unknown fields → 422
  artifact_id: string;
  name?: string | null;
}
interface BatchView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  name: string;
  script_id: string;
  script_version_id: string;
  script_version_number: number;
  runtime: RuntimeSpec;
  schedule: Schedule | null;
  policy: Policy;
  tenant_id: string;
  project_id: string | null;
  user_id: string;
  enabled: boolean;
  can_enable: boolean;
  can_disable: boolean;
  enable_blocked_reason: string | null;
  disabled_reason: string | null;
  disabled_at: string | null;
  next_run_at: string | null;
  preview_runs: string[];
  config_number: number;
  revision: number;
}
interface Body_add_version_api_v1_scripts__script_id__versions_post {
  file: string;
}
interface Body_create_script_api_v1_scripts_post {
  file: string;
  type: ScriptType;
  name?: string | null; // 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$`
}
interface Calendar { // unknown fields → 422
  kind: "CALENDAR";
  frequency: "DAILY" | "WEEKLY" | "MONTHLY";
  at: string;
  weekdays?: ("MON" | "TUE" | "WED" | "THU" | "FRI" | "SAT" | "SUN")[]; // 항목 ≤ 7
  month_days?: number[]; // 항목 ≤ 31
  last_day?: boolean; // default false
  nth_weekdays?: NthWeekday[]; // 항목 ≤ 35
}
interface CatchUpMisfire { // unknown fields → 422
  mode: "CATCH_UP";
  grace_seconds?: number; // default 300; ≥ 1, ≤ 86400
  max_runs?: number; // default 10; ≥ 1, ≤ 1000
  max_age_seconds?: number; // default 86400; ≥ 60, ≤ 31536000
}
interface CellCounts {
  total: number;
  executable: number;
  skipped: number;
}
interface CellEntry {
  index: number;
  type: string;
  executed: boolean;
  sequence?: number | null;
}
interface CodeApprovalRequest {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "code_approval";
  purpose: string;
  code: string;
  code_level: number;
}
interface ContextSummarizedData {
  messages: number;
  summary_chars: number;
}
interface ContextSummarizedEvent {
  id: number;
  type: "context_summarized";
  data: ContextSummarizedData;
  created_at: string;
}
interface CreateBatch { // unknown fields → 422
  name: string; // 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$`
  script_id: string;
  script_version_number?: number | null; // ≥ 1
  runtime: RuntimeSpec;
  schedule?: Schedule | null;
  policy?: Policy;
}
interface Cron { // unknown fields → 422
  kind: "CRON";
  expression: string; // 길이 ≥ 1, 길이 ≤ 128
}
interface ExecutionCompletedData {
  execution_id: string;
  results: StepResult[];
  error?: string | null;
}
interface ExecutionCompletedEvent {
  id: number;
  type: "execution_completed";
  data: ExecutionCompletedData;
  created_at: string;
}
interface ExecutionProgressData {
  event_type: string;
  status?: string | null;
  step?: Record<string, unknown> | null;
  error?: unknown;
  reason?: string | null;
  paused_seconds?: number | null;
  finished_during_handover?: boolean | null;
}
interface ExecutionProgressEvent {
  id: number;
  type: "execution_progress";
  data: ExecutionProgressData;
  created_at: string;
}
interface ExecutorWait {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "executor_wait";
  execution_id: string;
  operation_id: string | null;
  steps?: string[];
}
interface HitlRequestEvent {
  id: number;
  type: "hitl_request";
  data: QuestionRequest | PlanApprovalRequest | CodeApprovalRequest | WorkflowSaveRequest | ExecutorWait;
  created_at: string;
}
interface HitlResolvedData {
  interrupt_id: string | null;
}
interface HitlResolvedEvent {
  id: number;
  type: "hitl_resolved";
  data: HitlResolvedData;
  created_at: string;
}
interface InputSlot {
  key: string;
  tool: string;
  param: string;
  type?: string | null;
  required: boolean;
  value?: unknown;
}
interface Interval { // unknown fields → 422
  kind: "INTERVAL";
  seconds: number; // ≥ 60, ≤ 31536000
  anchor?: string | null;
}
interface LatestMisfire { // unknown fields → 422
  mode: "LATEST";
  grace_seconds?: number; // default 300; ≥ 1, ≤ 86400
}
type ManualRun = Record<string, unknown>;
interface MemoryUpdatedData {
  topic: string;
  title: string;
  content: string;
  version: number;
  updated_at: string | null;
  by: "user" | "agent";
}
interface MemoryUpdatedEvent {
  id: number;
  type: "memory_updated";
  data: MemoryUpdatedData;
  created_at: string;
}
interface MessageFinalData {
  content: string;
}
interface MessageFinalEvent {
  id: number;
  type: "message_final";
  data: MessageFinalData;
  created_at: string;
}
interface MisfirePatch { // unknown fields → 422
  mode?: "SKIP" | "LATEST" | "CATCH_UP" | null;
  grace_seconds?: number | null; // ≥ 1, ≤ 86400
  max_runs?: number | null; // ≥ 1, ≤ 1000
  max_age_seconds?: number | null; // ≥ 60, ≤ 31536000
}
interface NthWeekday { // unknown fields → 422
  weekday: "MON" | "TUE" | "WED" | "THU" | "FRI" | "SAT" | "SUN";
  nth: 1 | 2 | 3 | 4 | 5 | -1;
}
interface Once { // unknown fields → 422
  kind: "ONCE";
  at: string;
}
interface OverlapPatch { // unknown fields → 422
  mode?: "SKIP" | "QUEUE" | "PARALLEL" | "REPLACE" | null;
  max_concurrent?: number | null; // ≥ 1, ≤ 100
  max_queued?: number | null; // ≥ 1, ≤ 10000
}
interface ParallelOverlap { // unknown fields → 422
  mode: "PARALLEL";
  max_concurrent: number; // ≥ 1, ≤ 100
  max_queued?: number; // default 100; ≥ 1, ≤ 10000
}
interface ParamRef {
  call: number | null;
  tool: string | null;
  output: string;
}
interface PlanApprovalRequest {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "plan_approval";
  candidates: PlanCandidate[];
  allow_reject_templates?: boolean; // default false
}
interface PlanApprovedData {
  plan_id: string;
  title: string;
  document: Record<string, unknown>;
}
interface PlanApprovedEvent {
  id: number;
  type: "plan_approved";
  data: PlanApprovedData;
  created_at: string;
}
interface PlanAutoApprovedData {
  title: string;
  source?: WorkflowSource | null;
}
interface PlanAutoApprovedEvent {
  id: number;
  type: "plan_auto_approved";
  data: PlanAutoApprovedData;
  created_at: string;
}
interface PlanCall {
  index: number;
  key: string;
  skill: string;
  skill_description?: string; // default ""
  tool: string;
  summary?: string; // default ""
  execution: "always" | "conditional";
  condition?: string | null;
  params: PlanParam[];
}
interface PlanCandidate {
  title: string;
  rationale?: string; // default ""
  source?: WorkflowSource | null;
  document: Record<string, unknown>;
  calls: PlanCall[];
  input_slots: InputSlot[];
  input_values?: Record<string, unknown>;
}
interface PlanParam {
  name: string;
  key: string;
  type: string | null;
  required: boolean;
  doc?: string; // default ""
  source: "literal" | "input" | "tool_output" | "default";
  value?: unknown;
  default?: string | null;
  ref?: ParamRef | null;
}
interface PlanRevisedData {
  call: number;
  args: Record<string, unknown>;
}
interface PlanRevisedEvent {
  id: number;
  type: "plan_revised";
  data: PlanRevisedData;
  created_at: string;
}
interface Policy { // unknown fields → 422
  overlap?: SkipOverlap | QueueOverlap | ParallelOverlap | ReplaceOverlap;
  misfire?: SkipMisfire | LatestMisfire | CatchUpMisfire;
}
interface PolicyPatch { // unknown fields → 422
  overlap?: OverlapPatch | null;
  misfire?: MisfirePatch | null;
}
interface QuestionField {
  key: string;
  label?: string | null;
  type?: string | null;
  required?: boolean; // default false
}
interface QuestionRequest {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "question";
  question: string;
  options?: string[];
  fields?: QuestionField[];
}
interface QueueOverlap { // unknown fields → 422
  mode: "QUEUE";
  max_queued?: number; // default 100; ≥ 1, ≤ 10000
}
interface RenameScript { // unknown fields → 422
  name: string; // 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$`
}
interface ReplaceOverlap { // unknown fields → 422
  mode: "REPLACE";
}
interface ResultRefs {
  notebook_artifact_id?: string | null;
}
interface RunDetail {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  batch_id: string;
  user_id: string;
  script_id: string;
  script_version_id: string;
  config_number: number;
  runtime: Record<string, unknown>;
  snapshot: Record<string, unknown>;
  trigger: string;
  scheduled_for: string | null;
  status: string;
  skip_reason: string | null;
  cancel_requested: boolean;
  cancel_source: string | null;
  cancel_reason: string | null;
  execution_id: string | null;
  operation_id: string | null;
  execution_status: string | null;
  observed_version: number | null;
  failure_type: string | null;
  notebook_status: string | null;
  last_error: string | null;
  artifacts: Record<string, unknown>[];
  attempts: Record<string, unknown>[];
  retry_info: Record<string, unknown> | null;
  result?: ResultRefs; // default {}
  submitted_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  observed_at: string | null;
  completed_at: string | null;
  steps: StepView[];
}
interface RunErrorData {
  message: string;
}
interface RunErrorEvent {
  id: number;
  type: "run_error";
  data: RunErrorData;
  created_at: string;
}
interface RunPage {
  items: RunView[];
  next_cursor: string | null;
}
interface RunStatusData {
  status: "queued" | "running" | "waiting_input" | "waiting_executor" | "succeeded" | "failed" | "cancelled";
  execution_id?: string | null;
  operation_id?: string | null;
  steps?: string[] | null;
}
interface RunStatusEvent {
  id: number;
  type: "run_status";
  data: RunStatusData;
  created_at: string;
}
interface RunView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  batch_id: string;
  user_id: string;
  script_id: string;
  script_version_id: string;
  config_number: number;
  runtime: Record<string, unknown>;
  snapshot: Record<string, unknown>;
  trigger: string;
  scheduled_for: string | null;
  status: string;
  skip_reason: string | null;
  cancel_requested: boolean;
  cancel_source: string | null;
  cancel_reason: string | null;
  execution_id: string | null;
  operation_id: string | null;
  execution_status: string | null;
  observed_version: number | null;
  failure_type: string | null;
  notebook_status: string | null;
  last_error: string | null;
  artifacts: Record<string, unknown>[];
  attempts: Record<string, unknown>[];
  retry_info: Record<string, unknown> | null;
  result?: ResultRefs; // default {}
  submitted_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  observed_at: string | null;
  completed_at: string | null;
}
interface RuntimeList {
  items: RuntimeSpec[];
}
interface RuntimeSpec { // unknown fields → 422
  type?: "JUPYTER"; // default "JUPYTER"
  profile: string; // 길이 ≥ 1, 길이 ≤ 128, `^[^\x00-\x1f\x7f]+$`
}
interface Schedule { // unknown fields → 422
  definition: Once | Interval | Calendar | Cron;
  timezone?: "Asia/Seoul"; // default "Asia/Seoul"
  start_at?: string | null;
  end_at?: string | null;
}
interface ScriptPage {
  items: ScriptView[];
  next_cursor: string | null;
}
type ScriptType = "NOTEBOOK";
interface ScriptView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  name: string;
  type: ScriptType;
  user_id: string;
  revision: number;
  latest_version: VersionView;
}
interface SessionTitledData {
  title: string;
}
interface SessionTitledEvent {
  id: number;
  type: "session_titled";
  data: SessionTitledData;
  created_at: string;
}
interface SkipMisfire { // unknown fields → 422
  mode: "SKIP";
  grace_seconds?: number; // default 300; ≥ 1, ≤ 86400
}
interface SkipOverlap { // unknown fields → 422
  mode: "SKIP";
}
interface SkippedPage {
  items: SkippedView[];
  next_cursor: string | null;
}
interface SkippedView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  batch_id: string;
  config_number: number;
  from_at: string;
  until_at: string;
  occurrences: number;
  reason: string;
}
interface StepResult {
  call?: number | null;
  tool?: string | null;
  id?: string | null;
  status: string;
  observations?: unknown[];
  stdout?: string; // default ""
  images?: string[];
  error?: unknown;
}
interface StepView {
  sequence: number;
  original_index: number;
  source_sha256: string;
  step_id: string | null;
  status: string | null;
  result_ref: Record<string, unknown> | null;
}
interface TokenData {
  text: string;
}
interface TokenEvent {
  id: number;
  type: "token";
  data: TokenData;
  created_at: string;
}
interface ToolCallData {
  name: string;
  args: Record<string, unknown>;
  label?: string; // default ""
}
interface ToolCallEvent {
  id: number;
  type: "tool_call";
  data: ToolCallData;
  created_at: string;
}
interface UpdateBatch { // unknown fields → 422
  name?: string | null; // 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$`
  script_id?: string | null;
  script_version_number?: number | null; // ≥ 1
  runtime?: RuntimeSpec | null;
  schedule?: Schedule | null;
  policy?: PolicyPatch | null;
}
interface VersionDetail {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  script_id: string;
  version_number: number;
  filename: string;
  sha256: string;
  code_hash: string;
  size_bytes: number;
  cells: CellCounts;
  cell_list: CellEntry[];
}
interface VersionPage {
  items: VersionView[];
  next_cursor: string | null;
}
interface VersionView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  script_id: string;
  version_number: number;
  filename: string;
  sha256: string;
  code_hash: string;
  size_bytes: number;
  cells: CellCounts;
}
interface WorkflowSaveRequest {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "workflow_save";
  name: string;
  user_queries: string[];
  tags?: string[];
  document: Record<string, unknown>;
  excluded_custom_steps?: number; // default 0
}
interface WorkflowSavedData {
  workflow_id: string;
  name: string;
}
interface WorkflowSavedEvent {
  id: number;
  type: "workflow_saved";
  data: WorkflowSavedData;
  created_at: string;
}
interface WorkflowSource {
  workflow_id: string;
  revision: number;
  name: string;
  similarity?: number | null;
}
```
<!-- gen:end types -->

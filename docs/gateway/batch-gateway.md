# 배치 게이트웨이 API (`/api/v1/batch/…`, `/api/v1/batch-reports`)

pr-agentic-service를 거쳐 pr-batch를 부르는 API와, 이 서비스가 직접 제공하는 배치 API입니다. pr-batch는 Jupyter 노트북을 올려 두고 일정이나 수동 요청으로 executor에서 실행합니다. 실행 자체는 executor가 하고, pr-batch는 스크립트 보관, 일정, 실행 접수와 추적을 맡습니다.

먼저 [00-common.md](00-common.md)를 읽습니다. 주소, key 종류, `X-User-Id`, 조회 범위, 오류 형식, 넘어가는 헤더는 거기에 있습니다.

## 1. 개념

```
Script (노트북) 1──* Version (바이트가 고정된 한 벌, 번호 1,2,3…)
Batch  ──고정──▶ Version 하나 + runtime + schedule + policy     (등록하면 꺼진 상태)
Batch  1──* Run (실행 한 번 = executor Execution 하나)
Batch  1──* SkippedWindow (정책 때문에 실행하지 않은 예약 구간)
```

| 개념 | 설명 |
| --- | --- |
| Script | 올린 노트북. 이름과 버전 목록. 타입은 `NOTEBOOK` 하나 |
| Version | 노트북 원본 한 벌. 같은 바이트를 다시 올리면 새로 만들지 않습니다. 비어 있지 않은 코드 셀 하나가 Step 하나가 됩니다 |
| Batch | 어떤 버전을, 어떤 런타임에서, 언제, 어떤 정책으로 돌릴지. **등록하면 꺼져 있고** `enable`로 켭니다 |
| Run | 실행 한 번. 수동 실행이나 예약 시각에 생기고 executor Execution 하나와 1:1입니다 |
| 소유 | 모든 자원은 (tenant, 사용자) 것입니다. tenant는 key, 사용자는 `X-User-Id`입니다. 응답의 `user_id`가 소유자입니다 |
| 기록 | `created_by`·`updated_by`는 요청의 `X-User-Id`, `created_by_client`·`updated_by_client`는 pr-batch를 부른 key 이름(이 게이트웨이로 오면 `pr-agentic-service`)입니다. 예약 실행·상태 반영처럼 사람이 하지 않은 변경은 둘 다 `null`입니다 |

일반적인 흐름:

1. `GET /api/v1/batch/runtimes`로 고를 수 있는 런타임 확인
2. `POST /api/v1/batch/scripts`로 노트북 업로드
3. `POST /api/v1/batch/batches`로 배치 등록 (꺼진 상태)
4. `POST /api/v1/batch/batches/{id}/runs`로 한 번 돌려 보고, `POST /api/v1/batch/batches/{id}/enable`로 일정 켜기
5. `GET /api/v1/batch/batches/{id}/runs/{run_id}`로 상태 확인. 끝나면 결과 노트북을 executor 게이트웨이에서 받기(`GET /api/v1/executor/artifacts/{notebook_artifact_id}/content`)

## 2. 엔드포인트 한눈에 보기

1~22는 pr-batch 중계, 23~28은 이 서비스의 API입니다. 이 밖의 `/api/v1/batch/…` 경로는 404입니다.

<!-- gen:begin summary -->
| # | Method | Path | 요청 본문 | 성공 응답 |
| --- | --- | --- | --- | --- |
| 1 | GET | `/api/v1/batch/runtimes` | - | 200 RuntimeList |
| 2 | GET | `/api/v1/batch/scripts` | - | 200 ScriptPage |
| 3 | POST | `/api/v1/batch/scripts` | Body_create_script_api_v1_scripts_post | 201 ScriptView |
| 4 | GET | `/api/v1/batch/scripts/{script_id}` | - | 200 ScriptView |
| 5 | PATCH | `/api/v1/batch/scripts/{script_id}` | RenameScript | 200 ScriptView |
| 6 | DELETE | `/api/v1/batch/scripts/{script_id}` | - | 204 |
| 7 | GET | `/api/v1/batch/scripts/{script_id}/versions` | - | 200 VersionPage |
| 8 | POST | `/api/v1/batch/scripts/{script_id}/versions` | Body_add_version_api_v1_scripts__script_id__versions_post | 201 VersionView |
| 9 | GET | `/api/v1/batch/scripts/{script_id}/versions/{version_id}` | - | 200 VersionDetail |
| 10 | GET | `/api/v1/batch/scripts/{script_id}/versions/{version_id}/content` | - | 200 string (binary) |
| 11 | GET | `/api/v1/batch/batches` | - | 200 BatchPage |
| 12 | POST | `/api/v1/batch/batches` | CreateBatch | 201 BatchView |
| 13 | GET | `/api/v1/batch/batches/{batch_id}` | - | 200 BatchView |
| 14 | PATCH | `/api/v1/batch/batches/{batch_id}` | UpdateBatch | 200 BatchView |
| 15 | DELETE | `/api/v1/batch/batches/{batch_id}` | - | 204 |
| 16 | POST | `/api/v1/batch/batches/{batch_id}/enable` | - | 200 BatchView |
| 17 | POST | `/api/v1/batch/batches/{batch_id}/disable` | - | 200 BatchView |
| 18 | GET | `/api/v1/batch/batches/{batch_id}/skipped-windows` | - | 200 SkippedPage |
| 19 | GET | `/api/v1/batch/batches/{batch_id}/runs` | - | 200 RunPage |
| 20 | POST | `/api/v1/batch/batches/{batch_id}/runs` | ManualRun \| null | 202 RunView |
| 21 | GET | `/api/v1/batch/batches/{batch_id}/runs/{run_id}` | - | 200 RunDetail |
| 22 | POST | `/api/v1/batch/batches/{batch_id}/runs/{run_id}/cancel` | - | 202 RunView |
| 23 | GET | `/api/v1/batch-reports` | - | 200 BatchReportPage |
| 24 | GET | `/api/v1/batch-reports/{report_id}` | - | 200 BatchReportDetail |
| 25 | GET | `/api/v1/batch-reports/{report_id}/events` | - | 200 BatchReportEvents |
| 26 | GET | `/api/v1/batch-reports/{report_id}/stream` | - | 200 string |
| 27 | POST | `/api/v1/batch-reports/{report_id}/retry` | - | 202 BatchReportDetail |
| 28 | POST | `/api/v1/batch/scripts/from-notebook` | BatchScriptFromNotebook | 201 ScriptView |
<!-- gen:end summary -->

## 3. 이 게이트웨이만의 규칙

[00-common.md](00-common.md)에 더해 이것만 다릅니다.

| 항목 | 규칙 |
| --- | --- |
| `Idempotency-Key` | 쓰기(POST·PATCH·DELETE)마다 **필수 헤더**입니다. 1~255자, 공백 없는 ASCII. 그대로 pr-batch에 넘어갑니다. 같은 tenant·사용자·작업·키·본문이면 처음 응답을 그대로 돌려주고(7일 보관), 같은 키에 다른 본문은 409 `IDEMPOTENCY_CONFLICT` |
| `If-Match` | 스크립트 이름 변경·삭제, 배치 수정·삭제·켜기·끄기에 필수. 상세 GET이나 직전 쓰기 응답의 `ETag` 값을 **따옴표까지 그대로**(예: `"3"`). 낡았으면 409 `REVISION_CONFLICT`, 따옴표가 없으면 422 `INVALID_REVISION`, 없으면 422 |
| `X-Project-Id` | 배치 등록(`POST /batches`) 때만 넘어가고 배치에 저장됩니다. 나중에 바꿀 수 없습니다. 이 서비스 tenant key면 멤버인 프로젝트여야 합니다 |
| `X-Session-Id` | 넘기지 않습니다 |
| 조회 범위 | 00-common 4.2와 같습니다. 쿼리 `user_id` 필터는 `GET /scripts`, `GET /batches`에서 받습니다 |
| `GET /runtimes` | 누구에게나 같은 목록입니다. 그래도 `X-User-Id`는 보내야 합니다 |
| `Location` | pr-batch 기준 경로(`/api/v1/batches/{id}`)입니다. `/api/v1/` → `/api/v1/batch/`로 바꿔 씁니다 |
| 오류 본문 | pr-batch 오류는 공통 형식 그대로 옵니다. **예외 하나:** 수동 실행이 동시 실행 한도에 걸린 409(아래 5.4)는 RunView 대신 `{"error": {"code": "CONFLICT", …, "context": <RunView>}}`로 옵니다 |

## 4. 상태

### 4.1 Batch

```
등록 ──▶ 꺼짐 ──enable──▶ 켜짐 ──disable──▶ 꺼짐 (disabled_reason=OWNER)
                              ├─ 사용자 비활성화 ▶ 꺼짐 (USER_DEACTIVATED)   수동 실행 → 409 OWNER_DEACTIVATED
                              └─ tenant 폐기     ▶ 꺼짐 (TENANT_REVOKED)     수동 실행 → 409 TENANT_REVOKED
```

- 켜려면 다음 실행 시각이 있는 일정, 설정된 executor, 쓸 수 있는 런타임이 필요합니다. 호출하기 전에 `can_enable`과 `enable_blocked_reason`을 봅니다(`SCHEDULE_REQUIRED` 409, `NO_FUTURE_OCCURRENCE`·`UNKNOWN_RUNTIME`·`RUNTIME_NOT_SUPPORTED` 422, `EXECUTOR_NOT_CONFIGURED`·`RUNTIMES_NOT_CONFIGURED` 503).
- 이미 켜진 배치를 켜거나 꺼진 배치를 끄면 200이고 아무것도 바뀌지 않습니다.
- 켜면 지금부터 일정을 셉니다. 꺼져 있던 동안의 예약은 채우지 않습니다.
- 수동 실행은 꺼진 배치, 일정 없는 배치에서도 됩니다(위 두 사유 제외).

### 4.2 Run

```
WAITING ─▶ QUEUED ─▶ RUNNING ─▶ COLLECTING ─▶ COMPLETED | FAILED
   └──────────┴─────────┴─▶ CANCELLED   (취소는 WAITING·QUEUED·RUNNING에서만)
SKIPPED  (정책이 실행하지 않기로 함, 만들어질 때 끝)
```

- 끝 상태: `COMPLETED`, `FAILED`, `CANCELLED`, `SKIPPED`. 폴링은 5초 이상 간격으로 하고 이 상태에서 멈춥니다.
- QUEUED·RUNNING 취소는 202에 `cancel_requested: true`와 **같은 상태**가 옵니다. `CANCELLED`가 될 때까지 폴링합니다.
- `notebook_status`는 run이 끝난 뒤에만 봅니다.

## 5. 경로별 상세 설명

경로는 모두 `/api/v1/batch` 뒤에 붙습니다. 헤더는 `X-Api-Key`, `X-User-Id`(필수)와 3장의 헤더입니다. 필드 전체는 9장 레퍼런스와 10장 스키마에 있습니다.

### 5.1 런타임

`GET /runtimes` → `{"items": [{"type": "JUPYTER", "profile": "default"}, …]}`. 배치 등록의 `runtime`에는 이 목록의 항목 하나를 **그대로** 넣습니다. executor 게이트웨이의 `runtime.profile`에도 이 값을 씁니다.

### 5.2 스크립트와 버전

| 경로 | 본문·쿼리 | 성공 | 메모 |
| --- | --- | --- | --- |
| `POST /scripts` | multipart: `file`(.ipynb), `type`=`NOTEBOOK`, `name`? | 201 ScriptView | `Idempotency-Key` |
| `GET /scripts` | `limit`(1~100, 기본 50), `cursor`, `user_id`(마스터키) | 200 ScriptPage | |
| `GET /scripts/{script_id}` | | 200 ScriptView + `ETag` | |
| `PATCH /scripts/{script_id}` | `{"name": "…"}` | 200 ScriptView | `Idempotency-Key`, `If-Match` |
| `DELETE /scripts/{script_id}` | | 204 | `Idempotency-Key`, `If-Match`. 배치가 쓰고 있으면 409 `SCRIPT_IN_USE`, 진행 중 run이 있으면 409 `SCRIPT_HAS_ACTIVE_RUNS` |
| `POST /scripts/{script_id}/versions` | multipart: `file` | 201 VersionView (같은 바이트면 200 기존 버전) | `Idempotency-Key`. 스크립트 `revision`이 올라갑니다 |
| `GET /scripts/{script_id}/versions` | `limit`, `cursor` | 200 VersionPage (버전 번호 역순) | |
| `GET /scripts/{script_id}/versions/{version_id}` | | 200 VersionDetail (`cell_list`: 셀마다 실행 여부와 Step 번호) | |
| `GET /scripts/{script_id}/versions/{version_id}/content` | | 200 `.ipynb` 원본 바이트 | |

노트북 업로드 제한:

| 규칙 | 기본값 | 오류 |
| --- | --- | --- |
| 파일 이름 `.ipynb`, nbformat v4 JSON | — | 422 `INVALID_NOTEBOOK` |
| 파일 크기 | 10MiB | 413 `UPLOAD_TOO_LARGE` / `REQUEST_TOO_LARGE` |
| 전체 셀 수 (Markdown 포함) | 1000 | 422 `TOO_MANY_CELLS` |
| 비어 있지 않은 코드 셀 수 (executor 한도) | 100 | 422 `TOO_MANY_CELLS` |
| 코드 셀 하나의 크기 | 1MiB | 422 `CELL_TOO_LARGE` |
| 코드 셀이 하나 이상 | — | 422 `EMPTY_NOTEBOOK` |
| 언어가 적혀 있으면 Python | — | 422 `UNSUPPORTED_LANGUAGE` |

새 버전을 올려도 기존 배치는 바뀌지 않습니다. 배치를 `PATCH`해서 `script_version_number`를 바꾸거나 `null`(최신)로 다시 고정합니다.

### 5.3 배치

| 경로 | 본문·쿼리 | 성공 | 메모 |
| --- | --- | --- | --- |
| `POST /batches` | CreateBatch | 201 BatchView (`enabled: false`) | `Idempotency-Key`, `X-Project-Id`? |
| `GET /batches` | `limit`, `cursor`, `script_id`, `user_id`(마스터키) | 200 BatchPage | |
| `GET /batches/{batch_id}` | | 200 BatchView + `ETag` | |
| `PATCH /batches/{batch_id}` | UpdateBatch (바꿀 필드만) | 200 BatchView | `Idempotency-Key`, `If-Match` |
| `DELETE /batches/{batch_id}` | | 204 | `Idempotency-Key`, `If-Match`. 진행 중 run이 있으면 409 `BATCH_HAS_ACTIVE_RUNS` |
| `POST /batches/{batch_id}/enable`, `/disable` | 없음 | 200 BatchView | `Idempotency-Key`, `If-Match` |
| `GET /batches/{batch_id}/skipped-windows` | `limit`, `cursor` | 200 SkippedPage | |

CreateBatch:

```jsonc
{
  "name": "평일 08시 라인 리포트",                 // 필수, 1~255자
  "script_id": "uuid",                            // 필수
  "script_version_number": 2,                     // 선택. 없으면 등록 시점의 최신 버전
  "runtime": {"type": "JUPYTER", "profile": "default"},   // 필수. GET /runtimes 항목 그대로
  "schedule": {                                   // 선택. 없으면 수동 실행 전용 (켤 수 없음)
    "definition": {"kind": "CRON", "expression": "0 8 * * MON-FRI"},
    "timezone": "Asia/Seoul",                     // 선택, 이 값만 허용
    "start_at": null, "end_at": null              // 선택, 시간대 포함. 시작 포함, 끝 미포함
  },
  "policy": {                                     // 선택. 기본: overlap SKIP, misfire SKIP
    "overlap": {"mode": "QUEUE", "max_queued": 100},
    "misfire": {"mode": "LATEST", "grace_seconds": 300}
  }
}
```

일정 `definition` (`kind`로 구분):

```jsonc
{"kind": "ONCE", "at": "2026-12-01T09:00:00+09:00"}
{"kind": "INTERVAL", "seconds": 1800, "anchor": null}               // 60~31536000초
{"kind": "CALENDAR", "frequency": "DAILY", "at": "08:00:00"}         // at = 서울 시각, 시간대 없이
{"kind": "CALENDAR", "frequency": "WEEKLY", "at": "08:00:00", "weekdays": ["MON", "FRI"]}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "month_days": [1, 15]}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "last_day": true}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "nth_weekdays": [{"weekday": "MON", "nth": 1}]}  // nth 1~5 또는 -1
{"kind": "CRON", "expression": "*/10 9-17 * * MON-FRI"}             // 5필드 또는 @hourly 등. 초·L/W/# 없음
```

정책: 고른 `mode`가 쓰는 필드만 보냅니다(다른 필드는 422).

| 구분 | mode | 필드 (기본값) |
| --- | --- | --- |
| `overlap` (앞 run이 안 끝났을 때) | `SKIP` | — |
| | `QUEUE` | `max_queued` (100, 1~10000) |
| | `PARALLEL` | `max_concurrent` (필수, 1~100), `max_queued` (100) |
| | `REPLACE` | — (진행 중 run을 취소하고 새로 실행) |
| `misfire` (예약 시각을 놓쳤을 때) | `SKIP` | `grace_seconds` (300, 1~86400) |
| | `LATEST` | `grace_seconds` |
| | `CATCH_UP` | `grace_seconds`, `max_runs` (10, 1~1000), `max_age_seconds` (86400, 60~31536000) |

UpdateBatch(PATCH) 규칙: 바꿀 필드만 보냅니다. `{}`는 422입니다. `name`·`script_id`·`runtime`·`policy`는 `null`이 안 됩니다. `script_version_number: null`은 최신 버전으로 다시 고정, `schedule: null`은 일정 삭제(켜져 있으면 409 `SCHEDULE_REQUIRED`)입니다. **일정이 그대로면 `schedule`을 빼고 보냅니다.** 같은 일정을 다시 보내면 새 일정으로 보고 간격 실행의 주기를 지금부터 다시 셉니다. `policy`는 구간별로 합쳐지고, 다른 `mode`로 바꾸면 그 구간이 새 mode의 기본값으로 바뀝니다.

BatchView에서 화면·로직에 쓰는 필드: `user_id`(소유자), `enabled`, `can_enable`, `can_disable`, `enable_blocked_reason`, `disabled_reason`(`OWNER`·`USER_DEACTIVATED`·`TENANT_REVOKED`·null), `next_run_at`, `preview_runs`(최대 5개), `revision`, `config_number`.

### 5.4 실행 (Run)

| 경로 | 본문 | 성공 | 메모 |
| --- | --- | --- | --- |
| `POST /batches/{batch_id}/runs` | 없음 또는 `{}` | 202 RunView | `Idempotency-Key` |
| `GET /batches/{batch_id}/runs` | `limit`, `cursor` | 200 RunPage | |
| `GET /batches/{batch_id}/runs/{run_id}` | | 200 RunDetail | 5초 이상 간격으로 폴링 |
| `POST /batches/{batch_id}/runs/{run_id}/cancel` | 없음 | 202 RunView | `Idempotency-Key`. 끝난 run은 409 `NOT_CANCELLABLE` |

- 수동 실행이 동시 실행 한도에 걸리면 pr-batch는 409와 함께 `status: "SKIPPED"`, `skip_reason: "SKIPPED_CAPACITY"`인 RunView를 돌려줍니다. **이 게이트웨이에서는 이것이 `{"error": {"code": "CONFLICT", "message": "pr-batch refused the request.", "details": [], "context": {<RunView 필드>}}}`로 옵니다.** `error.context.skip_reason`으로 구분합니다.
- RunView 주요 필드: `id`, `user_id`(소유자), `status`, `skip_reason`, `failure_type`, `cancel_requested`, `trigger`(`MANUAL`·`SCHEDULED`), `scheduled_for`, `execution_id`, `notebook_status`, `result.notebook_artifact_id`, `completed_at`.
- 실행 결과 파일은 pr-batch가 주지 않습니다. `COMPLETED`면 `result.notebook_artifact_id`를 executor 게이트웨이에서 받습니다: `GET /api/v1/executor/artifacts/{notebook_artifact_id}/content`(같은 key, 같은 `X-User-Id`). 실행 상세는 `GET /api/v1/executor/executions/{execution_id}`입니다.

### 5.5 세션 노트북을 배치 스크립트로 (이 서비스의 API)

`POST /api/v1/batch/scripts/from-notebook` `{"artifact_id": "<executor NOTEBOOK artifact>", "name"?: "…"}` → 201 ScriptView(pr-batch 응답 그대로).

- 이 서비스의 채팅 세션이 만든 노트북을 `NOTEBOOK` 스크립트로 올립니다. 그 아티팩트를 볼 수 있는 **이 서비스 tenant 사용자**만 됩니다(`X-User-Id`가 이 서비스의 활성 사용자).
- 노트북이 아닌 아티팩트는 422입니다. `Idempotency-Key`는 필요 없습니다(같은 요청을 다시 보내면 같은 스크립트가 돌아옵니다).

### 5.6 배치 리포트 (이 서비스의 API)

배치 run이 `COMPLETED`(executor `SUCCEEDED`)가 되면 이 서비스가 리포트 작업을 만들어 에이전트로 결과를 분석하고, 리포트를 executor 아티팩트로 저장해 실행 노트북 끝에 붙입니다. 실패한 run은 리포트가 없습니다. **이 서비스 tenant의 배치만** 대상이고, 소유자(실행의 `context.user_id`) 것만 보입니다. key 호출자는 `X-User-Id`가 이 서비스의 활성 사용자여야 합니다.

| 경로 (`/api/v1` 뒤) | 설명 |
| --- | --- |
| `GET /batch-reports?batch_id=&execution_id=&status=&cursor=&limit=` | 최신순 목록. `status`는 `QUEUED`, `COLLECTING`(노트북 준비 대기), `GENERATING`(에이전트 작성 중), `MATERIALIZING`(저장 중), `SUCCEEDED`, `FAILED` 중 쉼표로 여러 개 |
| `GET /batch-reports/{report_id}` | 상세: `markdown`, `summary`(다음 실행이 비교할 요약), `artifact_id`(리포트 아티팩트), `error`, `failed_stage`, `owner`, `execution`(trigger·context·metadata) |
| `GET /batch-reports/{report_id}/events?types=` | 저장된 진행 이벤트(채팅 run 이벤트와 같은 모양, `run_id` = 리포트 ID). `token`·`activity`는 저장되지 않습니다 |
| `GET /batch-reports/{report_id}/stream` | SSE(`text/event-stream`). 저장된 이벤트를 먼저 보내고 실시간 이벤트를 이어 보냅니다. `Last-Event-ID` 헤더(또는 `?after=`)로 이어 받기. 15초마다 `: keep-alive` |
| `POST /batch-reports/{report_id}/retry` | `FAILED` 작업만 다시 대기열로(202). 다른 상태는 409 |

이벤트 종류: `run_status`(`queued` → `running` → [`waiting_executor`] → `succeeded`|`failed`), `token`, `activity`, `tool_call`, `artifact`(리포트·노트북), `message_final`(리포트 Markdown), `run_error`.

## 6. 예시

```http
POST /api/v1/batch/scripts
X-Api-Key: pas_live_xxxxxxxx
X-User-Id: e12345
Idempotency-Key: 1b6c2f0e-…
Content-Type: multipart/form-data; boundary=…

(file=@daily.ipynb, type=NOTEBOOK, name=Daily line report)
```

```http
POST /api/v1/batch/batches
X-Api-Key: pas_live_xxxxxxxx
X-User-Id: e12345
X-Project-Id: project-100
Idempotency-Key: 8d1f…
Content-Type: application/json

{"name": "Weekdays 08:00", "script_id": "<script id>",
 "runtime": {"type": "JUPYTER", "profile": "default"},
 "schedule": {"definition": {"kind": "CRON", "expression": "0 8 * * MON-FRI"}}}
```

```http
GET /api/v1/batch/batches/<batch id>          → 200, ETag: "1"
POST /api/v1/batch/batches/<batch id>/enable
If-Match: "1"
Idempotency-Key: 4a0e…                        → 200, enabled: true, ETag: "2"
```

마스터키로 tenant 전체 배치 중 한 사용자 것만:

```http
GET /api/v1/batch/batches?user_id=e20000
X-Api-Key: pas_live_master…
X-User-Id: e12345
```

## 7. 오류 코드

게이트웨이 오류(400·401·403·404·413·502·504)는 [00-common 6.1](00-common.md#61-게이트웨이가-내는-오류)입니다. pr-batch가 내는 코드:

| HTTP | code | 뜻 | 재시도 |
| --- | --- | --- | --- |
| 400 | `INVALID_IDENTITY` | `X-User-Id`·`user_id` 형식 오류 | 아니오 |
| 403 | `FORBIDDEN` | `user_id`가 `X-User-Id`와 다름 | 아니오 |
| 404 | `NOT_FOUND` | 없음, 다른 tenant·(일반키) 다른 사용자, 삭제됨 | 아니오 |
| 409 | `IDEMPOTENCY_CONFLICT` | 같은 키에 다른 본문 | 새 키로 |
| 409 | `REVISION_CONFLICT` | `If-Match`가 현재 revision과 다름 (`details[0].context`: `expected`, `current`) | GET 뒤 새 `ETag`와 **새 키**로 |
| 409 | `SCRIPT_IN_USE`, `SCRIPT_HAS_ACTIVE_RUNS`, `BATCH_HAS_ACTIVE_RUNS`, `SCHEDULE_REQUIRED`, `NOT_CANCELLABLE`, `OWNER_DEACTIVATED`, `TENANT_REVOKED` | 지금 상태에서 불가 | 상태를 바꾼 뒤 |
| 409 | `CONFLICT` (context에 RunView) | 수동 실행이 동시 실행 한도에 걸림 (5.4) | 앞 run이 끝난 뒤 |
| 413 | `REQUEST_TOO_LARGE`, `UPLOAD_TOO_LARGE` | 본문·파일 크기 초과 | 아니오 |
| 422 | `VALIDATION_ERROR` | 필드 누락·형식·범위 오류, 모르는 필드 | 아니오 |
| 422 | `INVALID_REVISION`, `INVALID_CURSOR`, `INVALID_POLICY`, `INVALID_NOTEBOOK`, `TOO_MANY_CELLS`, `CELL_TOO_LARGE`, `EMPTY_NOTEBOOK`, `UNSUPPORTED_LANGUAGE`, `UNKNOWN_RUNTIME`, `RUNTIME_NOT_SUPPORTED`, `NO_FUTURE_OCCURRENCE` | 값 오류 | 아니오 |
| 500 | `INTERNAL_ERROR` | pr-batch 내부 오류 (`details[0].context.error_id`) | 아니오. 담당자에게 문의 |
| 503 | `DATABASE_UNAVAILABLE`, `STORAGE_UNAVAILABLE`, `INCONSISTENT_STATE` | 일시 장애 | 예, 같은 `Idempotency-Key`로 |
| 503 | `EXECUTOR_NOT_CONFIGURED`, `RUNTIMES_NOT_CONFIGURED` | 서버 설정 누락 | 설정이 고쳐진 뒤 |

## 8. 알려진 제약

- **결과 파일은 executor 게이트웨이에서:** 배치 게이트웨이로는 run 결과 노트북을 받을 수 없습니다(5.4).
- **`Location`은 pr-batch 기준 경로:** `/api/v1/` → `/api/v1/batch/`로 바꿔 씁니다.
- **수동 실행 409의 모양:** 5.4의 `CONFLICT` 형태로 옵니다.
- **`Content-Disposition` 미전달:** 버전 원본(`…/content`)을 저장할 파일 이름은 VersionView의 이름으로 정합니다.
- **배치 리포트와 from-notebook은 이 서비스 tenant 사용자만:** 다른 tenant key는 `X-User-Id`가 이 서비스 사용자가 아니면 403입니다.

## 9. 레퍼런스: 경로별 파라미터와 응답

`X-Api-Key`, `X-User-Id`(필수), `X-Project-Id`(배치 등록만)는 표에서 뺐습니다. 모든 경로는 00-common 6.1의 게이트웨이 오류와 422를 낼 수 있습니다.

<!-- gen:begin endpoints -->
#### `GET /api/v1/batch/runtimes`

List Runtimes

- 응답 `200` (`application/json`): [RuntimeList](#schema-runtimelist)

#### `GET /api/v1/batch/scripts`

List Scripts

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| query | `limit` | integer |  | `50` | ≥ 1, ≤ 100 |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 1024 |  |
| query | `user_id` | string \| null |  |  | `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` | Reads only. Master key: narrows the tenant-wide read to this user. Standard key: may only repeat X-User-Id (anything else is 403). |

- 응답 `200` (`application/json`): [ScriptPage](#schema-scriptpage)

#### `POST /api/v1/batch/scripts`

Create Script

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |

- 요청 본문 (`multipart/form-data`): [Body_create_script_api_v1_scripts_post](#schema-body_create_script_api_v1_scripts_post)
- 응답 `201` (`application/json`): [ScriptView](#schema-scriptview)

#### `GET /api/v1/batch/scripts/{script_id}`

Get Script

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `script_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [ScriptView](#schema-scriptview)

#### `PATCH /api/v1/batch/scripts/{script_id}`

Rename Script

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `script_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |
| header | `If-Match` | string | O |  | 길이 ≤ 32 |  |

- 요청 본문 (`application/json`): [RenameScript](#schema-renamescript)
- 응답 `200` (`application/json`): [ScriptView](#schema-scriptview)

#### `DELETE /api/v1/batch/scripts/{script_id}`

Delete Script

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `script_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |
| header | `If-Match` | string | O |  | 길이 ≤ 32 |  |

- 응답 `204`: 본문 없음

#### `GET /api/v1/batch/scripts/{script_id}/versions`

List Versions

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `script_id` | string (uuid) | O |  |  |  |
| query | `limit` | integer |  | `50` | ≥ 1, ≤ 100 |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 1024 |  |

- 응답 `200` (`application/json`): [VersionPage](#schema-versionpage)

#### `POST /api/v1/batch/scripts/{script_id}/versions`

Add Version

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `script_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |

- 요청 본문 (`multipart/form-data`): [Body_add_version_api_v1_scripts__script_id__versions_post](#schema-body_add_version_api_v1_scripts__script_id__versions_post)
- 응답 `201` (`application/json`): [VersionView](#schema-versionview)

#### `GET /api/v1/batch/scripts/{script_id}/versions/{version_id}`

Get Version

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `script_id` | string (uuid) | O |  |  |  |
| path | `version_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [VersionDetail](#schema-versiondetail)

#### `GET /api/v1/batch/scripts/{script_id}/versions/{version_id}/content`

Download Version

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `script_id` | string (uuid) | O |  |  |  |
| path | `version_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/octet-stream`): string (binary)

#### `GET /api/v1/batch/batches`

List Batches

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| query | `limit` | integer |  | `50` | ≥ 1, ≤ 100 |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 1024 |  |
| query | `script_id` | string (uuid) \| null |  |  |  |  |
| query | `user_id` | string \| null |  |  | `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` | Reads only. Master key: narrows the tenant-wide read to this user. Standard key: may only repeat X-User-Id (anything else is 403). |

- 응답 `200` (`application/json`): [BatchPage](#schema-batchpage)

#### `POST /api/v1/batch/batches`

Create Batch

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |

- 요청 본문 (`application/json`): [CreateBatch](#schema-createbatch)
- 응답 `201` (`application/json`): [BatchView](#schema-batchview)

#### `GET /api/v1/batch/batches/{batch_id}`

Get Batch

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [BatchView](#schema-batchview)

#### `PATCH /api/v1/batch/batches/{batch_id}`

Update Batch

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |
| header | `If-Match` | string | O |  | 길이 ≤ 32 |  |

- 요청 본문 (`application/json`): [UpdateBatch](#schema-updatebatch)
- 응답 `200` (`application/json`): [BatchView](#schema-batchview)

#### `DELETE /api/v1/batch/batches/{batch_id}`

Delete Batch

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |
| header | `If-Match` | string | O |  | 길이 ≤ 32 |  |

- 응답 `204`: 본문 없음

#### `POST /api/v1/batch/batches/{batch_id}/enable`

Enable Batch

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |
| header | `If-Match` | string | O |  | 길이 ≤ 32 |  |

- 응답 `200` (`application/json`): [BatchView](#schema-batchview)

#### `POST /api/v1/batch/batches/{batch_id}/disable`

Disable Batch

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |
| header | `If-Match` | string | O |  | 길이 ≤ 32 |  |

- 응답 `200` (`application/json`): [BatchView](#schema-batchview)

#### `GET /api/v1/batch/batches/{batch_id}/skipped-windows`

List Skipped Windows

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| query | `limit` | integer |  | `50` | ≥ 1, ≤ 100 |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 1024 |  |

- 응답 `200` (`application/json`): [SkippedPage](#schema-skippedpage)

#### `GET /api/v1/batch/batches/{batch_id}/runs`

List Runs

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| query | `limit` | integer |  | `50` | ≥ 1, ≤ 100 |  |
| query | `cursor` | string \| null |  |  | 길이 ≤ 1024 |  |

- 응답 `200` (`application/json`): [RunPage](#schema-runpage)

#### `POST /api/v1/batch/batches/{batch_id}/runs`

Create Run

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |

- 요청 본문 (`application/json`): [ManualRun](#schema-manualrun) | null
- 응답 `202` (`application/json`): [RunView](#schema-runview)

#### `GET /api/v1/batch/batches/{batch_id}/runs/{run_id}`

Get Run

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| path | `run_id` | string (uuid) | O |  |  |  |

- 응답 `200` (`application/json`): [RunDetail](#schema-rundetail)

#### `POST /api/v1/batch/batches/{batch_id}/runs/{run_id}/cancel`

Cancel Run

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `batch_id` | string (uuid) | O |  |  |  |
| path | `run_id` | string (uuid) | O |  |  |  |
| header | `Idempotency-Key` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[!-~]+$` |  |

- 응답 `202` (`application/json`): [RunView](#schema-runview)

#### `GET /api/v1/batch-reports`

List Reports

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| query | `batch_id` | string \| null |  |  |  |  |
| query | `execution_id` | string \| null |  |  |  |  |
| query | `status` | string \| null |  |  |  |  |
| query | `limit` | integer |  | `50` | ≥ 1, ≤ 200 |  |
| query | `cursor` | string \| null |  |  |  |  |

- 응답 `200` (`application/json`): [BatchReportPage](#schema-batchreportpage)

#### `GET /api/v1/batch-reports/{report_id}`

Get Report

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `report_id` | string | O |  |  |  |

- 응답 `200` (`application/json`): [BatchReportDetail](#schema-batchreportdetail)

#### `GET /api/v1/batch-reports/{report_id}/events`

Report Events

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `report_id` | string | O |  |  |  |
| query | `types` | string \| null |  |  |  |  |

- 응답 `200` (`application/json`): [BatchReportEvents](#schema-batchreportevents)

#### `GET /api/v1/batch-reports/{report_id}/stream`

Report Stream

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `report_id` | string | O |  |  |  |
| query | `after` | integer \| null |  |  |  |  |

- 응답 `200` (`text/event-stream`): string

#### `POST /api/v1/batch-reports/{report_id}/retry`

Retry Report

| 위치 | 이름 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- | --- |
| path | `report_id` | string | O |  |  |  |

- 응답 `202` (`application/json`): [BatchReportDetail](#schema-batchreportdetail)

#### `POST /api/v1/batch/scripts/from-notebook`

Notebook To Batch Script

- 요청 본문 (`application/json`): [BatchScriptFromNotebook](#schema-batchscriptfromnotebook)
- 응답 `201` (`application/json`): [ScriptView](#schema-scriptview)
<!-- gen:end endpoints -->

## 10. 스키마

pr-batch와 이 서비스의 OpenAPI에서 만든 표입니다. pr-batch 필드 설명은 원문이고, 뜻은 5장에 적었습니다. `BatchReportEvents.items`는 채팅 run 이벤트와 같은 모양이라 그 이벤트 스키마가 함께 들어 있습니다.

<!-- gen:begin schemas -->
<a id="schema-activitydata"></a>
#### ActivityData

Slow work in progress (agent.activity); extra detail may follow.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | O |  |  |  |
| `kind` | string | O |  |  | answering \| planning \| summarizing \| report_writing \| workflow_saving |
| `state` | "started" \| "finished" \| "failed" \| "paused" | O |  |  |  |
| `label` | string \| null |  |  |  | started에만: 상태 문구 |
| `elapsed_ms` | integer \| null |  |  |  | 끝 이벤트에만 |

<a id="schema-activityevent"></a>
#### ActivityEvent

``activity`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "activity" | O |  |  |  |
| `data` | [ActivityData](#schema-activitydata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-agentswitcheddata"></a>
#### AgentSwitchedData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `agent` | "main" \| "analyst" | O |  |  |  |
| `task` | string \| null |  |  |  |  |

<a id="schema-agentswitchedevent"></a>
#### AgentSwitchedEvent

``agent_switched`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "agent_switched" | O |  |  |  |
| `data` | [AgentSwitchedData](#schema-agentswitcheddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-artifactattachment"></a>
#### ArtifactAttachment

Also the data of an ``artifact`` event.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `kind` | "report" \| "notebook" | O |  |  |  |
| `artifact_id` | string | O |  |  | /view/artifacts/{artifact_id} |
| `title` | string | O |  |  |  |
| `lab_url` | string \| null |  |  |  | 노트북을 JupyterLab에서 여는 링크 (리포트는 null) |

<a id="schema-artifactevent"></a>
#### ArtifactEvent

``artifact`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "artifact" | O |  |  |  |
| `data` | [ArtifactAttachment](#schema-artifactattachment) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-batchpage"></a>
#### BatchPage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `items` | [BatchView](#schema-batchview)[] | O |  |  |  |
| `next_cursor` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-batchreportdetail"></a>
#### BatchReportDetail

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | O |  |  |  |
| `execution_id` | string | O |  |  |  |
| `batch_id` | string \| null | O |  |  |  |
| `batch_run_id` | string \| null | O |  |  | pr-batch run (metadata.run_id) |
| `state` | "QUEUED" \| "COLLECTING" \| "GENERATING" \| "MATERIALIZING" \| "SUCCEEDED" \| "FAILED" | O |  |  |  |
| `failed_stage` | string \| null | O |  |  | FAILED일 때 멈춘 단계 |
| `title` | string \| null | O |  |  |  |
| `artifact_id` | string \| null | O |  |  | 리포트 artifact (/api/v1/artifacts/{id}) |
| `error` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `finished_at` | string (date-time) \| null | O |  |  |  |
| `owner` | [BatchReportOwner](#schema-batchreportowner) | O |  |  |  |
| `markdown` | string \| null | O |  |  |  |
| `summary` | string \| null | O |  |  | 다음 실행이 비교할 요약 |
| `execution` | object | O |  |  | 작업을 만든 executor 실행의 trigger, context, metadata |

모르는 필드는 422로 거절합니다.

<a id="schema-batchreportevents"></a>
#### BatchReportEvents

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `report_id` | string | O |  |  |  |
| `state` | "QUEUED" \| "COLLECTING" \| "GENERATING" \| "MATERIALIZING" \| "SUCCEEDED" \| "FAILED" | O |  |  |  |
| `items` | [RunStatusEvent](#schema-runstatusevent) \| [TokenEvent](#schema-tokenevent) \| [MessageFinalEvent](#schema-messagefinalevent) \| [ToolCallEvent](#schema-toolcallevent) \| [AgentSwitchedEvent](#schema-agentswitchedevent) \| [PlanApprovedEvent](#schema-planapprovedevent) \| [PlanAutoApprovedEvent](#schema-planautoapprovedevent) \| [PlanRevisedEvent](#schema-planrevisedevent) \| [ExecutionProgressEvent](#schema-executionprogressevent) \| [ExecutionCompletedEvent](#schema-executioncompletedevent) \| [HitlRequestEvent](#schema-hitlrequestevent) \| [HitlResolvedEvent](#schema-hitlresolvedevent) \| [ArtifactEvent](#schema-artifactevent) \| [MemoryUpdatedEvent](#schema-memoryupdatedevent) \| [WorkflowSavedEvent](#schema-workflowsavedevent) \| [RunErrorEvent](#schema-runerrorevent) \| [SessionTitledEvent](#schema-sessiontitledevent) \| [ActivityEvent](#schema-activityevent) \| [ContextSummarizedEvent](#schema-contextsummarizedevent)[] | O |  |  | 채팅 run 이벤트와 같은 모양 (run_id = report id) |

모르는 필드는 422로 거절합니다.

<a id="schema-batchreportowner"></a>
#### BatchReportOwner

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | O |  |  |  |
| `employee_id` | string | O |  |  |  |
| `name` | string | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-batchreportpage"></a>
#### BatchReportPage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `items` | [BatchReportRead](#schema-batchreportread)[] | O |  |  |  |
| `next_cursor` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-batchreportread"></a>
#### BatchReportRead

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | O |  |  |  |
| `execution_id` | string | O |  |  |  |
| `batch_id` | string \| null | O |  |  |  |
| `batch_run_id` | string \| null | O |  |  | pr-batch run (metadata.run_id) |
| `state` | "QUEUED" \| "COLLECTING" \| "GENERATING" \| "MATERIALIZING" \| "SUCCEEDED" \| "FAILED" | O |  |  |  |
| `failed_stage` | string \| null | O |  |  | FAILED일 때 멈춘 단계 |
| `title` | string \| null | O |  |  |  |
| `artifact_id` | string \| null | O |  |  | 리포트 artifact (/api/v1/artifacts/{id}) |
| `error` | string \| null | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `finished_at` | string (date-time) \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-batchscriptfromnotebook"></a>
#### BatchScriptFromNotebook

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `artifact_id` | string | O |  |  |  |
| `name` | string \| null |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-batchview"></a>
#### BatchView

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_at` | string (date-time) | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `created_by_client` | string \| null | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `id` | string (uuid) | O |  |  |  |
| `name` | string | O |  |  |  |
| `script_id` | string (uuid) | O |  |  |  |
| `script_version_id` | string (uuid) | O |  |  |  |
| `script_version_number` | integer | O |  |  |  |
| `runtime` | [RuntimeSpec](#schema-runtimespec) | O |  |  |  |
| `schedule` | [Schedule](#schema-schedule) \| null | O |  |  |  |
| `policy` | [Policy](#schema-policy) | O |  |  |  |
| `tenant_id` | string | O |  |  |  |
| `project_id` | string \| null | O |  |  |  |
| `user_id` | string | O |  |  |  |
| `enabled` | boolean | O |  |  |  |
| `can_enable` | boolean | O |  |  |  |
| `can_disable` | boolean | O |  |  |  |
| `enable_blocked_reason` | string \| null | O |  |  |  |
| `disabled_reason` | string \| null | O |  |  |  |
| `disabled_at` | string (date-time) \| null | O |  |  |  |
| `next_run_at` | string (date-time) \| null | O |  |  |  |
| `preview_runs` | string (date-time)[] | O |  |  |  |
| `config_number` | integer | O |  |  |  |
| `revision` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-body_add_version_api_v1_scripts__script_id__versions_post"></a>
#### Body_add_version_api_v1_scripts__script_id__versions_post

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `file` | string | O |  |  |  |

<a id="schema-body_create_script_api_v1_scripts_post"></a>
#### Body_create_script_api_v1_scripts_post

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `file` | string | O |  |  |  |
| `type` | [ScriptType](#schema-scripttype) | O |  |  |  |
| `name` | string \| null |  |  | 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$` |  |

<a id="schema-calendar"></a>
#### Calendar

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `kind` | "CALENDAR" | O |  |  |  |
| `frequency` | "DAILY" \| "WEEKLY" \| "MONTHLY" | O |  |  |  |
| `at` | string | O |  |  |  |
| `weekdays` | "MON" \| "TUE" \| "WED" \| "THU" \| "FRI" \| "SAT" \| "SUN"[] |  |  | 항목 ≤ 7 |  |
| `month_days` | integer[] |  |  | 항목 ≤ 31 |  |
| `last_day` | boolean |  | `false` |  |  |
| `nth_weekdays` | [NthWeekday](#schema-nthweekday)[] |  |  | 항목 ≤ 35 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-catchupmisfire"></a>
#### CatchUpMisfire

Run up to max_runs missed occurrences younger than max_age_seconds.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "CATCH_UP" | O |  |  |  |
| `grace_seconds` | integer |  | `300` | ≥ 1, ≤ 86400 |  |
| `max_runs` | integer |  | `10` | ≥ 1, ≤ 1000 |  |
| `max_age_seconds` | integer |  | `86400` | ≥ 60, ≤ 31536000 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-cellcounts"></a>
#### CellCounts

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `total` | integer | O |  |  |  |
| `executable` | integer | O |  |  |  |
| `skipped` | integer | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-cellentry"></a>
#### CellEntry

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `index` | integer | O |  |  |  |
| `type` | string | O |  |  |  |
| `executed` | boolean | O |  |  |  |
| `sequence` | integer \| null |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-codeapprovalrequest"></a>
#### CodeApprovalRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `interrupt_id` | string | O |  |  | command.resume.interrupt_id로 답 |
| `kind` | "input" \| "executor" \| null |  |  |  | run.waiting에만: input(사람) \| executor |
| `type` | "code_approval" | O |  |  |  |
| `purpose` | string | O |  |  |  |
| `code` | string | O |  |  |  |
| `code_level` | integer | O |  |  |  |

<a id="schema-contextsummarizeddata"></a>
#### ContextSummarizedData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `messages` | integer | O |  |  | 요약한 메시지 수 |
| `summary_chars` | integer | O |  |  |  |

<a id="schema-contextsummarizedevent"></a>
#### ContextSummarizedEvent

``context_summarized`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "context_summarized" | O |  |  |  |
| `data` | [ContextSummarizedData](#schema-contextsummarizeddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-createbatch"></a>
#### CreateBatch

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `name` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$` |  |
| `script_id` | string (uuid) | O |  |  |  |
| `script_version_number` | integer \| null |  |  | ≥ 1 |  |
| `runtime` | [RuntimeSpec](#schema-runtimespec) | O |  |  |  |
| `schedule` | [Schedule](#schema-schedule) \| null |  |  |  |  |
| `policy` | [Policy](#schema-policy) |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-cron"></a>
#### Cron

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `kind` | "CRON" | O |  |  |  |
| `expression` | string | O |  | 길이 ≥ 1, 길이 ≤ 128 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-executioncompleteddata"></a>
#### ExecutionCompletedData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `execution_id` | string | O |  |  |  |
| `results` | [StepResult](#schema-stepresult)[] | O |  |  | 실행 순서대로 |
| `error` | string \| null |  |  |  |  |

<a id="schema-executioncompletedevent"></a>
#### ExecutionCompletedEvent

``execution_completed`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "execution_completed" | O |  |  |  |
| `data` | [ExecutionCompletedData](#schema-executioncompleteddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-executionprogressdata"></a>
#### ExecutionProgressData

Relayed from the executor (``execution.*`` events).

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `event_type` | string | O |  |  |  |
| `status` | string \| null |  |  |  |  |
| `step` | object \| null |  |  |  |  |
| `error` | any |  |  |  |  |
| `reason` | string \| null |  |  |  |  |
| `paused_seconds` | number \| null |  |  |  |  |
| `finished_during_handover` | boolean \| null |  |  |  |  |

<a id="schema-executionprogressevent"></a>
#### ExecutionProgressEvent

``execution_progress`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "execution_progress" | O |  |  |  |
| `data` | [ExecutionProgressData](#schema-executionprogressdata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-executorwait"></a>
#### ExecutorWait

Not a question: the run waits for the executor (resumed by events).

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `interrupt_id` | string | O |  |  | command.resume.interrupt_id로 답 |
| `kind` | "input" \| "executor" \| null |  |  |  | run.waiting에만: input(사람) \| executor |
| `type` | "executor_wait" | O |  |  |  |
| `execution_id` | string | O |  |  |  |
| `operation_id` | string \| null | O |  |  | 기다리는 작업. null이면 실행 종료(노트북 확정)를 기다림 |
| `steps` | string[] |  |  |  |  |

<a id="schema-hitlrequestevent"></a>
#### HitlRequestEvent

``hitl_request`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "hitl_request" | O |  |  |  |
| `data` | [QuestionRequest](#schema-questionrequest) \| [PlanApprovalRequest](#schema-planapprovalrequest) \| [CodeApprovalRequest](#schema-codeapprovalrequest) \| [WorkflowSaveRequest](#schema-workflowsaverequest) \| [ExecutorWait](#schema-executorwait) | O |  |  | 구분 필드 `type`. |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-hitlresolveddata"></a>
#### HitlResolvedData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `interrupt_id` | string \| null | O |  |  |  |

<a id="schema-hitlresolvedevent"></a>
#### HitlResolvedEvent

``hitl_resolved`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "hitl_resolved" | O |  |  |  |
| `data` | [HitlResolvedData](#schema-hitlresolveddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-inputslot"></a>
#### InputSlot

A value the user provides (``source: input``).

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `key` | string | O |  |  |  |
| `tool` | string | O |  |  |  |
| `param` | string | O |  |  |  |
| `type` | string \| null |  |  |  |  |
| `required` | boolean | O |  |  |  |
| `value` | any |  |  |  |  |

<a id="schema-interval"></a>
#### Interval

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `kind` | "INTERVAL" | O |  |  |  |
| `seconds` | integer | O |  | ≥ 60, ≤ 31536000 |  |
| `anchor` | string (date-time) \| null |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-latestmisfire"></a>
#### LatestMisfire

Run only the most recent missed occurrence.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "LATEST" | O |  |  |  |
| `grace_seconds` | integer |  | `300` | ≥ 1, ≤ 86400 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-manualrun"></a>
#### ManualRun

Run the selected immutable configuration without overrides.

타입: object

<a id="schema-memoryupdateddata"></a>
#### MemoryUpdatedData

A project memory topic changed (agent tool or memory worker).

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `topic` | string | O |  |  | 주제 id |
| `title` | string | O |  |  |  |
| `content` | string | O |  |  | 주제 본문 전체 (Markdown) |
| `version` | integer | O |  |  |  |
| `updated_at` | string \| null | O |  |  |  |
| `by` | "user" \| "agent" | O |  |  |  |

<a id="schema-memoryupdatedevent"></a>
#### MemoryUpdatedEvent

``memory_updated`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "memory_updated" | O |  |  |  |
| `data` | [MemoryUpdatedData](#schema-memoryupdateddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-messagefinaldata"></a>
#### MessageFinalData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `content` | string | O |  |  | 확정 답변 (Markdown) |

<a id="schema-messagefinalevent"></a>
#### MessageFinalEvent

``message_final`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "message_final" | O |  |  |  |
| `data` | [MessageFinalData](#schema-messagefinaldata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-misfirepatch"></a>
#### MisfirePatch

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "SKIP" \| "LATEST" \| "CATCH_UP" \| null |  |  |  |  |
| `grace_seconds` | integer \| null |  |  | ≥ 1, ≤ 86400 |  |
| `max_runs` | integer \| null |  |  | ≥ 1, ≤ 1000 |  |
| `max_age_seconds` | integer \| null |  |  | ≥ 60, ≤ 31536000 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-nthweekday"></a>
#### NthWeekday

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `weekday` | "MON" \| "TUE" \| "WED" \| "THU" \| "FRI" \| "SAT" \| "SUN" | O |  |  |  |
| `nth` | 1 \| 2 \| 3 \| 4 \| 5 \| -1 | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-once"></a>
#### Once

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `kind` | "ONCE" | O |  |  |  |
| `at` | string (date-time) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-overlappatch"></a>
#### OverlapPatch

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "SKIP" \| "QUEUE" \| "PARALLEL" \| "REPLACE" \| null |  |  |  |  |
| `max_concurrent` | integer \| null |  |  | ≥ 1, ≤ 100 |  |
| `max_queued` | integer \| null |  |  | ≥ 1, ≤ 10000 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-paralleloverlap"></a>
#### ParallelOverlap

Run up to max_concurrent at once; extra runs wait (max_queued).

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "PARALLEL" | O |  |  |  |
| `max_concurrent` | integer | O |  | ≥ 1, ≤ 100 |  |
| `max_queued` | integer |  | `100` | ≥ 1, ≤ 10000 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-paramref"></a>
#### ParamRef

Where a ``tool_output`` parameter takes its value from.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `call` | integer \| null | O |  |  | 앞 호출의 번호 (calls[].index) |
| `tool` | string \| null | O |  |  |  |
| `output` | string | O |  |  |  |

<a id="schema-planapprovalrequest"></a>
#### PlanApprovalRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `interrupt_id` | string | O |  |  | command.resume.interrupt_id로 답 |
| `kind` | "input" \| "executor" \| null |  |  |  | run.waiting에만: input(사람) \| executor |
| `type` | "plan_approval" | O |  |  |  |
| `candidates` | [PlanCandidate](#schema-plancandidate)[] | O |  |  |  |
| `allow_reject_templates` | boolean |  | `false` |  | 후보가 모두 등록된 워크플로우(source 있음)일 때만 true: action "reject_templates"로 추천을 거절하고 새 계획을 요청할 수 있음 |

<a id="schema-planapproveddata"></a>
#### PlanApprovedData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `plan_id` | string | O |  |  |  |
| `title` | string | O |  |  |  |
| `document` | object | O |  |  | Workflow 1.0 문서 |

<a id="schema-planapprovedevent"></a>
#### PlanApprovedEvent

``plan_approved`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "plan_approved" | O |  |  |  |
| `data` | [PlanApprovedData](#schema-planapproveddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-planautoapproveddata"></a>
#### PlanAutoApprovedData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `title` | string | O |  |  |  |
| `source` | [WorkflowSource](#schema-workflowsource) \| null |  |  |  |  |

<a id="schema-planautoapprovedevent"></a>
#### PlanAutoApprovedEvent

``plan_auto_approved`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "plan_auto_approved" | O |  |  |  |
| `data` | [PlanAutoApprovedData](#schema-planautoapproveddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-plancall"></a>
#### PlanCall

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `index` | integer | O |  |  | 계획 안의 호출 번호 (#0, #1 ...) |
| `key` | string | O |  |  | <step>.<tool> |
| `skill` | string | O |  |  |  |
| `skill_description` | string |  | `""` |  |  |
| `tool` | string | O |  |  |  |
| `summary` | string |  | `""` |  |  |
| `execution` | "always" \| "conditional" | O |  |  |  |
| `condition` | string \| null |  |  |  |  |
| `params` | [PlanParam](#schema-planparam)[] | O |  |  |  |

<a id="schema-plancandidate"></a>
#### PlanCandidate

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `title` | string | O |  |  |  |
| `rationale` | string |  | `""` |  |  |
| `source` | [WorkflowSource](#schema-workflowsource) \| null |  |  |  |  |
| `document` | object | O |  |  | Workflow 1.0 문서 (core/workflows/workflow_schema_1.0.json) |
| `calls` | [PlanCall](#schema-plancall)[] | O |  |  |  |
| `input_slots` | [InputSlot](#schema-inputslot)[] | O |  |  |  |
| `input_values` | object |  |  |  | 요청에서 이미 정해진 입력값 |

<a id="schema-planparam"></a>
#### PlanParam

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `name` | string | O |  |  |  |
| `key` | string | O |  |  | <step>.<tool>.<param>: input_values·overrides의 키 |
| `type` | string \| null | O |  |  | tool 시그니처의 타입 표기 |
| `required` | boolean | O |  |  |  |
| `doc` | string |  | `""` |  |  |
| `source` | "literal" \| "input" \| "tool_output" \| "default" | O |  |  | literal: Agent가 정한 값 (overrides로 수정), input: 사용자가 채울 칸 (input_values), tool_output: 앞 호출의 결과, default: tool 기본값 (overrides로 수정) |
| `value` | any |  |  |  |  |
| `default` | string \| null |  |  |  | source가 default일 때 |
| `ref` | [ParamRef](#schema-paramref) \| null |  |  |  | source가 tool_output일 때 |

<a id="schema-planreviseddata"></a>
#### PlanRevisedData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `call` | integer | O |  |  | 고친 호출 번호 |
| `args` | object | O |  |  |  |

<a id="schema-planrevisedevent"></a>
#### PlanRevisedEvent

``plan_revised`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "plan_revised" | O |  |  |  |
| `data` | [PlanRevisedData](#schema-planreviseddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-policy"></a>
#### Policy

Overlap and misfire handling; manual runs also follow overlap.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `overlap` | [SkipOverlap](#schema-skipoverlap) \| [QueueOverlap](#schema-queueoverlap) \| [ParallelOverlap](#schema-paralleloverlap) \| [ReplaceOverlap](#schema-replaceoverlap) |  |  |  | 구분 필드 `mode`. |
| `misfire` | [SkipMisfire](#schema-skipmisfire) \| [LatestMisfire](#schema-latestmisfire) \| [CatchUpMisfire](#schema-catchupmisfire) |  |  |  | 구분 필드 `mode`. |

모르는 필드는 422로 거절합니다.

<a id="schema-policypatch"></a>
#### PolicyPatch

Partial policy update; omitted values keep their current value.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `overlap` | [OverlapPatch](#schema-overlappatch) \| null |  |  |  |  |
| `misfire` | [MisfirePatch](#schema-misfirepatch) \| null |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-questionfield"></a>
#### QuestionField

A structured input the agent asks for (written by the model).

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `key` | string | O |  |  |  |
| `label` | string \| null |  |  |  |  |
| `type` | string \| null |  |  |  | string \| number \| date \| list |
| `required` | boolean |  | `false` |  |  |

<a id="schema-questionrequest"></a>
#### QuestionRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `interrupt_id` | string | O |  |  | command.resume.interrupt_id로 답 |
| `kind` | "input" \| "executor" \| null |  |  |  | run.waiting에만: input(사람) \| executor |
| `type` | "question" | O |  |  |  |
| `question` | string | O |  |  |  |
| `options` | string[] |  |  |  | 버튼으로 보여줄 선택지 |
| `fields` | [QuestionField](#schema-questionfield)[] |  |  |  |  |

<a id="schema-queueoverlap"></a>
#### QueueOverlap

Wait in order; beyond max_queued the run is SKIPPED (capacity).

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "QUEUE" | O |  |  |  |
| `max_queued` | integer |  | `100` | ≥ 1, ≤ 10000 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-renamescript"></a>
#### RenameScript

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `name` | string | O |  | 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$` |  |

모르는 필드는 422로 거절합니다.

<a id="schema-replaceoverlap"></a>
#### ReplaceOverlap

Cancel running/waiting runs; start the new one once they stop.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "REPLACE" | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-resultrefs"></a>
#### ResultRefs

Executor artifact IDs; download via Executor after ownership check.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `notebook_artifact_id` | string \| null |  |  |  |  |

<a id="schema-rundetail"></a>
#### RunDetail

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_at` | string (date-time) | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `created_by_client` | string \| null | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `id` | string (uuid) | O |  |  |  |
| `batch_id` | string (uuid) | O |  |  |  |
| `user_id` | string | O |  |  |  |
| `script_id` | string (uuid) | O |  |  |  |
| `script_version_id` | string (uuid) | O |  |  |  |
| `config_number` | integer | O |  |  |  |
| `runtime` | object | O |  |  |  |
| `snapshot` | object | O |  |  |  |
| `trigger` | string | O |  |  |  |
| `scheduled_for` | string (date-time) \| null | O |  |  |  |
| `status` | string | O |  |  |  |
| `skip_reason` | string \| null | O |  |  |  |
| `cancel_requested` | boolean | O |  |  |  |
| `cancel_source` | string \| null | O |  |  |  |
| `cancel_reason` | string \| null | O |  |  |  |
| `execution_id` | string (uuid) \| null | O |  |  |  |
| `operation_id` | string (uuid) \| null | O |  |  |  |
| `execution_status` | string \| null | O |  |  |  |
| `observed_version` | integer \| null | O |  |  |  |
| `failure_type` | string \| null | O |  |  |  |
| `notebook_status` | string \| null | O |  |  |  |
| `last_error` | string \| null | O |  |  |  |
| `artifacts` | object[] | O |  |  |  |
| `attempts` | object[] | O |  |  |  |
| `retry_info` | object \| null | O |  |  |  |
| `result` | [ResultRefs](#schema-resultrefs) |  | `{}` |  |  |
| `submitted_at` | string (date-time) \| null | O |  |  |  |
| `started_at` | string (date-time) \| null | O |  |  |  |
| `finished_at` | string (date-time) \| null | O |  |  |  |
| `observed_at` | string (date-time) \| null | O |  |  |  |
| `completed_at` | string (date-time) \| null | O |  |  |  |
| `steps` | [StepView](#schema-stepview)[] | O |  |  |  |

<a id="schema-runerrordata"></a>
#### RunErrorData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `message` | string | O |  |  |  |

<a id="schema-runerrorevent"></a>
#### RunErrorEvent

``run_error`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "run_error" | O |  |  |  |
| `data` | [RunErrorData](#schema-runerrordata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-runpage"></a>
#### RunPage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `items` | [RunView](#schema-runview)[] | O |  |  |  |
| `next_cursor` | string \| null | O |  |  |  |

<a id="schema-runstatusdata"></a>
#### RunStatusData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `status` | "queued" \| "running" \| "waiting_input" \| "waiting_executor" \| "succeeded" \| "failed" \| "cancelled" | O |  |  |  |
| `execution_id` | string \| null |  |  |  |  |
| `operation_id` | string \| null |  |  |  |  |
| `steps` | string[] \| null |  |  |  |  |

<a id="schema-runstatusevent"></a>
#### RunStatusEvent

``run_status`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "run_status" | O |  |  |  |
| `data` | [RunStatusData](#schema-runstatusdata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-runview"></a>
#### RunView

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_at` | string (date-time) | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `created_by_client` | string \| null | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `id` | string (uuid) | O |  |  |  |
| `batch_id` | string (uuid) | O |  |  |  |
| `user_id` | string | O |  |  |  |
| `script_id` | string (uuid) | O |  |  |  |
| `script_version_id` | string (uuid) | O |  |  |  |
| `config_number` | integer | O |  |  |  |
| `runtime` | object | O |  |  |  |
| `snapshot` | object | O |  |  |  |
| `trigger` | string | O |  |  |  |
| `scheduled_for` | string (date-time) \| null | O |  |  |  |
| `status` | string | O |  |  |  |
| `skip_reason` | string \| null | O |  |  |  |
| `cancel_requested` | boolean | O |  |  |  |
| `cancel_source` | string \| null | O |  |  |  |
| `cancel_reason` | string \| null | O |  |  |  |
| `execution_id` | string (uuid) \| null | O |  |  |  |
| `operation_id` | string (uuid) \| null | O |  |  |  |
| `execution_status` | string \| null | O |  |  |  |
| `observed_version` | integer \| null | O |  |  |  |
| `failure_type` | string \| null | O |  |  |  |
| `notebook_status` | string \| null | O |  |  |  |
| `last_error` | string \| null | O |  |  |  |
| `artifacts` | object[] | O |  |  |  |
| `attempts` | object[] | O |  |  |  |
| `retry_info` | object \| null | O |  |  |  |
| `result` | [ResultRefs](#schema-resultrefs) |  | `{}` |  |  |
| `submitted_at` | string (date-time) \| null | O |  |  |  |
| `started_at` | string (date-time) \| null | O |  |  |  |
| `finished_at` | string (date-time) \| null | O |  |  |  |
| `observed_at` | string (date-time) \| null | O |  |  |  |
| `completed_at` | string (date-time) \| null | O |  |  |  |

<a id="schema-runtimelist"></a>
#### RuntimeList

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `items` | [RuntimeSpec](#schema-runtimespec)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-runtimespec"></a>
#### RuntimeSpec

Same shape as the Executor's execution `runtime` object.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `type` | "JUPYTER" |  | `"JUPYTER"` |  |  |
| `profile` | string | O |  | 길이 ≥ 1, 길이 ≤ 128, `^[^\x00-\x1f\x7f]+$` |  |

모르는 필드는 422로 거절합니다.

<a id="schema-schedule"></a>
#### Schedule

When a batch runs. Policies live separately in Policy.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `definition` | [Once](#schema-once) \| [Interval](#schema-interval) \| [Calendar](#schema-calendar) \| [Cron](#schema-cron) | O |  |  | 구분 필드 `kind`. |
| `timezone` | "Asia/Seoul" |  | `"Asia/Seoul"` |  |  |
| `start_at` | string (date-time) \| null |  |  |  |  |
| `end_at` | string (date-time) \| null |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-scriptpage"></a>
#### ScriptPage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `items` | [ScriptView](#schema-scriptview)[] | O |  |  |  |
| `next_cursor` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-scripttype"></a>
#### ScriptType

값: `NOTEBOOK`

<a id="schema-scriptview"></a>
#### ScriptView

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_at` | string (date-time) | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `created_by_client` | string \| null | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `id` | string (uuid) | O |  |  |  |
| `name` | string | O |  |  |  |
| `type` | [ScriptType](#schema-scripttype) | O |  |  |  |
| `user_id` | string | O |  |  |  |
| `revision` | integer | O |  |  |  |
| `latest_version` | [VersionView](#schema-versionview) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-sessiontitleddata"></a>
#### SessionTitledData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `title` | string | O |  |  |  |

<a id="schema-sessiontitledevent"></a>
#### SessionTitledEvent

``session_titled`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "session_titled" | O |  |  |  |
| `data` | [SessionTitledData](#schema-sessiontitleddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-skipmisfire"></a>
#### SkipMisfire

Drop missed occurrences.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "SKIP" | O |  |  |  |
| `grace_seconds` | integer |  | `300` | ≥ 1, ≤ 86400 |  |

모르는 필드는 422로 거절합니다.

<a id="schema-skipoverlap"></a>
#### SkipOverlap

Record the new run as SKIPPED (OVERLAP).

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `mode` | "SKIP" | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-skippedpage"></a>
#### SkippedPage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `items` | [SkippedView](#schema-skippedview)[] | O |  |  |  |
| `next_cursor` | string \| null | O |  |  |  |

<a id="schema-skippedview"></a>
#### SkippedView

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_at` | string (date-time) | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `created_by_client` | string \| null | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `id` | string (uuid) | O |  |  |  |
| `batch_id` | string (uuid) | O |  |  |  |
| `config_number` | integer | O |  |  |  |
| `from_at` | string (date-time) | O |  |  |  |
| `until_at` | string (date-time) | O |  |  |  |
| `occurrences` | integer | O |  |  |  |
| `reason` | string | O |  |  |  |

<a id="schema-stepresult"></a>
#### StepResult

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `call` | integer \| null |  |  |  | 계획의 호출 번호 (직접 작성한 코드는 null) |
| `tool` | string \| null |  |  |  |  |
| `id` | string \| null |  |  |  | 직접 작성한 코드의 id |
| `status` | string | O |  |  | SUCCEEDED \| FAILED \| ... \| NOT_RUN |
| `observations` | any[] |  |  |  | 변수 요약 (데이터에 따라 모양이 다름) |
| `stdout` | string |  | `""` |  |  |
| `images` | string[] |  |  |  | GET /sessions/{id}/outputs?execution_id=&path= 의 path |
| `error` | any |  |  |  |  |

<a id="schema-stepview"></a>
#### StepView

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `sequence` | integer | O |  |  |  |
| `original_index` | integer | O |  |  |  |
| `source_sha256` | string | O |  |  |  |
| `step_id` | string (uuid) \| null | O |  |  |  |
| `status` | string \| null | O |  |  |  |
| `result_ref` | object \| null | O |  |  |  |

<a id="schema-tokendata"></a>
#### TokenData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `text` | string | O |  |  |  |

<a id="schema-tokenevent"></a>
#### TokenEvent

``token`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "token" | O |  |  |  |
| `data` | [TokenData](#schema-tokendata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-toolcalldata"></a>
#### ToolCallData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `name` | string | O |  |  |  |
| `args` | object | O |  |  | 긴 값은 잘려 있음 |
| `label` | string |  | `""` |  | 화면에 보일 진행 문구 (예: '실행 계획 작성') |

<a id="schema-toolcallevent"></a>
#### ToolCallEvent

``tool_call`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "tool_call" | O |  |  |  |
| `data` | [ToolCallData](#schema-toolcalldata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-updatebatch"></a>
#### UpdateBatch

Only fields present in the request change; schedule=null removes.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `name` | string \| null |  |  | 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$` |  |
| `script_id` | string (uuid) \| null |  |  |  |  |
| `script_version_number` | integer \| null |  |  | ≥ 1 |  |
| `runtime` | [RuntimeSpec](#schema-runtimespec) \| null |  |  |  |  |
| `schedule` | [Schedule](#schema-schedule) \| null |  |  |  |  |
| `policy` | [PolicyPatch](#schema-policypatch) \| null |  |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-versiondetail"></a>
#### VersionDetail

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_at` | string (date-time) | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `created_by_client` | string \| null | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `id` | string (uuid) | O |  |  |  |
| `script_id` | string (uuid) | O |  |  |  |
| `version_number` | integer | O |  |  |  |
| `filename` | string | O |  |  |  |
| `sha256` | string | O |  |  |  |
| `code_hash` | string | O |  |  |  |
| `size_bytes` | integer | O |  |  |  |
| `cells` | [CellCounts](#schema-cellcounts) | O |  |  |  |
| `cell_list` | [CellEntry](#schema-cellentry)[] | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-versionpage"></a>
#### VersionPage

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `items` | [VersionView](#schema-versionview)[] | O |  |  |  |
| `next_cursor` | string \| null | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-versionview"></a>
#### VersionView

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `created_at` | string (date-time) | O |  |  |  |
| `created_by` | string \| null | O |  |  |  |
| `created_by_client` | string \| null | O |  |  |  |
| `updated_at` | string (date-time) | O |  |  |  |
| `updated_by` | string \| null | O |  |  |  |
| `updated_by_client` | string \| null | O |  |  |  |
| `id` | string (uuid) | O |  |  |  |
| `script_id` | string (uuid) | O |  |  |  |
| `version_number` | integer | O |  |  |  |
| `filename` | string | O |  |  |  |
| `sha256` | string | O |  |  |  |
| `code_hash` | string | O |  |  |  |
| `size_bytes` | integer | O |  |  |  |
| `cells` | [CellCounts](#schema-cellcounts) | O |  |  |  |

모르는 필드는 422로 거절합니다.

<a id="schema-workflowsaverequest"></a>
#### WorkflowSaveRequest

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `interrupt_id` | string | O |  |  | command.resume.interrupt_id로 답 |
| `kind` | "input" \| "executor" \| null |  |  |  | run.waiting에만: input(사람) \| executor |
| `type` | "workflow_save" | O |  |  |  |
| `name` | string | O |  |  |  |
| `user_queries` | string[] | O |  |  |  |
| `tags` | string[] |  |  |  |  |
| `document` | object | O |  |  | Workflow 1.0 문서 |
| `excluded_custom_steps` | integer |  | `0` |  | 워크플로우에 넣지 않은 직접 작성 코드 수 |

<a id="schema-workflowsaveddata"></a>
#### WorkflowSavedData

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `workflow_id` | string | O |  |  |  |
| `name` | string | O |  |  |  |

<a id="schema-workflowsavedevent"></a>
#### WorkflowSavedEvent

``workflow_saved`` event

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `id` | integer | O |  |  |  |
| `type` | "workflow_saved" | O |  |  |  |
| `data` | [WorkflowSavedData](#schema-workflowsaveddata) | O |  |  |  |
| `created_at` | string (date-time) | O |  |  |  |

<a id="schema-workflowsource"></a>
#### WorkflowSource

The registered workflow a candidate plan comes from.

| 필드 | 타입 | 필수 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `workflow_id` | string | O |  |  |  |
| `revision` | integer | O |  |  |  |
| `name` | string | O |  |  |  |
| `similarity` | number \| null |  |  |  | 이번 턴의 워크플로우 검색에서 서버가 잰 유사도 (0~1). 임베딩 없이 모델이 고른 검색이거나 검색 없이 쓰인 워크플로우면 null |
<!-- gen:end schemas -->

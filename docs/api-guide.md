# 프론트엔드 연동 가이드 (API v1)

기준 경로는 `/api/v1`입니다. 전체 스키마는 서비스의 `/docs`(Swagger)와 `/openapi.json`에서 확인할 수 있습니다. 내부망 규정상 dev·stg·prd에서는 꺼져 있고(`DOCS_ENABLED: false`), 로컬(docker compose)에서만 켜집니다. 동작하는 참고 구현은 `web/dev/index.html`(로컬·dev 환경의 `/dev/`)입니다.

## 1. 인증 (SSO)

| 순서 | 호출 | 설명 |
| --- | --- | --- |
| 1 | 브라우저 이동 `GET /api/v1/auth/login/sso?return_to=/` | XHR이 아니라 페이지 이동으로 호출합니다. SSO를 거쳐 `FRONTEND_ORIGIN + return_to`로 돌아옵니다. 최초 로그인이면 User와 기본 Project가 생성됩니다. |
| 2 | `GET /api/v1/auth/session` | `{user_id, csrf_token, expires_at}`. 401이면 1번으로 이동합니다. |
| 3 | 이후 모든 호출 | `credentials: "include"`로 쿠키를 보냅니다. GET 외 요청에는 `X-CSRF-Token: <csrf_token>` 헤더가 필요합니다. |
| - | `POST /api/v1/auth/logout` | 서비스 세션만 종료합니다(SSO 전체 로그아웃 아님). |

`GET /api/v1/users/me` → `{user, default_project_id, can_switch_role}`

`GET /api/v1/users/lookup?ids=a,b` → `{id: {id, employee_id, name, department}}`. executor 실행의 `context.user_id`처럼 화면에 나오는 사용자 ID를 이름·사번으로 바꿀 때 씁니다(한 번에 200개까지, 일반 사용자는 본인 ID만, 관리자는 전체).

`POST /api/v1/auth/dev/role` `{role: "user" | "admin"}`: 로컬 개발 로그인(`APP_ENV` 비움, `SSO_ADAPTER=dev`)에서만 있는 API로, 현재 사용자를 관리자와 일반 사용자 사이에서 바꿉니다(`can_switch_role`이 true일 때만). 다른 환경에서는 404입니다.

`GET /api/v1/models` → `{items: [{name, label, default, input: ["text"] | ["text","image"], max_images}]}`: 고를 수 있는 모델(설정 파일 `config.{APP_ENV}.yml`의 `models`, 로컬은 compose `MODELS`). 요청의 `model`에는 `name`을 보내고, 화면에는 `label`(없으면 `name`)을 보여 줍니다. `input`에 `image`가 있는 모델만 이미지를 받습니다.

### 다른 서비스·에이전트 (API key)

브라우저가 아닌 호출자는 쿠키 없이 관리자가 발급한 key와 사용자를 헤더로 보냅니다. 쿠키가 있으면 SSO로만 판정합니다.

| 헤더 | 규칙 |
| --- | --- |
| `X-Api-Key` | 시스템 화면 "API 키"에서 발급(`pas_live_…`, 로컬·dev `pas_dev_…`). 모르는·대기(pending)·폐기된 key는 401 `INVALID_API_KEY` |
| `X-User-Id` | 우리 사용자의 `users.id` 또는 사번(우리가 `users.id`로 바꿔 넘김). 없거나 형식 오류 400 `INVALID_IDENTITY`, 미등록·비활성 사용자 403. 단, 다른 tenant 키가 executor·배치 게이트웨이를 부를 때는 그 호출자의 사용자 ID를 형식만 보고 그대로 넘깁니다 |
| `X-Project-Id`, `X-Session-Id` | 선택. 경로의 프로젝트·세션과 다르면 400. executor 입구에서는 그 호출자의 tenant가 우리면 멤버십을 확인하고, 다른 tenant면 형식만 봅니다 |

Swagger(`/docs`)에서는 Authorize 버튼에 `X-Api-Key`·`X-User-Id`가 있고, 각 API에 `X-Project-Id`·`X-Session-Id` 입력칸이 있습니다. 같은 브라우저에 SSO 로그인 쿠키가 있으면 쿠키가 우선이라 헤더는 무시됩니다. 관리자 API(`/admin/...`)는 key로 부를 수 없습니다(403). key 요청은 감사 로그(`api_service.audit`)에 남습니다. 로컬·dev의 `AUTH_MODE=header`에서는 key 없이 `X-User-Id`만으로 부를 수 있습니다.

관리자용: `GET /api/v1/admin/api-clients`, `POST /api/v1/admin/api-clients` `{name, tenant?, description?}` → `{client, api_key}`(key 원문은 이때 한 번만), `POST /api/v1/admin/api-clients/{id}/activate`, `/revoke`. 우리 tenant 클라이언트는 바로 active, 다른 tenant는 executor·pr-batch의 `allowed_tenants`에 반영된 뒤 활성화합니다.

**오류 응답:** 모든 오류는 executor와 같은 모양입니다. executor·배치 게이트웨이로 받은 오류도 이 모양으로 옵니다.

```json
{"error": {
  "code": "INVALID_BODY",
  "message": "Invalid request.",
  "details": [{"location": ["body", "input", "content"], "type": "too_long",
               "message": "List should have at most 50 items",
               "context": {"max_length": 50}}],
  "context": {"run": {"id": "..."}}
}}
```

- `code`: 기계가 읽는 코드. executor·pr-batch와 같이 대문자 snake_case입니다(예: `SESSION_BUSY`, `REVISION_CONFLICT`). `message`: 사람이 읽는 설명.
- `details[]`: 잘못된 값마다 하나씩. `location`(요청 안의 위치, 워크플로 검증 오류는 Workflow 1.0 문서 안의 위치), `type`(이유), `message`, `context`(판단 근거 값, 예: `{"limit": 20, "requested": 23}`). 요청 값 자체는 넣지 않습니다. 요청 전체에 대한 오류면 빈 목록입니다.
- `context`: 특정 값에 묶이지 않는 정보(예: `SESSION_BUSY`의 진행 중인 `run`, `UNKNOWN_MODEL`의 `models`). 없으면 빠집니다.

**오류 코드 표:** 화면 문구는 `code`로 고릅니다. `message`는 개발자용 영문 설명이라 사용자에게 그대로 보여 주지 않는 것을 권합니다. executor·pr-batch 코드는 각 서비스 가이드를 봅니다.

| code | 상태 | 뜻 | 화면 문구 예 |
| --- | --- | --- | --- |
| `LOGIN_REQUIRED` | 401 | 로그인 필요 | (로그인으로 이동) |
| `INVALID_API_KEY` | 401 | 모르는 API key | API key를 확인하세요. |
| `INVALID_IDENTITY` | 400 | `X-User-Id`가 없거나 형식 오류 | 사용자 정보가 없습니다. |
| `FORBIDDEN` | 403 | 권한 없음(작성자·관리자 전용 등) | 권한이 없습니다. |
| `NOT_FOUND` | 404 | 없거나 볼 수 없는 대상 | 찾을 수 없습니다. |
| `CONFLICT` | 409 | 다른 곳에서 먼저 바뀜(버전 충돌), 진행 중인 대화가 있어 삭제 불가 등 | 다른 곳에서 바뀌었습니다. 새로 불러오세요. |
| `SESSION_BUSY` | 409 | 다른 턴이 진행 중 | 이전 요청을 처리하고 있습니다. 끝난 뒤 보내거나 중지하세요. |
| `NOT_WAITING` | 409 | 답할 질문이 없음 | 이미 답했거나 끝난 질문입니다. |
| `STALE_INTERRUPT` | 409 | 화면의 질문이 지금 질문과 다름 | 질문이 바뀌었습니다. 새로 불러오세요. |
| `IDEMPOTENCY_CONFLICT` | 409 | 같은 `Idempotency-Key`에 다른 본문 | (재시도 키를 새로 만듦) |
| `INVALID_BODY` | 422 | 요청 형식 오류(`details`에 칸별 이유) | 입력값을 확인하세요. |
| `INVALID_ANSWER` | 422 | 확인 답이 질문과 맞지 않음(`details`) | 입력칸을 확인하세요. |
| `INVALID_WORKFLOW` | 422 | 워크플로 문서 검증 실패(`details`) | 워크플로 내용을 확인하세요. |
| `UNKNOWN_MODEL` | 422 | 없는 모델(`context.models`) | 모델을 다시 고르세요. |
| `MODEL_NOT_MULTIMODAL` | 422 | 이미지를 못 받는 모델 | 이미지를 받을 수 있는 모델을 고르세요. |
| `INVALID_IMAGE` | 422 | 이미지가 아니거나 장수 초과 | 이미지 형식·장수를 확인하세요. |
| `IMAGE_TOO_LARGE` | 413 | 이미지 합계 크기 초과 | 이미지가 너무 큽니다. |
| `TOO_LARGE` | 413 | 요청 전체가 32MB 초과 | 요청이 너무 큽니다(최대 32MB). |
| `BAD_GATEWAY` | 502 | executor·pr-batch가 응답하지 않음 | 잠시 후 다시 시도하세요. |
| `EXECUTOR_UNAVAILABLE` | 502 | executor가 응답하지 않음 | 잠시 후 다시 시도하세요. |
| `EXECUTOR_TIMEOUT` | 504 | executor 응답 시간 초과 | 잠시 후 다시 시도하세요. |
| `EXECUTOR_ADMIN_KEY_MISSING` | 503 | 운영 key 미설정(시스템 화면) | 운영 설정이 필요합니다. |
| `BAD_REQUEST` | 400 | 그 밖의 잘못된 요청 | 요청을 확인하세요. |


## 2. 프로젝트·세션·메시지

| Method | Path | 설명 |
| --- | --- | --- |
| GET/POST | `/projects` | 목록 / 생성 `{name, description?, system_prompt?, code_level?}` |
| GET/PATCH/DELETE | `/projects/{id}` | `system_prompt`는 모든 Agent에 주입되는 프로젝트 지침입니다. 응답의 `effective_code_level`은 실제 적용되는 코드 레벨입니다. 기본 프로젝트는 삭제할 수 없고, 실행 중인 턴이 있으면 409입니다(먼저 취소). 삭제하면 아직 열려 있는 executor 실행도 취소됩니다. |
| POST | `/projects/{id}/sessions` | `{input?, title?, code_level?, model?}`. `input`이 있으면 세션을 만들고 바로 첫 턴을 시작합니다(응답 `{session, run}`). 첫 턴이 거절되면(모델 이름 오류 등) 세션도 만들지 않습니다. |
| GET | `/projects/{id}/sessions?limit=&cursor=` | 세션 목록(최근 수정순). `{items, next_cursor}`. `active_run_id`가 있으면 작업 중입니다. |
| GET/PATCH/DELETE | `/sessions/{id}` | `title`, `code_level`(1~4, null이면 프로젝트 기본값) 변경. 응답의 `effective_code_level`은 세션 → 프로젝트 → 서비스 기본값 순으로 정해진 실제 값입니다. `title_source`: `initial`(첫 메시지 앞부분) → `auto`(첫 답변 후 LLM 요약) / `user`(직접 변경, 이후 자동 변경 없음) |
| GET | `/sessions/{id}/messages?limit=&cursor=` | 대화 기록(읽기 전용). 최근 `limit`개(페이지 안에서는 오래된 → 최신 순), `next_cursor`로 더 이전 메시지. user 메시지의 `attachments`에 보낸 이미지(`{kind: image, image_id, name, width, height}`), assistant 메시지의 `attachments`에 리포트·노트북, `run_id`로 그 턴의 이벤트를 조회합니다. |
| POST | `/sessions/{id}/runs` | **에이전트 실행.** 새 턴 `{input, model?}` 또는 재개 `{command: {resume: {interrupt_id, value}}}` → 202 `{run, resumed}`. 아래 "에이전트 실행" 참고. |
| GET | `/sessions/{id}/runs?limit=&cursor=` | run 이력 `{items, next_cursor}` |
| GET | `/runs/{id}/events?types=` | 그 턴의 저장된 이벤트를 순서대로 반환(작업 단계, 계획 승인, 실행 결과, 결과물 등). 지난 대화를 다시 그릴 때 씁니다. `types=execution_completed,artifact`처럼 거를 수 있습니다. 토큰·executor 진행·activity 이벤트는 저장하지 않습니다. |
| GET | `/runs/{id}` | `status`: `queued`, `running`, `waiting_input`, `waiting_executor`, `succeeded`, `failed`, `cancelled` |
| POST | `/runs/{id}/cancel` | 취소. 실행 중인 executor 작업도 취소됩니다. |

## 에이전트 실행: `POST /sessions/{id}/runs`

본문에는 `input`과 `command` 중 **정확히 하나**를 담습니다. 선택 헤더 `Idempotency-Key`를 주면, 같은 키로 다시 보낸 요청은 처음 결과를 그대로 돌려받습니다(하루 보관, 본문이 다르면 409 `IDEMPOTENCY_CONFLICT`).

```json
// 새 턴: content는 문자열, 또는 LangChain content block 목록
{"input": {"content": "NCE 분석해줘"}, "model": "qwen38-27b-nvfp4"}
{"input": {"content": [
   {"type": "text", "text": "이 웨이퍼 맵에서 이상 패턴 찾아줘"},
   {"type": "image", "base64": "iVBOR…", "mime_type": "image/png", "name": "wafer.png"}
 ]}, "model": "qwen38-27b-nvfp4"}

// 재개: hitl_request(또는 Run.waiting)의 interrupt_id와 답(4장)
{"command": {"resume": {"interrupt_id": "…", "value": {"action": "approve", "index": 0}}}}
```

- 응답 202 `{run, resumed}`. 새 턴이면 `resumed: false`와 새 run, 재개면 `resumed: true`와 기다리던 그 run(같은 id)입니다. 진행은 SSE로 받습니다.
- **이미지:** `image/png`, `image/jpeg`, `image/webp`만, 장당 10MB, 합계 20MB, 장수는 모델의 `max_images`까지. 긴 변이 1568px를 넘으면 서버가 줄입니다. 대화 기록에서는 `GET /api/v1/images/{image_id}`로 보여 줍니다. 모델은 최근 3턴의 이미지까지 봅니다.
- **확인 대기 중에 `input`을 보내면** 그 글이 기다리던 확인에 대한 답이 됩니다: `question`은 답, `plan_approval`은 수정 요청 피드백, `code_approval`·`workflow_save`는 거절 + 그 글을 에이전트에게 전달. 응답은 `resumed: true`이고, 글은 대화 기록에 user 메시지로 남습니다.

| 상태 | code | 언제 |
| --- | --- | --- |
| 409 | `SESSION_BUSY` | 다른 턴이 돌고 있음 (`error.context.run`에 진행 중인 run) |
| 409 | `NOT_WAITING` | 재개인데 기다리는 질문이 없음 (이미 답했거나 끝남, `error.context.run`) |
| 409 | `STALE_INTERRUPT` | `interrupt_id`가 지금 질문이 아님 (오래된 화면, `error.context.run.waiting`에 현재 질문) |
| 409 | `IDEMPOTENCY_CONFLICT` | 같은 키, 다른 본문 |
| 422 | `INVALID_BODY` | `input`/`command` 둘 다 또는 둘 다 없음, 형식 오류 (`details`) |
| 422 | `INVALID_ANSWER` | 답이 질문과 맞지 않음, 예: 후보 번호 범위 밖, 필수 입력 빈칸 (`details`) |
| 422 | `UNKNOWN_MODEL` | `model`이 목록에 없음 (`error.context.models`) |
| 422 | `MODEL_NOT_MULTIMODAL` | 텍스트 전용 모델에 이미지 (`error.context.models`: 이미지 가능한 모델) |
| 422 / 413 | `INVALID_IMAGE` / `IMAGE_TOO_LARGE` | 이미지가 아니거나 형식·장수·크기 초과 |

## 목록 페이지네이션

목록 API는 `{items, next_cursor}`를 반환합니다. `next_cursor`가 있으면 그대로 `?cursor=`로 넘겨 다음(더 오래된) 페이지를 받습니다. `limit`은 1~200, 기본 50입니다.

## 요청 ID

모든 응답에 `X-Request-ID` 헤더가 붙습니다. 요청에 `X-Request-ID`(영문·숫자·`._:-`, 128자 이내)를 보내면 그 값을 그대로 쓰고, 없으면 서버가 만듭니다. 같은 값이 서버 로그의 `[...]` 칸과 executor 호출 헤더에 남으므로, 오류를 문의할 때 이 값을 함께 주면 추적이 빠릅니다.

## 3. 실시간 이벤트 (SSE)

`GET /api/v1/sessions/{id}/events` (EventSource, `withCredentials: true`)

- 각 이벤트의 `event:` 이름이 아래 type이고, `data`는 `{id?, type, run_id, data}`입니다. 안쪽 `data`의 모양은 type마다 정해져 있고, OpenAPI의 `RunEvents.items`(`<Type>Event` schema, 예: `ToolCallEvent`)에 그대로 나옵니다. 서버는 이벤트를 보내기 전에 이 모델로 검사합니다.
- `id`가 있는 이벤트는 저장되어 재연결 시 `Last-Event-ID`로 이어 받습니다. 커서 없이 연결하면 진행 중인 run의 이벤트를 처음부터 다시 받습니다. 서버가 실시간 이벤트를 놓쳤을 수 있으면(전달 지연, 내부 재연결) 스트림을 닫습니다. EventSource는 자동으로 다시 연결해 놓친 저장 이벤트를 받으니, 직접 구현한 클라이언트도 연결이 끊기면 `Last-Event-ID`로 다시 연결해야 합니다.
- `token`은 저장하지 않는 실시간 이벤트입니다. 완료되면 `message_final`로 확정 답변이 옵니다.
- `token`으로 흘러온 글 뒤에 `tool_call`이 오면 그 글은 사용자에게 하는 답이 아니라 도구를 부르기 전의 중간 출력입니다("스킬을 확인하겠습니다" 같은 진행 멘트). 채팅 답변에서 빼고 단계 표시 아래 접힌 영역 등에 따로 보여 줍니다. 사용자에게 하는 말은 `message_final` 하나이고, 지난 대화를 다시 열 때도 이것만 메시지로 남습니다.

| type | data | 화면 처리 |
| --- | --- | --- |
| `run_status` | `{status, execution_id?, operation_id?, steps?}` | 상태 표시. `waiting_executor`면 실행 중 단계 표시, `waiting_input`이면 확인 카드(입력창 글도 답으로 받음) |
| `token` | `{text}` | 답변 스트리밍. 뒤이어 `tool_call`이 오면 중간 출력으로 옮김 |
| `message_final` | `{content}` | 확정 답변 (Markdown) |
| `tool_call` | `{name, args, label}` | 백그라운드 메시지 (Agent가 하는 일). 화면에는 `label`(예: "실행 계획 작성", "분석 skill 확인 · eda")을 그대로 보여 줍니다. 도구 이름별 문구 표를 프론트가 따로 둘 필요가 없습니다 |
| `agent_switched` | `{agent: main\|analyst, task?}` | 담당 전환 표시 |
| `plan_approved`, `plan_auto_approved`, `plan_revised` | 계획 정보 | 백그라운드 메시지 |
| `execution_progress` | `{event_type, status, step, error, reason?, paused_seconds?, finished_during_handover?}` | executor 단계별 진행. `event_type`이 `execution.step_handover_started`면 실행 중인 단계를 다른 executor 워커가 넘겨받는 중(`reason`: `EXECUTOR_SHUTDOWN`\|`EXECUTOR_UNRESPONSIVE`, 커널은 계속 실행되고 코드가 다시 돌지 않음), `execution.step_handover_completed`면 넘겨받기 완료(`paused_seconds`: 멈춰 있던 초). 둘 다 정보 표시용이며 이어서 같은 단계의 `execution.step_completed`가 옵니다 |
| `execution_completed` | `{execution_id, results: [{call, tool, status, observations, stdout, images[], error}], error}` | 실행 순서대로 담긴 단계 결과. `call`은 계획의 tool 번호(사용자 코드는 null, 대신 `id`). 이미지는 5장 참고 |
| `hitl_request` | `{interrupt_id, type, ...}` | 사용자 입력 카드 (4장) |
| `hitl_resolved` | `{interrupt_id}` | 카드 닫기 |
| `artifact` | `{kind: report\|notebook, artifact_id, title, lab_url}` | 링크 `/view/artifacts/{artifact_id}`, 노트북은 `lab_url`로 JupyterLab에서 열기 (5장) |
| `memory_updated` | `{topic, title, content, version, updated_at, by: user\|agent}` | 프로젝트 메모리 주제의 본문이 바뀜(대화 중 저장 또는 백그라운드 정리). `topic`은 주제 id, `content`는 그 주제 본문 전체 |
| `workflow_saved` | `{workflow_id, name}` | 저장 알림 |
| `activity` | 시작: `{id, kind, state: "started", label, ...}` / 끝: `{id, kind, state: finished\|failed\|paused, elapsed_ms}` | 오래 걸리는 작업의 진행 표시. 시작 이벤트의 `label`(예: "이전 대화를 정리하는 중")을 상태 문구로 띄우고, 같은 `id`의 끝 이벤트가 오면 내립니다. `kind`: `answering`, `planning`(모델 호출), `summarizing`, `report_writing`, `workflow_saving`. 저장하지 않는 실시간 이벤트입니다. 코드 실행 대기는 `run_status`(waiting_executor)와 `execution_progress`로 옵니다 |
| `context_summarized` | `{messages, summary_chars}` | 이전 대화가 요약으로 정리됨. 대화 중간에 구분선으로 표시합니다(저장됨) |
| `run_error` | `{message}` | 실패 사유 |
| `session_titled` | `{title}` | 세션 제목 자동 갱신 (목록·헤더 반영) |

## 4. HITL (사용자 확인)

`hitl_request.type`별 화면과 `POST /sessions/{id}/runs`의 `command.resume.value`입니다. 질문 종류마다 답(reply) 모델이 정해져 있고 OpenAPI(`Resume.value`)에 나옵니다: `PlanApproveReply`·`PlanReviseReply`·`PlanCancelReply`(`action`으로 구분), `CodeApprovalReply`, `WorkflowSaveReply`, question은 문자열 또는 객체(`QuestionReply`).

서버는 run이 기다리는 질문 종류의 모델로 답을 검사합니다(모르는 항목, 틀린 타입은 거절). 그다음 질문 내용과 맞는지 검사합니다(후보 번호 범위, 필수 입력칸, 계획에 없는 파라미터). 맞지 않으면 422 `INVALID_ANSWER`와 `details[]`(`location`, `message`)를 돌려줍니다. `location`은 `["body", "command", "resume", "value", ...]`이고, 입력칸 키(`0.1.lot_cd`)는 한 칸으로 들어갑니다. 문자열도 객체도 아닌 값(숫자, 목록 등)은 본문 검사에서 422 `INVALID_BODY`가 됩니다.

| type | 받는 데이터 | value |
| --- | --- | --- |
| `question` | `question`, `options[]`, `fields[]` | 문자열 답변, 또는 fields가 있으면 `{<key>: 값, ...}` |
| `plan_approval` | `candidates[]`: `{title, rationale, source(워크플로우 출처 또는 null), document(Workflow 1.0), calls[], input_slots[]}`. `calls[]`: `{index, key, skill, skill_description, tool, summary, execution, condition, params[]}`, `params[]`: `{name, type, required, doc, key, source(literal\|input\|tool_output\|default), value, default, ref}` | `{"action": "approve", "index": 0, "input_values": {"0.0.lot_cd": "L1"}, "overrides": {"1.0.sample_size": 500}}` / `{"action": "revise", "feedback": "..."}` / `{"action": "cancel"}` |
| `code_approval` | `purpose`, `code`, `code_level` | `{"approve": true, "code": "수정한 코드(선택)"}` / `{"approve": false, "feedback": "..."}` |
| `workflow_save` | `name`, `user_queries[]`, `tags[]`, `document`, `excluded_custom_steps` | `{"approve": true, "name": "...", "user_queries": [...]}` / `{"approve": false}` |

`input_values`의 키는 `"<step_index>.<tool_index>.<파라미터>"`입니다. 값은 입력칸 글자 그대로 문자열로 보내도 됩니다. 서버가 파라미터 `type`에 맞춰 바꿉니다. 예를 들어 `int`이면 `"500"`을 500으로, `list`이면 `"[1, 2]"`를 목록으로, 빈 글자는 `None`을 허용하는 칸에서 null로 바꿉니다. `str` 칸은 `"123"`도 글자 그대로 둡니다. 바꿀 수 없는 값은 422 `INVALID_ANSWER`이고 `details`에 기대한 타입이 나옵니다. JSON 값(숫자, 목록)을 직접 보내도 됩니다. `required`가 true인 칸이 비어 있으면 승인되지 않습니다.

## 5. 결과물

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/view/artifacts/{artifact_id}` | 리포트(.md)·노트북(.ipynb)을 렌더링한 HTML 페이지. API 서버가 직접 제공하므로 프론트는 새 탭 링크만 걸면 됩니다(로그인 쿠키로 인증, 본인 세션 결과물이 아니면 404). 화면 안에 직접 그리려면 아래 content API를 씁니다. |
| GET | `/api/v1/artifacts/{artifact_id}` | 메타데이터 + `view_url`, 노트북이면 `lab_url` |
| GET | `/api/v1/artifacts/{artifact_id}/content` | 원본 다운로드 (executor 프록시) |
| GET | `/api/v1/sessions/{sid}/outputs?execution_id=&path=` | `execution_completed.images[]`의 그림 파일 |

`lab_url`은 노트북을 사내 JupyterLab에서 여는 링크입니다(리포트이거나 `NOTEBOOK_LAB_BASE_URL`이 비어 있으면 null). `/view/artifacts/{id}` 노트북 화면 상단에도 같은 버튼이 있습니다. 형식은 `{lab}/lab/workspaces/agentic-{사번}/tree/{경로}`로, 사용자마다 Lab workspace(탭·레이아웃 상태)가 따로 있어 다른 사람의 화면과 겹치지 않습니다. 메시지 `attachments`와 `artifact` 이벤트에도 같은 값이 들어 있습니다. Lab 로그인은 Lab 서버의 인증을 따릅니다.

## 배포 시 프론트 연동 설정

- 프론트가 다른 origin이면 `CORS_ORIGINS=["https://front.example"]`, 사이트가 다르면 `COOKIE_SAMESITE=none` + HTTPS(`COOKIE_SECURE=true`).
- `FRONTEND_ORIGIN`: 로그인 후 돌아갈 프론트 주소, `SSO_ALLOWED_RETURN_ROOTS`: 허용할 경로.

## executor 조회 (중계)와 외부 호출자 입구

`/api/v1/executor/<경로>` → executor `/api/v1/<경로>`. 응답 본문은 executor 것을 그대로 돌려줍니다(형식은 executor API 문서). 아래 경로만 열려 있고, 그 밖은 404입니다. 본문에 `context`·`tenant_id`, 목록에 `user_id`·`tenant_id`를 넣지 않습니다(범위는 헤더가 정함).

**브라우저(SSO)**

| Method | Path (`/api/v1/executor` 아래) | 권한 |
| --- | --- | --- |
| GET | `/executions?project_id=&session_id=&status=&cursor=&limit=` | 내 실행만 (`user_id`는 서버가 로그인 사용자로 고정). `project_id`·`session_id`는 내가 속한 것만 |
| GET | `/executions/{id}`, `/result`, `/steps`, `/steps/{step_id}`, `/events`, `/artifacts`, `/notebook` | 그 실행의 프로젝트 멤버 (관리자는 전부) |
| GET | `/executions/{id}/diagnostics`, `/attempts`, `/attempts/{id}`, `/attempts/{id}/steps` | 관리자 |
| GET | `/runtime-targets`, `/runtime-targets/{id}`, `/runtime-pools`, `/maintenance`, `/maintenance/runs/{id}`, `/maintenance/runs/{id}/targets` | 관리자 |
| POST | `/runtime-targets` | 관리자. 런타임 등록·수정(바로 probe) |
| POST | `/runtime-targets/{id}/probe`, `/drain`, `/activate`, `/disable`, `/purge` | 관리자. 다시 점검 / 새 작업 배정 중지(진행 중은 마저) / 배정 복귀 / 사용 중지 / 사용 중지된 대상 제거 |
| POST | `/maintenance/drain`, `/maintenance/activate`, `/maintenance/runs` | 관리자. executor 전체의 새 실행 접수 중지 / 재개 / 진행 중 실행을 멈추는 점검 작업 생성 |

runtime·maintenance 경로는 executor 운영 key(`EXECUTOR_ADMIN_API_KEY`)가 없으면 503 `EXECUTOR_ADMIN_KEY_MISSING`입니다. POST의 `actor`는 클라이언트 값 대신 서버가 요청한 관리자(`{"type": "USER", "id": <users.id>}`)로 채웁니다. executor·pr-batch에 넘기는 사용자 ID(`X-User-Id`, `context.user_id`, actor)는 모두 사번이 아닌 `users.id`(UUID)입니다. 화면에 이름·사번이 필요하면 `/users`로 찾습니다. 나머지 본문(`idempotency_key` 등)은 executor 형식 그대로입니다.

**API key 호출자** (executor를 직접 부르지 않고 여기로 부릅니다)

| Method | Path (`/api/v1/executor` 아래) |
| --- | --- |
| GET·POST | `/executions` |
| GET | `/executions/{id}`, `/result`, `/steps`, `/steps/{id}`, `/operations`, `/operations/{id}`, `/operations/{id}/result`, `/operations/{id}/steps`, `/attempts`, `/attempts/{id}`, `/attempts/{id}/steps`, `/events`, `/notebook`, `/notebook/cells/{n}` |
| POST | `/executions/{id}/operations`, `/finalize`, `/cancel`, `/retry` |
| GET·POST | `/executions/{id}/artifacts` |
| GET | `/artifacts/{id}`, `/artifacts/{id}/content` |

우리가 `X-Api-Key`(우리 executor key), `X-User-Id`, `X-Tenant-Id`(그 호출자의 tenant)를 다시 만들어 붙입니다. `X-User-Id` 없는 GET은 그 tenant 전체 조회, 없는 쓰기는 400입니다. 운영 경로와 diagnostics는 404. 이벤트는 중계하지 않습니다(`executor.events.<tenant>`를 읽거나 `/events`를 폴링).

executor가 응답하지 않으면 502 `EXECUTOR_UNAVAILABLE`, 시간 초과는 504 `EXECUTOR_TIMEOUT`입니다.

## 6. 프로젝트 공유 메모리

프로젝트 메모리는 주제(topic)마다 짧은 Markdown 본문입니다. 모든 대화의 프롬프트에 전부 들어갑니다(내용이 있는 주제마다 `## {title}`). 주제 목록은 프로젝트마다 고칠 수 있고, 고친 적 없는 프로젝트는 아래 기본 주제를 씁니다.

| id | title | description (요약) | max_chars |
| --- | --- | --- | --- |
| `overview` | Overview | 프로젝트 배경·목적·분석 대상 | 500 |
| `preferences` | Preferences | 분석 방식·보고서 형식·용어 선호 | 500 |
| `core_interests` | Core Interests | 계속 관심 두는 제품·공정·설비·지표 | 500 |
| `key_events` | Key Events | 날짜가 있는 사건·결정. 날짜(YYYY-MM-DD)로 시작, 최신이 위 | 700 |

주제는 `{id, title, description, max_chars}`입니다. 백그라운드 정리와 Agent는 제목·설명에 맞는 주제에만 내용을 넣으므로, 형식 규칙(예: 날짜로 시작)도 설명에 씁니다. 제한: 주제 1–6개, 제목 1–40자(중복 불가), 설명 200자 이하(한 줄), 주제마다 `max_chars` 100 이상, 합계는 `MEMORY_TOTAL_MAX_CHARS`(기본 2200) 이하.

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/projects/{id}/memory` | `{topics: [{topic, title, description, max_chars, content, lines[], version, updated_at}], topics_version, total_max_chars, limits}`. 주제 순서대로, 빈 주제 포함(`content: ""`, `version: 0`). `lines[]`: `{id, text, author(user\|agent), updated_at, source}` |
| GET | `/projects/{id}/memory/topics` | `{topics: [{id, title, description, max_chars}], version, updated_at, total_max_chars, limits}`. `version: 0`은 기본 주제(고친 적 없음). `limits`: `{max_topics, min_topic_chars, title_max_chars, description_max_chars, total_max_chars}`로, PUT이 받아 주는 한도입니다. 화면에서 미리 검사할 때 이 값을 씁니다(숫자를 화면에 고정하지 않음) |
| PUT | `/projects/{id}/memory/topics` | `{topics: [{id?, title, description?, max_chars, replace?}], expected_version}`. 목록 전체를 순서대로 보냅니다. **수정**: 기존 `id` 그대로 → 제목·설명·한도만 바뀌고 본문 유지(한도를 본문보다 낮춰도 됨: 그 뒤 줄이는 쓰기만 허용). **새 주제**: `id` 없음 → 새 id, 빈 본문(다음 대화부터 채워짐). **교체**: 기존 `id` + `replace: true` → 새 id·빈 본문. **삭제**: 목록에서 뺌. 교체·삭제된 본문은 이력(`topic_replaced`/`topic_removed`)에 남아 복원할 수 있습니다. 409 버전 불일치, 422 제한 위반·모르는 id |
| PUT | `/projects/{id}/memory/{topic}` | `{content, expected_version}`. 주제 본문 전체를 바꿉니다. 바뀌지 않은 줄은 작성자를 유지하고, 새로 쓰거나 고친 줄은 `author=user`. 404 없는 주제, 409 버전 불일치, 422 한도 초과 또는 `# `·`## ` 제목 줄 |
| GET | `/projects/{id}/memory/history?topic=&removed=&limit=` | 변경 이력(최신 먼저): `{id, topic, title, action(update\|delete\|revert\|migrate\|topic_removed\|topic_replaced\|topic_restored), before, after, version, replaced_by, actor{type,id}, session_id, run_id, created_at}`. `removed=true`면 교체·삭제된 주제만 |
| POST | `/projects/{id}/memory/{topic}/revert` | `{history_id, expected_version?}`. 그 변경 직전 본문으로 되돌립니다(새 버전, 이력에 `revert`로 남음) |
| POST | `/projects/{id}/memory/history/{history_id}/restore` | 교체·삭제된 주제를 그때의 제목·설명·한도·본문 그대로 목록 끝에 되살립니다(이력 `topic_restored`). 응답은 GET `/memory`와 같습니다. 개수·합계 제한을 넘으면 422(다른 주제를 줄이거나 지운 뒤 다시), 이미 있으면 409, 같은 제목이 있으면 제목 뒤에 " (복원)" |

작성자(`author`)는 기록만 합니다. Agent와 백그라운드 메모리 정리도 사용자가 쓴 줄을 고칠 수 있고, 잘못 바뀌면 이력에서 되돌립니다. Agent가 대화 중 고치면 `actor.id`가 `main`, 백그라운드 정리는 `memory_worker`입니다.

## 7. 워크플로우 (Workflow 1.0)

| Method | Path | 설명 |
| --- | --- | --- |
| POST | `/workflows` | `{document, user_queries[], tags[]}` → candidate (작성자만 보임) |
| GET | `/workflows?lifecycle=&q=&tag=` | template 전체 + 내 candidate. 가벼운 요약: `steps`(skill 순서와 tool), `call_count`, `mine` (문서 본문 없음) |
| POST | `/workflows/validate` | 문서 검증만 |
| POST | `/workflows/search` | `{query}` → 승격된 template만 유사도 순 |
| GET/PATCH/DELETE | `/workflows/{id}` | GET은 문서 전체 + `calls`(tool별 설명·파라미터 출처·앞 단계 참조, 계획 승인 화면과 같은 형식) + `mine`. PATCH는 `expected_revision` 필수. DELETE는 작성자, 또는 관리자(template·candidate 모두) |
| POST | `/workflows/{id}/promote` | candidate → template (검색·추천 대상). `WORKFLOW_PROMOTION=author`(기본)이면 작성자가 자기 워크플로를, `admin`이면 관리자만(SSO 로그인) 아무 워크플로나 승격합니다. 목록·상세의 `can_promote`가 true면 승격 버튼을 보여 주면 됩니다. `admin` 모드의 관리자(SSO)에게는 목록·상세에 다른 사람의 candidate도 보입니다. |
| POST | `/workflows/{id}/clone`, `/workflows/{id}/reindex` | |

## 8. 배치 (pr-batch 진입점)

- `/api/v1/batch/{path}` → pr-batch `/api/v1/{path}`로 그대로 중계됩니다(`Idempotency-Key`, `If-Match` 헤더 전달). 사용자 인증은 이 서비스가 처리하고, pr-batch에는 우리 key와 `X-User-Id`를 붙입니다. API key 호출자도 같은 경로를 씁니다.
- 배치 등록(`POST /batches`)에만 tenant(`X-Tenant-Id`: 브라우저는 우리, key 호출자는 그 tenant)와 프로젝트(요청의 `X-Project-Id`, 우리 tenant면 멤버만)가 붙습니다. 본문에 `tenant_id`를 넣으면 pr-batch가 422로 거부합니다. 배치의 프로젝트는 바꿀 수 없어서 옮기려면 새로 만듭니다.
- 사용자가 비활성화되면 그 사람의 배치가 꺼집니다(`disabled_reason: USER_DEACTIVATED`). 그 배치의 수동 실행은 409 `OWNER_DEACTIVATED`입니다.
- `POST /api/v1/batch/scripts/from-notebook` `{artifact_id, name?}`: 세션 노트북을 배치 스크립트로 등록합니다.
- 배치 실행의 노트북·리포트 artifact는 `/api/v1/artifacts/{id}`로 볼 수 있습니다(배치 소유자 = 실행의 `context.user_id`만).
- **일정(schedule) 보내는 법:** 요청 본문 형식은 pr-batch 가이드(공유 폴더 `batch-api-guide/pr-batch-api-guide.md`)를 따릅니다. 화면 입력을 바꿀 때 지킬 것은 아래와 같습니다.
  - 시각은 서울 시간 기준이고, `+09:00`을 붙인 ISO 8601로 보냅니다(예: `2026-11-01T09:00:00+09:00`). 브라우저의 `datetime-local` 값은 시간대가 없으므로 그대로 보내지 않습니다.
  - 간격 실행은 `{"kind": "INTERVAL", "seconds": 분×60}`, 매일 실행은 `{"kind": "CALENDAR", "frequency": "DAILY", "at": "HH:MM:SS"}`, cron은 `{"kind": "CRON", "expression": "0 9 * * MON-FRI"}`입니다.
  - 매일 실행의 기간을 날짜로 받으면 `start_at`은 시작일 `00:00:00`, `end_at`은 종료일 `23:59:59`로 보냅니다(종료일 포함).
  - **배치를 수정할 때 일정이 바뀌지 않았으면 `schedule`을 본문에서 뺍니다.** 같은 일정을 다시 보내면 pr-batch가 새 일정으로 보고 간격 실행의 주기를 지금부터 다시 셉니다.

## 9. 배치 리포트

배치 실행이 성공(`SUCCEEDED`)하면 서버가 리포트 작업을 하나 만들어 Agent로 결과를 분석하고, 리포트를 executor Artifact로 저장해 실행 노트북 끝에 붙입니다. 실패한 실행은 리포트가 없습니다. 서버가 executor 완료 이벤트를 놓친 실행도 주기적으로(기본 10분, 최근 14일) 찾아 리포트를 만듭니다. 같은 배치의 이전 실행 요약을 읽고 달라진 점을 함께 씁니다. 모두 내 배치 실행의 작업만 보입니다(`/api/v1/batch/*`와 다른 경로입니다).

| Method | Path (`/api/v1` 아래) | 설명 |
| --- | --- | --- |
| GET | `/batch-reports?batch_id=&execution_id=&status=&cursor=&limit=` | 최신순 목록. `status`는 `QUEUED`, `COLLECTING`(노트북 준비 대기), `GENERATING`(Agent 작성 중), `MATERIALIZING`, `SUCCEEDED`, `FAILED` 중 쉼표로 여러 개 |
| GET | `/batch-reports/{id}` | 상세: `markdown`, `summary`(다음 실행이 비교할 요약), `artifact_id`, `error`, `failed_stage`, `owner`(이름·사번), `execution`(trigger·context·metadata) |
| GET | `/batch-reports/{id}/events?types=` | 저장된 진행 이벤트. 채팅 `GET /runs/{id}/events`와 같은 모양(`run_id` = 리포트 id) |
| GET | `/batch-reports/{id}/stream` | SSE. 저장된 이벤트를 먼저 보내고 실시간 이벤트(`token`, `activity` 포함)를 이어서 보냅니다. `Last-Event-ID`(또는 `?after=`)로 이어 받기 |
| POST | `/batch-reports/{id}/retry` | `FAILED` 작업만 다시 대기열로. 이미 쓴 리포트가 있으면 저장만 다시 합니다 |

이벤트 종류와 `data`는 채팅 SSE와 같아서 채팅 컴포넌트를 그대로 쓸 수 있습니다: `run_status`(`queued` → `running` → [`waiting_executor`] → `succeeded`|`failed`), `token`, `activity`, `tool_call`, `artifact`(리포트·노트북), `message_final`(리포트 Markdown), `run_error`.

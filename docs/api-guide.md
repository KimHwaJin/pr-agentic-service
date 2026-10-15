# 프론트엔드 연동 가이드 (API v1)

기준 경로는 `/api/v1`입니다. 전체 스키마는 서비스의 `/docs`(Swagger)와 `/openapi.json`에서 확인할 수 있습니다. 동작하는 참고 구현은 `web/dev/index.html`(로컬·dev 환경의 `/dev/`)입니다.

## 1. 인증 (사내 SSO)

| 순서 | 호출 | 설명 |
| --- | --- | --- |
| 1 | 브라우저 이동 `GET /api/v1/auth/login/sso?return_to=/` | XHR이 아니라 페이지 이동으로 호출합니다. 사내 SSO를 거쳐 `FRONTEND_ORIGIN + return_to`로 돌아옵니다. 최초 로그인이면 User와 기본 Project가 생성됩니다. |
| 2 | `GET /api/v1/auth/session` | `{user_id, csrf_token, expires_at}`. 401이면 1번으로 이동합니다. |
| 3 | 이후 모든 호출 | `credentials: "include"`로 쿠키를 보냅니다. GET 외 요청에는 `X-CSRF-Token: <csrf_token>` 헤더가 필요합니다. |
| - | `POST /api/v1/auth/logout` | 서비스 세션만 종료합니다(사내 SSO 전체 로그아웃 아님). |

`GET /api/v1/users/me` → `{user, default_project_id, can_switch_role}`

`POST /api/v1/auth/dev/role` `{role: "user" | "admin"}`: 로컬 개발 로그인(`ENV=local`, `SSO_ADAPTER=dev`)에서만 있는 API로, 현재 사용자를 관리자와 일반 사용자 사이에서 바꿉니다(`can_switch_role`이 true일 때만). 다른 환경에서는 404입니다.

`GET /api/v1/models` → `{items: [{name, label, default, input: ["text"] | ["text","image"], max_images}]}`: 고를 수 있는 모델(설정 파일 `config.<ENV>.yml`의 `models`). 요청의 `model`에는 `name`을 보내고, 화면에는 `label`(없으면 `name`)을 보여 줍니다. `input`에 `image`가 있는 모델만 이미지를 받습니다.

**오류 응답:** 모든 오류는 `{"detail": "설명", "code": "기계가 읽는 코드", ...}`입니다. 요청 형식 오류는 `code: invalid_body`와 `errors: [{field, message}]`가 붙습니다.

## 2. 프로젝트·세션·메시지

| Method | Path | 설명 |
| --- | --- | --- |
| GET/POST | `/projects` | 목록 / 생성 `{name, description?, system_prompt?, code_level?}` |
| GET/PATCH/DELETE | `/projects/{id}` | `system_prompt`는 모든 Agent에 주입되는 프로젝트 지침입니다. 응답의 `effective_code_level`은 실제 적용되는 코드 레벨입니다. 기본 프로젝트는 삭제할 수 없습니다. |
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

본문에는 `input`과 `command` 중 **정확히 하나**를 담습니다. 선택 헤더 `Idempotency-Key`를 주면, 같은 키로 다시 보낸 요청은 처음 결과를 그대로 돌려받습니다(하루 보관, 본문이 다르면 409 `idempotency_conflict`).

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
- **확인 대기 중에 `input`을 보내면** 그 글이 기다리던 확인에 대한 답이 됩니다: `question`은 답, `plan_approval`은 수정 요청 피드백, `code_approval`·`memory_change`·`workflow_save`는 거절 + 그 글을 에이전트에게 전달. 응답은 `resumed: true`이고, 글은 대화 기록에 user 메시지로 남습니다.

| 상태 | code | 언제 |
| --- | --- | --- |
| 409 | `session_busy` | 다른 턴이 돌고 있음 (`run`에 진행 중인 run) |
| 409 | `not_waiting` | 재개인데 기다리는 질문이 없음 (이미 답했거나 끝남, `run` 포함) |
| 409 | `stale_interrupt` | `interrupt_id`가 지금 질문이 아님 (오래된 화면, `run.waiting`에 현재 질문) |
| 409 | `idempotency_conflict` | 같은 키, 다른 본문 |
| 422 | `invalid_body` | `input`/`command` 둘 다 또는 둘 다 없음, 형식 오류 (`errors`) |
| 422 | `invalid_answer` | 답이 질문과 맞지 않음, 예: 후보 번호 범위 밖, 필수 입력 빈칸 (`errors`) |
| 422 | `unknown_model` | `model`이 목록에 없음 (`models`) |
| 422 | `model_not_multimodal` | 텍스트 전용 모델에 이미지 (`models`: 이미지 가능한 모델) |
| 422 / 413 | `invalid_image` / `image_too_large` | 이미지가 아니거나 형식·장수·크기 초과 |

## 목록 페이지네이션

목록 API는 `{items, next_cursor}`를 반환합니다. `next_cursor`가 있으면 그대로 `?cursor=`로 넘겨 다음(더 오래된) 페이지를 받습니다. `limit`은 1~200, 기본 50입니다.

## 3. 실시간 이벤트 (SSE)

`GET /api/v1/sessions/{id}/events` (EventSource, `withCredentials: true`)

- 각 이벤트의 `event:` 이름이 아래 type이고, `data`는 `{id?, type, run_id, data}`입니다.
- `id`가 있는 이벤트는 저장되어 재연결 시 `Last-Event-ID`로 이어 받습니다. 커서 없이 연결하면 진행 중인 run의 이벤트를 처음부터 다시 받습니다.
- `token`은 저장하지 않는 실시간 이벤트입니다. 완료되면 `message_final`로 확정 답변이 옵니다.

| type | data | 화면 처리 |
| --- | --- | --- |
| `run_status` | `{status, execution_id?, operation_id?, steps?}` | 상태 표시. `waiting_executor`면 실행 중 단계 표시, `waiting_input`이면 확인 카드(입력창 글도 답으로 받음) |
| `token` | `{text}` | 답변 스트리밍 |
| `message_final` | `{content}` | 확정 답변 (Markdown) |
| `tool_call` | `{name, args}` | 백그라운드 메시지 (Agent가 하는 일) |
| `agent_switched` | `{agent: main\|analyst, task?}` | 담당 전환 표시 |
| `plan_approved`, `plan_auto_approved`, `plan_revised` | 계획 정보 | 백그라운드 메시지 |
| `execution_progress` | `{event_type, status, step, error}` | executor 단계별 진행 |
| `execution_completed` | `{execution_id, results: [{call, tool, status, observations, stdout, images[], error}], error}` | 실행 순서대로 담긴 단계 결과. `call`은 계획의 tool 번호(사용자 코드는 null, 대신 `id`). 이미지는 5장 참고 |
| `hitl_request` | `{interrupt_id, type, ...}` | 사용자 입력 카드 (4장) |
| `hitl_resolved` | `{interrupt_id}` | 카드 닫기 |
| `artifact` | `{kind: report\|notebook, artifact_id, title, lab_url}` | 링크 `/view/artifacts/{artifact_id}`, 노트북은 `lab_url`로 JupyterLab에서 열기 (5장) |
| `memory_updated` | `{action, item}` | 메모리 변경 알림 |
| `workflow_saved` | `{workflow_id, name}` | 저장 알림 |
| `activity` | 시작: `{id, kind, state: "started", label, ...}` / 끝: `{id, kind, state: finished\|failed\|paused, elapsed_ms}` | 오래 걸리는 작업의 진행 표시. 시작 이벤트의 `label`(예: "이전 대화를 정리하는 중")을 상태 문구로 띄우고, 같은 `id`의 끝 이벤트가 오면 내립니다. `kind`: `answering`, `planning`(모델 호출), `summarizing`, `report_writing`, `workflow_saving`. 저장하지 않는 실시간 이벤트입니다. 코드 실행 대기는 `run_status`(waiting_executor)와 `execution_progress`로 옵니다 |
| `context_summarized` | `{messages, summary_chars}` | 이전 대화가 요약으로 정리됨. 대화 중간에 구분선으로 표시합니다(저장됨) |
| `run_error` | `{message}` | 실패 사유 |
| `session_titled` | `{title}` | 세션 제목 자동 갱신 (목록·헤더 반영) |

## 4. HITL (사용자 확인)

`hitl_request.type`별 화면과 `POST /sessions/{id}/runs`의 `command.resume.value`입니다. 질문 종류마다 답 모델이 정해져 있고 OpenAPI(`Resume.value`)에 나옵니다: `PlanApprove`·`PlanRevise`·`PlanCancel`(`action`으로 구분), `CodeApprovalAnswer`, `MemoryChangeAnswer`, `WorkflowSaveAnswer`, question은 문자열 또는 객체.

서버는 run이 기다리는 질문 종류의 모델로 답을 검사합니다(모르는 항목, 틀린 타입은 거절). 그다음 질문 내용과 맞는지 검사합니다(후보 번호 범위, 필수 입력칸, 계획에 없는 파라미터). 맞지 않으면 422 `invalid_answer`와 `errors[]`(`field`, `message`)를 돌려줍니다. 문자열도 객체도 아닌 값(숫자, 목록 등)은 본문 검사에서 422 `invalid_body`가 됩니다.

| type | 받는 데이터 | value |
| --- | --- | --- |
| `question` | `question`, `options[]`, `fields[]` | 문자열 답변, 또는 fields가 있으면 `{<key>: 값, ...}` |
| `plan_approval` | `candidates[]`: `{title, rationale, source(워크플로우 출처 또는 null), document(Workflow 1.0), calls[], input_slots[]}`. `calls[]`: `{index, key, skill, skill_description, tool, summary, execution, condition, params[]}`, `params[]`: `{name, type, required, doc, key, source(literal\|input\|tool_output\|default), value, default, ref}` | `{"action": "approve", "index": 0, "input_values": {"0.0.lot_cd": "L1"}, "overrides": {"1.0.sample_size": 500}}` / `{"action": "revise", "feedback": "..."}` / `{"action": "cancel"}` |
| `code_approval` | `purpose`, `code`, `code_level` | `{"approve": true, "code": "수정한 코드(선택)"}` / `{"approve": false, "feedback": "..."}` |
| `memory_change` | `item`(현재), `proposed`, `reason` | `{"approve": true\|false}` |
| `workflow_save` | `name`, `user_queries[]`, `tags[]`, `document`, `excluded_custom_steps` | `{"approve": true, "name": "...", "user_queries": [...]}` / `{"approve": false}` |

`input_values`의 키는 `"<step_index>.<tool_index>.<파라미터>"`입니다. `required`가 true인 칸이 비어 있으면 승인되지 않습니다.

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

## executor 조회 (중계)

`/api/v1/executor/<경로>` → executor `/api/v1/<경로>`. 응답 본문은 executor 것을 그대로 돌려줍니다(형식은 executor API 문서). 아래 경로만 열려 있고, 그 밖은 404입니다.

| Method | Path (`/api/v1/executor` 아래) | 권한 |
| --- | --- | --- |
| GET | `/executions?project_id=&session_id=&status=&cursor=&limit=` | 내 실행만 (`user_id`는 서버가 로그인 사용자로 고정). `project_id`·`session_id`는 내가 속한 것만 |
| GET | `/executions/{id}`, `/result`, `/steps`, `/steps/{step_id}`, `/events`, `/artifacts`, `/notebook` | 그 실행의 프로젝트 멤버 (관리자는 전부) |
| GET | `/executions/{id}/diagnostics`, `/attempts`, `/attempts/{id}`, `/attempts/{id}/steps` | 관리자 |
| GET | `/runtime-targets`, `/runtime-targets/{id}`, `/runtime-pools`, `/maintenance`, `/maintenance/runs/{id}`, `/maintenance/runs/{id}/targets` | 관리자 |
| POST | `/runtime-targets` | 관리자. 런타임 등록·수정(바로 probe) |
| POST | `/runtime-targets/{id}/probe`, `/drain`, `/activate`, `/disable`, `/purge` | 관리자. 다시 점검 / 새 작업 배정 중지(진행 중은 마저) / 배정 복귀 / 사용 중지 / 사용 중지된 대상 제거 |
| POST | `/maintenance/drain`, `/maintenance/activate`, `/maintenance/runs` | 관리자. executor 전체의 새 실행 접수 중지 / 재개 / 진행 중 실행을 멈추는 점검 작업 생성 |

POST의 `actor`는 클라이언트 값 대신 서버가 요청한 관리자(`{"type": "USER", "id": <사번>}`)로 채웁니다. 나머지 본문(`idempotency_key` 등)은 executor 형식 그대로입니다.

executor가 응답하지 않으면 502 `executor_unavailable`입니다.

## 6. 프로젝트 공유 메모리

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/projects/{id}/memory` | `{items[], total_chars, max_chars}`. item: `{id, category, title, content, author(user\|agent), version, source}` |
| POST | `/projects/{id}/memory` | `{category, title, content}` (사용자가 쓴 항목은 Agent가 승인 없이 바꾸지 못함) |
| PATCH | `/projects/{id}/memory/{item_id}` | `{expected_version, title?, content?, category?}` — 버전이 다르면 409 |
| DELETE | `/projects/{id}/memory/{item_id}?expected_version=N` | |
| GET | `/projects/{id}/memory/history?item_id=` | 변경 이력 |

category: `background`(프로젝트 배경), `analysis_preferences`(분석 선호), `report_preferences`(보고서 선호), `shared_findings`(공유할 주요 발견)

## 7. 워크플로우 (Workflow 1.0)

| Method | Path | 설명 |
| --- | --- | --- |
| POST | `/workflows` | `{document, user_queries[], tags[]}` → candidate (작성자만 보임) |
| GET | `/workflows?lifecycle=&q=&tag=` | template 전체 + 내 candidate. 가벼운 요약: `steps`(skill 순서와 tool), `call_count`, `mine` (문서 본문 없음) |
| POST | `/workflows/validate` | 문서 검증만 |
| POST | `/workflows/search` | `{query}` → 승격된 template만 유사도 순 |
| GET/PATCH/DELETE | `/workflows/{id}` | GET은 문서 전체 + `calls`(tool별 설명·파라미터 출처·앞 단계 참조, 계획 승인 화면과 같은 형식) + `mine`. PATCH는 `expected_revision` 필수. DELETE는 작성자, 또는 관리자(template·candidate 모두) |
| POST | `/workflows/{id}/promote` | candidate → template (검색·추천 대상) |
| POST | `/workflows/{id}/clone`, `/workflows/{id}/reindex` | |

## 8. 배치 (pr-batch 진입점)

- `/api/v1/batch/{path}` → pr-batch `/api/v1/{path}`로 그대로 중계됩니다(`Idempotency-Key`, `If-Match` 헤더 전달). 사용자 인증은 이 서비스가 처리합니다.
- `POST /api/v1/batch/scripts/from-notebook` `{artifact_id, name?}`: 세션 노트북을 배치 스크립트로 등록합니다.
- pr-batch가 호출하는 `/internal/v1/execution-reports`는 서비스 간 API라 프론트에서 쓰지 않습니다.

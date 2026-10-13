# 프론트엔드 연동 가이드 (API v1)

기준 경로는 `/api/v1`입니다. 전체 스키마는 서비스의 `/docs`(Swagger)와 `/openapi.json`에서 확인할 수 있습니다. 동작하는 참고 구현은 `web/dev/index.html`(로컬·dev 환경의 `/dev/`)입니다.

## 1. 인증 (사내 SSO)

| 순서 | 호출 | 설명 |
| --- | --- | --- |
| 1 | 브라우저 이동 `GET /api/v1/auth/login/sso?return_to=/` | XHR이 아니라 페이지 이동으로 호출합니다. 사내 SSO를 거쳐 `FRONTEND_ORIGIN + return_to`로 돌아옵니다. 최초 로그인이면 User와 기본 Project가 생성됩니다. |
| 2 | `GET /api/v1/auth/session` | `{user_id, csrf_token, expires_at}`. 401이면 1번으로 이동합니다. |
| 3 | 이후 모든 호출 | `credentials: "include"`로 쿠키를 보냅니다. GET 외 요청에는 `X-CSRF-Token: <csrf_token>` 헤더가 필요합니다. |
| - | `POST /api/v1/auth/logout` | 서비스 세션만 종료합니다(사내 SSO 전체 로그아웃 아님). |

`GET /api/v1/users/me` → `{user, default_project_id, models, default_model, default_code_level}`

## 2. 프로젝트·세션·메시지

| Method | Path | 설명 |
| --- | --- | --- |
| GET/POST | `/projects` | 목록 / 생성 `{name, description?, system_prompt?, code_level?}` |
| GET/PATCH/DELETE | `/projects/{id}` | `system_prompt`는 모든 Agent에 주입되는 프로젝트 지침입니다. 기본 프로젝트는 삭제할 수 없습니다. |
| POST | `/projects/{id}/sessions` | `{message?, title?, code_level?, model_alias?}`. `message`가 있으면 세션을 만들고 바로 첫 턴을 시작합니다(응답 `{session, run}`). |
| GET | `/projects/{id}/sessions` | 세션 목록. `active_run_id`가 있으면 작업 중입니다. |
| GET/PATCH/DELETE | `/sessions/{id}` | `title`, `code_level`(1~4, null이면 프로젝트 기본값) 변경. `title_source`: `initial`(첫 메시지 앞부분) → `auto`(첫 답변 후 LLM 요약) / `user`(직접 변경, 이후 자동 변경 없음) |
| GET | `/sessions/{id}/messages` | 화면용 대화 기록. assistant 메시지의 `attachments`에 리포트·노트북이 들어 있습니다. |
| POST | `/sessions/{id}/messages` | `{content, model_alias?}` → 202 Run. **세션이 작업 중이면 409**입니다(세션당 동시 작업 1개). |
| GET | `/runs/{id}` | `status`: `queued`, `running`, `waiting_input`, `waiting_executor`, `succeeded`, `failed`, `cancelled` |
| POST | `/runs/{id}/resume` | HITL 응답 `{interrupt_id, value}` (4장) |
| POST | `/runs/{id}/cancel` | 취소. 실행 중인 executor 작업도 취소됩니다. |

## 3. 실시간 이벤트 (SSE)

`GET /api/v1/sessions/{id}/events` (EventSource, `withCredentials: true`)

- 각 이벤트의 `event:` 이름이 아래 type이고, `data`는 `{id?, type, run_id, data}`입니다.
- `id`가 있는 이벤트는 저장되어 재연결 시 `Last-Event-ID`로 이어 받습니다. 커서 없이 연결하면 진행 중인 run의 이벤트를 처음부터 다시 받습니다.
- `token`은 저장하지 않는 실시간 이벤트입니다. 완료되면 `message_final`로 확정 답변이 옵니다.

| type | data | 화면 처리 |
| --- | --- | --- |
| `run_status` | `{status, execution_id?, operation_id?, steps?}` | 상태 표시. `waiting_executor`면 실행 중 단계 표시 |
| `token` | `{text}` | 답변 스트리밍 |
| `message_final` | `{content}` | 확정 답변 (Markdown) |
| `tool_call` | `{name, args}` | 백그라운드 메시지 (Agent가 하는 일) |
| `agent_switched` | `{agent: main\|analyst, task?}` | 담당 전환 표시 |
| `plan_approved`, `plan_auto_approved`, `plan_revised` | 계획 정보 | 백그라운드 메시지 |
| `execution_progress` | `{event_type, status, step, error}` | executor 단계별 진행 |
| `execution_completed` | `{execution_id, results: {"<step>.<tool> <tool>": {status, observations, stdout, images[], error}}, error}` | 단계 결과. 이미지는 5장 참고 |
| `hitl_request` | `{interrupt_id, type, ...}` | 사용자 입력 카드 (4장) |
| `hitl_resolved` | `{interrupt_id}` | 카드 닫기 |
| `artifact` | `{kind: report\|notebook, artifact_id, title}` | 링크 `/view/artifacts/{artifact_id}` |
| `memory_updated` | `{action, item}` | 메모리 변경 알림 |
| `workflow_saved` | `{workflow_id, name}` | 저장 알림 |
| `run_error` | `{message}` | 실패 사유 |
| `session_titled` | `{title}` | 세션 제목 자동 갱신 (목록·헤더 반영) |

## 4. HITL (사용자 확인)

`hitl_request.type`별 화면과 `POST /runs/{run_id}/resume`의 `value`:

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
| GET | `/view/artifacts/{artifact_id}` | 리포트(.md)·노트북(.ipynb) 랜딩 페이지 |
| GET | `/api/v1/artifacts/{artifact_id}` | 메타데이터 |
| GET | `/api/v1/artifacts/{artifact_id}/content` | 원본 다운로드 (executor 프록시) |
| GET | `/api/v1/sessions/{sid}/outputs?execution_id=&path=` | `execution_completed.images[]`의 그림 파일 |

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

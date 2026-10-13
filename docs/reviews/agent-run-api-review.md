# 에이전트 실행 API 리뷰

기준: 2026-10-14 `main` (`459cac7`). 범위는 대화 턴(run)을 시작하고, 진행을 받고, 사용자 확인에 답하고, 취소하고, 결과를 가져오는 API입니다. 코드는 [sessions.py](../../src/api_service/routers/sessions.py), [artifacts.py](../../src/api_service/routers/artifacts.py), [schemas.py](../../src/api_service/schemas.py). 표시한 동작은 로컬 서버에 직접 호출해 확인했습니다.

## 1. 현재 스펙

### 실행 흐름

```
POST /projects/{p}/sessions {message}  또는  POST /sessions/{s}/messages {content}
  → 202 Run {status: queued}
GET  /sessions/{s}/events  (SSE)       → run_status, tool_call, hitl_request, execution_completed, artifact, message_final ...
POST /runs/{r}/resume {interrupt_id, value}   (hitl_request가 왔을 때)
POST /runs/{r}/cancel
GET  /runs/{r}, /runs/{r}/events, /sessions/{s}/messages   (새로고침·지난 턴 다시 그리기)
```

### 엔드포인트

| Method | Path | 요청 | 응답 | 오류 |
| --- | --- | --- | --- | --- |
| POST | `/projects/{p}/sessions` | `{title?, code_level?, message?, model_alias?}` | 201 `{session, run\|null}` | 404 프로젝트, 403 읽기 전용, 422 모델 별칭 |
| POST | `/sessions/{s}/messages` | `{content, model_alias?}` | 202 `Run` | 409 작업 중, 422 모델 별칭, 404 |
| GET | `/sessions/{s}/runs?limit&cursor` | | `{items: Run[], next_cursor}` 최신순 | 422 잘못된 cursor |
| GET | `/runs/{r}` | | `Run` | 404 |
| GET | `/runs/{r}/events?types=` | | `{run_id, status, items: [{id, type, data, created_at}]}` 최대 5000개 | 404 |
| POST | `/runs/{r}/resume` | `{interrupt_id, value}` | 202 `Run` | 409 대기 중이 아니거나 interrupt_id 불일치, 422 객체가 필요한 type에 객체가 아닌 값 |
| POST | `/runs/{r}/cancel` | | 202 `Run` (이미 끝났으면 그 상태 그대로) | 404 |
| GET | `/sessions/{s}/events` | `Last-Event-ID` 또는 `?after=` | SSE (`id`, `event: <type>`, `data: {id?, type, run_id, data}`), 15초마다 keep-alive | 404 |
| GET | `/sessions/{s}/outputs?execution_id&path` | | 단계 출력 파일(이미지 등) | 404 |
| GET | `/sessions/{s}/messages?limit&cursor` | | `{items: Message[], next_cursor}` 페이지 안은 오래된 순 | |
| GET | `/api/v1/artifacts/{id}`, `/content`, `/view/artifacts/{id}` | | 메타데이터(+`view_url`, 노트북은 `lab_url`), 원본, 렌더링 페이지 | 404 |

`Run` = `{id, session_id, status, model_alias, waiting, error, created_at, updated_at, finished_at}`

- `status`: `queued` → `running` → (`waiting_input` | `waiting_executor`) → … → `succeeded` | `failed` | `cancelled`
- `waiting`: `waiting_input`이면 사용자에게 보여 줄 HITL 내용 전체(`interrupt_id`, `type`, 계획 후보 등), `waiting_executor`면 `{kind: executor, execution_id, operation_id, steps}`

### 보장되는 것

- 세션당 동시에 한 턴만 돌아갑니다. 세션 행 잠금으로 동시 전송을 막고, 두 번째 전송은 409입니다.
- run은 사용자 메시지 하나당 하나이고, HITL 응답·executor 대기·Pod 장애 뒤 재개는 같은 run으로 이어집니다.
- SSE는 저장된 이벤트에 id가 있어 재연결 시 `Last-Event-ID`부터 이어 받습니다. cursor 없이 연결하면 진행 중인 run의 이벤트를 처음부터 다시 받습니다. 토큰과 executor 진행 이벤트는 저장하지 않습니다.
- 권한은 모두 세션 → 프로젝트 멤버십으로 확인하고, 쓰기(전송·재개·취소)는 쓰기 역할이 필요합니다.

## 2. 발견한 문제 (심각도 순)

### 높음

**H1. 첫 메시지와 함께 세션을 만들 때 모델 별칭이 틀리면 빈 세션이 남습니다.**
`create_session`이 세션을 먼저 커밋하고 그다음 `start_run`에서 별칭을 검사합니다. 로컬에서 `model_alias: "nope"`로 호출하니 422가 났는데 세션 수가 10 → 11로 늘었습니다(확인 후 지움). 프론트가 재시도하면 "hi" 제목의 빈 세션이 계속 쌓입니다.
→ 별칭 검사를 세션 생성 전으로 옮기거나, 세션 생성과 run 생성을 한 트랜잭션으로 묶습니다.

**H2. 계획 승인 응답의 내용을 API가 검사하지 않습니다.**
`resume`은 "객체인지"만 봅니다. `index`가 후보 범위 밖이면 에이전트 안에서 `IndexError`가 나고, 필수 입력이 비어 있으면 에이전트가 모델에게 "다시 제안하라"고 돌려서 같은 승인 화면이 다시 뜹니다. 둘 다 사용자 입장에서는 "승인했는데 다시 물어본다"로 보입니다.
→ `run.waiting`에 후보와 `input_slots`가 이미 있으므로, API에서 `index` 범위와 필수 입력(`required` 빈칸)을 검사해 422와 빠진 키 목록을 돌려줍니다. `code_approval`, `memory_change`, `workflow_save`도 `approve` 필드 유무를 같은 방식으로 검사합니다.

### 중간

**M1. 실행 중(`running`)에 취소하면 executor 작업이 계속 돌 수 있습니다.**
`waiting_executor`에서 취소하면 API가 executor 실행을 바로 취소합니다. 반면 `running`일 때는 `cancel_requested`만 켜고, worker가 다음 heartbeat에서 작업을 멈춥니다. 그 사이 도구가 executor에 operation을 막 보냈다면 그 operation은 취소되지 않고 끝까지 돕니다. 응답은 202 `running`이라 클라이언트는 SSE의 `run_status: cancelled`를 기다려야 합니다.
→ worker가 취소로 끝낼 때 state의 살아 있는 execution을 확인해 executor 취소를 함께 보냅니다. API 문서에 "취소는 비동기, 완료는 `run_status`로 확인"을 명시합니다.

**M2. 메시지 전송에 멱등성 키가 없습니다.**
네트워크 오류로 프론트가 `POST /messages`를 다시 보내면, 첫 요청이 이미 끝난 짧은 턴이었을 경우 같은 질문으로 턴이 두 번 돕니다(첫 요청이 아직 돌고 있으면 409라 괜찮음).
→ `Idempotency-Key` 헤더를 받아 같은 키면 기존 run을 돌려줍니다(세션 범위, 하루 보관이면 충분).

**M3. `resume`의 409가 두 가지 경우를 구분하지 않습니다.**
"이미 답해서 진행 중"(더블 클릭)과 "다른 질문에 대한 답"(오래된 화면)이 같은 메시지입니다. 앞의 경우는 프론트가 무시하면 되고, 뒤의 경우는 화면을 새로 그려야 합니다.
→ 409 본문에 `{code: "already_answered" | "stale_interrupt", status, waiting}`처럼 현재 상태를 담습니다.

**M4. `/sessions/{s}/outputs`가 이미지 한 장마다 executor API를 부릅니다.**
결과 카드 하나에 그림이 여러 장이면, 그 수만큼 executor `GET /executions/{id}`가 나갑니다(세션 소유 확인용). 지난 대화를 다시 그리면 더 많아집니다.
→ `code_sources`(또는 run 이벤트)에 `execution_id ↔ session_id`가 있으니 우리 DB로 확인하고 executor 호출을 없앱니다.

### 낮음

**L1.** `/runs/{r}/events`가 최대 5000개에서 조용히 자릅니다. 지금 턴당 이벤트는 수십 개라 문제는 없지만, 잘렸는지 알 수 있게 `truncated` 플래그나 `after` 커서를 두는 게 안전합니다.

**L2.** `Run`에 실행 연결 정보가 없습니다. `waiting_executor` 동안에만 `waiting.execution_id`가 보이고 끝나면 사라집니다. run → execution 관계는 `code_sources`에 있지만 API로 노출되지 않습니다(필요 없다고 정리됨, 기록만 남김).

**L3.** 오류 응답 형식이 FastAPI 기본 `{"detail": "..."}` 문자열 하나입니다. 프론트가 분기하려면 메시지 문자열을 비교해야 합니다. `{detail, code}`처럼 기계가 읽을 코드를 함께 주는 편이 낫습니다(H2, M3과 같이 하면 좋음).

**L4.** 세션을 지워도 열려 있는 SSE 연결은 끊기지 않습니다. 다른 탭에서 지운 경우에만 해당하고 데이터가 새지는 않습니다.

## 3. 문제없음으로 확인한 것

- 끝난 run에 `resume` → 409, `cancel` → 202와 현재 상태(변경 없음). 없는 run → 404. 잘못된 cursor → 422.
- 취소와 worker의 run 가져가기가 겹쳐도, API가 행을 잠그고 worker는 `SKIP LOCKED` + `status=queued` 조건으로 가져가서 취소된 run이 실행되지 않습니다.
- SSE는 구독을 먼저 걸고 저장된 이벤트를 읽은 뒤 id로 중복을 걸러서, 재연결 순간의 이벤트를 잃지 않습니다.
- `outputs`는 경로가 `executions/{execution_id}/`로 시작하는지와 결과 루트 밖으로 나가지 않는지를 모두 확인합니다.

## 4. 권장 순서

1. H1 (작음, 바로 고칠 수 있음)
2. H2 + M3 + L3 (resume 검증과 오류 코드를 한 번에)
3. M1 (취소 시 executor 정리)
4. M4, M2

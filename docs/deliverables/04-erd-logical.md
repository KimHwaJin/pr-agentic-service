# 논리 ERD

| 항목 | 내용 |
| --- | --- |
| 시스템 | gaia-api-service (사내 데이터 분석 Agent 서비스) |
| 스키마 버전 | 마이그레이션 0008 |
| 그림 원본 | `diagrams/04-erd-logical.drawio` (페이지 4장) |
| 모델 정의 | `src/dtest/core/models.py`, `src/dtest/gaia_bridge/models.py` |

엔티티마다 모든 속성은 9절에 있습니다. 데이터 타입과 기본값은 `06-table-definition.md`, `06-table-definition.xlsx`(Table 정의서)에 있습니다.

## 1. 개요

이 서비스의 데이터는 세 곳에 나뉘어 있습니다.

| 저장소 | 담는 것 | 사라지면 |
| --- | --- | --- |
| PostgreSQL 앱 테이블 19개 | 사용자, 프로젝트, 대화, 실행(run), 이벤트, 워크플로우, 배치 리포트, API 키 | 서비스 데이터 손실. 백업 대상 |
| PostgreSQL LangGraph 테이블 | Agent의 대화 상태(체크포인트)와 프로젝트 메모리 본문(store) | 진행 중이던 대화를 이어 갈 수 없고 프로젝트 메모리가 사라짐. 백업 대상 |
| Redis | 로그인 세션, 실시간 이벤트 전달, executor 이벤트 스트림, run 깨우기 신호 | 사용자가 다시 로그인해야 함. 놓친 executor 이벤트는 복구 절차가 채움. 영구 데이터 없음 |

분석 코드의 실행 기록, 노트북, 리포트 파일은 이 서비스가 아니라 executor가 가지고 있습니다. 우리 DB에는 그 식별자(`execution_id`, `artifact_id`)만 남습니다.

공통 규칙은 다음과 같습니다.

- 기본키는 UUID 문자열(36자)입니다. 이벤트와 이력처럼 순서가 필요한 테이블만 자동 증가 정수입니다.
- 시각은 모두 시간대가 있는 UTC입니다.
- 사용자에게 보이는 데이터(프로젝트, 세션, 워크플로우)는 지우지 않고 `deleted_at`에 시각을 적습니다(논리 삭제).
- 외래키 제약은 핵심 계층(사용자, 프로젝트, 세션, 메시지, run, 워크플로우)에만 걸려 있습니다. 이벤트, 이력, 코드 파일 같은 부속 테이블은 값으로만 참조하고 제약은 없습니다. 대량 삭제와 보존 정리를 빠르게 하기 위해서입니다.

## 2. 데이터 영역

| 영역 | 엔티티 | 설명 |
| --- | --- | --- |
| 사용자와 프로젝트 | users, projects, project_members | SSO 사용자, 프로젝트, 프로젝트 소유 관계 |
| 대화 | sessions, messages, images | 채팅 세션, 화면에 보이는 메시지, 첨부 이미지 |
| 실행 | runs, run_requests, run_events | Agent 실행 한 턴, 중복 요청 방지 키, 화면에 흘리는 이벤트 |
| executor 연동 | executor_inbox, code_sources | executor가 보낸 이벤트 보관함, executor로 보낸 코드 파일 기록 |
| 프로젝트 메모리 | memory_history, memory_extraction_state | 메모리 변경 이력, 백그라운드 정리 작업의 진행 위치 |
| 워크플로우 | workflows, workflow_query_vectors | 저장한 분석 절차, 검색용 임베딩 |
| 배치 리포트 | batch_report_jobs, batch_report_events | 배치 실행 결과 리포트 작업, 그 진행 이벤트 |
| 서비스 간 인증 | api_clients | 다른 서비스에 발급한 API 키 |
| gaia 연동 | gaia_sessions | gaia 채팅 세션과 우리 세션의 대응 |

## 3. ERD

### 3.1 전체

실선은 외래키 제약이 있는 관계, 점선은 값으로만 참조하는 관계입니다. 두 줄 표시 쪽이 부모(1), 까치발 쪽이 자식(0..N)입니다.

![논리 ERD 전체](diagrams/export/04-erd-logical-1.png)

### 3.2 사용자, 프로젝트, 대화, 실행

![논리 ERD 사용자, 대화, 실행](diagrams/export/04-erd-logical-2.png)

### 3.3 워크플로우, 배치 리포트, 메모리, 인증

![논리 ERD 워크플로우, 배치, 메모리, 인증](diagrams/export/04-erd-logical-3.png)

### 3.4 LangGraph 체크포인트와 store, 마이그레이션 버전

Agent의 대화 상태와 store, 스키마 버전 기록입니다. 앱 테이블과 외래키 제약은 없고 값으로만 이어집니다.

![논리 ERD LangGraph, Alembic](diagrams/export/04-erd-logical-4.png)

## 4. 엔티티 정의

### 4.1 사용자와 프로젝트

**users (사용자)**
SSO로 처음 로그인할 때 만들어집니다. `employee_id`(사번)가 사람을 구분하는 값이고 중복될 수 없습니다. `role`은 `user` 또는 `admin`입니다. `is_active`가 거짓이면 로그인과 API 호출이 모두 막히고, 진행 중이던 run과 executor 커널이 취소됩니다. `batches_disable_pending`은 비활성화된 사용자의 배치를 batch에서 아직 끄지 못했다는 표시이고, worker가 성공할 때까지 다시 시도합니다.

**projects (프로젝트)**
대화를 묶는 단위입니다. `system_prompt`는 그 프로젝트의 모든 대화에 들어가는 지시문, `code_level`은 코드 생성 수준의 기본값입니다. 사용자마다 첫 로그인 때 기본 프로젝트(`is_default`)가 하나 만들어집니다.

**project_members (프로젝트 구성원)**
프로젝트와 사용자의 다대다 관계입니다. 현재는 만든 사람이 `owner`로 한 줄 들어가는 것이 전부이고, 프로젝트 공유 기능을 나중에 붙일 수 있게 테이블만 준비되어 있습니다. 프로젝트 접근 권한은 이 테이블로 판단합니다.

### 4.2 대화

**sessions (채팅 세션)**
프로젝트 안의 대화 하나입니다. `active_run_id`는 지금 진행 중인 run이고, 값이 있는 동안에는 새 턴을 시작할 수 없습니다(세션당 한 턴 규칙). `title_source`는 제목이 어떻게 정해졌는지입니다. 첫 메시지에서 딴 것은 `initial`, 첫 답변 뒤 LLM이 요약한 것은 `auto`, 사용자가 바꾼 것은 `user`입니다. 세션 id는 LangGraph 체크포인트의 thread id로도 쓰입니다.

**messages (메시지)**
화면에 보이는 대화 내용입니다. Agent가 실제로 참고하는 대화 이력은 체크포인트에 따로 있으므로, 이 테이블을 고쳐도 Agent의 기억은 바뀌지 않습니다. `attachments`에는 이미지 참조와 결과물 링크가 들어갑니다.

**images (이미지)**
사용자가 메시지에 붙인 이미지의 메타 정보입니다. 파일 자체는 공유 저장소(`STORAGE_ROOT`) 아래 `path`에 있습니다.

### 4.3 실행

**runs (실행)**
사용자 메시지 한 건에 대한 Agent 실행 한 턴입니다. 작업 큐 역할도 합니다. worker는 `status`와 `lease_expires_at`을 보고 가져갈 run을 고릅니다.

- `input`: 사용자 메시지와 선택한 옵션.
- `waiting`: 멈춰 있는 이유. 사용자 확인을 기다리면 그 질문, executor를 기다리면 `execution_id`.
- `resume`: 멈춘 run을 이어 갈 때 넘겨줄 값(사용자의 답, executor 결과).
- `lease_owner`, `lease_expires_at`: 어느 인스턴스가 언제까지 실행 권한을 가졌는지. 만료되면 다른 인스턴스가 가져갑니다.
- `cancel_requested`: 사용자가 취소를 눌렀다는 표시.
- `recovery_checked_at`: 놓친 executor 이벤트를 마지막으로 확인한 시각.

**run_requests (실행 요청 키)**
`POST /sessions/{id}/runs`의 `Idempotency-Key`를 하루 동안 기억합니다. 같은 키로 같은 요청이 다시 오면 새 run을 만들지 않고 처음 만든 run을 돌려줍니다.

**run_events (실행 이벤트)**
화면에 실시간으로 보내는 이벤트 중 저장하는 것들입니다(상태 변경, 도구 호출, 계획 카드, 최종 답변 등). 브라우저가 끊겼다 다시 붙으면 마지막으로 받은 id 다음부터 이 테이블에서 다시 읽어 줍니다. 토큰 단위 스트리밍과 executor 진행 이벤트는 저장하지 않습니다.

### 4.4 executor 연동

**executor_inbox (executor 이벤트 보관함)**
executor가 Redis 스트림으로 보낸 이벤트를 중복 없이 보관합니다. `event_id`가 기본키라 같은 이벤트가 두 번 와도 한 줄만 남습니다. executor를 기다리던 run은 이 테이블의 이벤트를 근거로 다시 시작됩니다.

**code_sources (코드 파일 기록)**
Agent가 executor로 보낸 코드 파일 하나하나의 기록입니다. 어떤 run의 어떤 도구 호출에서 만들어졌는지, 어떤 skill과 tool인지, 사용자가 승인하거나 고쳤는지, executor의 어느 실행 단계가 되었는지를 잇습니다. 파일은 전달 수단일 뿐이고, 실제 실행 기록은 executor가 제출 시점에 뜬 사본과 노트북입니다. 그래서 파일은 7일 뒤 지우고(`file_deleted_at`) 이 행만 남깁니다.

### 4.5 프로젝트 메모리

프로젝트 메모리의 본문(주제 목록과 주제별 내용)은 앱 테이블이 아니라 LangGraph store에 있습니다. 앱 테이블에는 이력과 작업 상태만 있습니다.

**memory_history (메모리 변경 이력)**
메모리가 바뀔 때마다 바뀌기 전과 후를 남깁니다. `actor_type`으로 사용자가 고쳤는지 Agent가 고쳤는지 구분합니다. 화면에서 이전 상태로 되돌릴 때 씁니다.

**memory_extraction_state (메모리 정리 상태)**
프로젝트마다 한 줄입니다. 대화가 끝나면 `dirty`가 켜지고 `pending_turns`가 올라갑니다. 대화가 잠잠해지면 worker가 lease를 잡고, `processed_until_*` 위치 다음의 메시지를 읽어 기억할 내용을 정리합니다.

### 4.6 워크플로우

**workflows (워크플로우)**
저장된 분석 절차입니다. `document`가 Workflow 1.0 형식의 본문이고, `user_queries`는 이 워크플로우를 찾을 때 쓸 질문 예시입니다. `lifecycle`은 개인이 저장한 `candidate`와 관리자가 승격한 `template` 두 가지입니다. 내용을 고치면 `revision`이 올라갑니다. `index_state`는 검색 색인 상태(`not_indexed`, `ready`, `failed`)입니다.

**workflow_query_vectors (워크플로우 검색 벡터)**
`user_queries`의 질문마다 임베딩 한 줄입니다. 워크플로우를 고치면 이전 벡터의 `active`를 끄고 새 revision의 벡터를 만듭니다. 삭제되지 않은 `template`의 벡터만 `active`이고, 검색은 `active`인 행만 봅니다. `model`에는 `모델이름:차원` 형태의 값이 들어가 임베딩 모델이 바뀐 것을 구분합니다.

### 4.7 배치 리포트

**batch_report_jobs (배치 리포트 작업)**
batch의 배치 실행이 성공하면 그 결과를 분석해 리포트를 쓰는 작업입니다. 실행 한 건에 작업 하나이고 `idempotency_key`(`batch-report:{execution_id}`)로 중복을 막습니다. `owner_id`는 배치를 만든 사용자이고 그 사용자만 리포트를 봅니다. `markdown`은 리포트 본문, `summary`는 같은 배치의 다음 실행이 비교용으로 읽는 요약입니다.

**batch_report_events (배치 리포트 이벤트)**
리포트 작업의 진행 이벤트입니다. 채팅 이벤트와 같은 형식이라 화면이 같은 컴포넌트로 그립니다.

### 4.8 서비스 간 인증

**api_clients (API 클라이언트)**
다른 서비스와 에이전트에 발급한 API 키입니다. 키 원문은 저장하지 않고 SHA-256(`key_sha256`)과 앞부분(`key_prefix`)만 남깁니다. `tenant`는 이 키로 만든 실행과 배치가 속할 executor tenant입니다. `kind`가 `standard`이면 `X-User-Id` 사용자의 것만 조회하고, `master`이면 tenant 전체를 조회합니다. `batches_disable_pending`은 tenant의 키가 모두 폐기된 뒤 batch에서 그 tenant의 배치를 아직 끄지 못했다는 표시입니다.

### 4.9 gaia 연동

**gaia_sessions (gaia 세션 대응)**
gaia 채팅 화면의 세션 하나가 우리 세션 하나에 대응합니다. 기본키가 (사용자, gaia 세션 id)라서 다른 사용자가 같은 gaia 세션 id를 보내도 남의 세션에 닿지 않습니다.

## 5. 관계와 카디널리티

| 부모 | 자식 | 관계 | 제약 | 비고 |
| --- | --- | --- | --- | --- |
| users | projects | 1:N | FK `created_by` | |
| users, projects | project_members | N:M | FK 2개 | 현재는 프로젝트당 owner 1명 |
| projects | sessions | 1:N | FK | |
| users | sessions | 1:N | FK | |
| sessions | messages | 1:N | FK | |
| sessions | runs | 1:N | FK | 동시에 진행 중인 run은 세션당 1개 |
| runs | messages | 1:N | 없음 | 한 턴의 사용자 메시지와 답변 |
| runs | run_events | 1:N | 없음 | |
| sessions | run_requests | 1:N | 없음 | |
| sessions | images | 1:N | 없음 | |
| runs | code_sources | 1:N | 없음 | |
| runs | executor_inbox | 1:N | 없음 | `runs.waiting.execution_id` = `executor_inbox.execution_id` |
| projects | memory_history | 1:N | 없음 | |
| projects | memory_extraction_state | 1:1 | 없음 | |
| users | workflows | 1:N | FK `author_id` | |
| workflows | workflow_query_vectors | 1:N | FK | |
| users | batch_report_jobs | 1:N | 없음 | `owner_id` = `users.id` |
| batch_report_jobs | batch_report_events | 1:N | 없음 | |
| users, sessions | gaia_sessions | 1:N | FK 2개 | |
| users | api_clients | 1:N | 없음 | `created_by` = 발급한 관리자의 `users.id` |
| sessions | checkpoints | 1:N | 없음 | `checkpoints.thread_id` = `sessions.id` |
| checkpoints | checkpoint_blobs | 1:N | 없음 | 같은 `thread_id`, `checkpoint_ns`와 체크포인트의 채널 버전 |
| checkpoints | checkpoint_writes | 1:N | 없음 | 같은 `thread_id`, `checkpoint_ns`, `checkpoint_id` |
| projects, runs, 배치 | store | 1:N | 없음 | `prefix`가 `project_memory.{project_id}`, `tool_effects.{run_id}`, `batch_memory.{batch_id}` |

## 6. 상태 전이

### 6.1 run

| 이전 상태 | 다음 상태 | 계기 |
| --- | --- | --- |
| (시작) | `queued:` |  |
| `queued` | `running:` |  |
| `running` | `waiting_input:` |  |
| `running` | `waiting_executor:` |  |
| `waiting_input` | `queued:` |  |
| `waiting_executor` | `queued:` |  |
| `running` | `queued:` |  |
| `running` | `succeeded` |  |
| `running` | `failed` |  |
| `running` | `cancelled` |  |
| `waiting_input` | `cancelled` |  |
| `waiting_executor` | `cancelled` |  |
| `queued` | `cancelled` |  |

상태 전이 그림은 프로그램 명세서(Agent Graph)에 있습니다.

| 상태 | 뜻 | 인스턴스 자원 |
| --- | --- | --- |
| `queued` | worker를 기다림 | 쓰지 않음 |
| `running` | 어느 인스턴스가 실행 중. `lease_owner`가 그 인스턴스 | 실행 슬롯 1개 |
| `waiting_input` | 사용자 확인(계획 승인 등)을 기다림 | 쓰지 않음 |
| `waiting_executor` | executor가 코드를 실행 중 | 쓰지 않음 |
| `succeeded`, `failed`, `cancelled` | 끝남. `finished_at`이 채워짐 | 쓰지 않음 |

기다리는 상태에서는 며칠이 지나도 인스턴스 자원을 잡지 않습니다. 실행 중인 인스턴스가 죽으면 lease가 만료되어(기본 60초) 다른 인스턴스가 체크포인트에서 이어 갑니다.

### 6.2 배치 리포트 작업

`QUEUED → COLLECTING → GENERATING → MATERIALIZING → SUCCEEDED` 순서로 진행합니다. 어느 단계에서든 실패하면 `FAILED`가 되고 `failed_stage`에 그 단계가 남습니다.

| 상태 | 하는 일 |
| --- | --- |
| `QUEUED` | 대기 |
| `COLLECTING` | executor에서 실행 결과와 노트북을 모음. 노트북이 준비될 때까지 기다림 |
| `GENERATING` | LLM으로 리포트 작성 |
| `MATERIALIZING` | 리포트를 executor Artifact로 저장 |
| `SUCCEEDED`, `FAILED` | 끝남 |

### 6.3 API 키

발급하면 바로 `active`이고, 폐기하면 `revoked`입니다. 되돌리는 전이는 없습니다. 재발급은 같은 행의 키 해시를 새 값으로 바꾸는 것입니다. 2026-11-01 전에 있던 `pending` 상태는 없어졌고, 남아 있던 행은 마이그레이션 0006이 `active`로 바꿨습니다.

### 6.4 워크플로우

`lifecycle`은 `candidate`에서 `template`으로 관리자가 승격합니다. `index_state`는 저장 직후 `not_indexed`, 임베딩이 끝나면 `ready`, 임베딩 호출이 실패하면 `failed`입니다. 임베딩 설정이 없는 환경에서는 계속 `not_indexed`이고 검색 추천만 동작하지 않습니다.

## 7. 앱 테이블 밖의 데이터

### 7.1 LangGraph 체크포인트와 store (같은 PostgreSQL)

| 데이터 | 테이블 | 키 | 내용 |
| --- | --- | --- | --- |
| 대화 상태 | checkpoints, checkpoint_writes, checkpoint_blobs | thread_id = 세션 id | Agent가 보는 메시지 이력, 분석 계획, 진행 위치. run이 멈췄다 이어 갈 때 읽음 |
| store | store | prefix = 이름공간 | `project_memory.{project_id}` 프로젝트 메모리 본문, `tool_effects.{run_id}` 도구의 executor 요청 결과, `batch_memory.{batch_id}` 배치 리포트 요약 |

이 테이블들은 LangGraph 라이브러리가 만들고 관리합니다. 구조를 직접 바꾸지 않습니다. 모든 속성은 9.20~9.26절에 있습니다.

### 7.2 Redis

| 용도 | 키 또는 채널 | 방식 | 비고 |
| --- | --- | --- | --- |
| 로그인 세션, 로그인 진행 상태 | `{REDIS_NAMESPACE}:{종류}:{해시}` | 문자열 키, 만료 시간 있음 | 지워지면 다시 로그인 |
| 세션 이벤트 전달 | `{REDIS_NAMESPACE}:session:{세션 id}` | 발행/구독 | 저장되지 않음. 저장분은 run_events |
| 배치 리포트 이벤트 전달 | `{REDIS_NAMESPACE}:batch-report:{작업 id}` | 발행/구독 | |
| run 깨우기 | `{REDIS_NAMESPACE}:runs:wake` | 발행/구독 | 놓쳐도 5초 폴링이 처리 |
| executor 이벤트 | `{EXECUTOR_EVENT_STREAM}.{tenant}` | 스트림, 소비자 그룹 | executor가 쓰고 우리가 읽음. 같은 Redis, 같은 DB 번호여야 함 |

`REDIS_NAMESPACE`의 기본값은 `agentic`입니다. 두 환경이 같은 Redis를 쓰면 이 값이 달라야 로그인 세션과 이벤트가 섞이지 않습니다.

### 7.3 executor와 공유 저장소

| 데이터 | 위치 | 우리 DB의 참조 |
| --- | --- | --- |
| 실행, 단계, 결과, 노트북, 리포트 Artifact | executor의 DB와 저장소 | `runs.waiting.execution_id`, `code_sources.execution_id`, `batch_report_jobs.execution_id`, `batch_report_jobs.artifact_id` |
| 코드 파일, 첨부 이미지 | 공유 저장소(`STORAGE_ROOT`) | `code_sources.path`, `images.path` |
| 배치 정의와 배치 실행 | batch의 DB | `batch_report_jobs.batch_id`, `batch_run_id` |

## 8. 삭제와 보존 규칙

| 대상 | 규칙 | 설정(기본값) |
| --- | --- | --- |
| 프로젝트, 세션, 워크플로우 | 논리 삭제. 행은 남고 `deleted_at`만 채움 | |
| run_events, batch_report_events | 만든 지 30일 지나면 삭제 | `RUN_EVENT_RETENTION_DAYS` (30) |
| executor_inbox | 받은 지 7일 지나면 삭제 | `EXECUTOR_INBOX_RETENTION_DAYS` (7) |
| run_requests | 1일 지나면 삭제 | `RUN_REQUEST_RETENTION_DAYS` (1) |
| images | 세션을 삭제하고 7일 지나면 파일과 행 삭제 | `IMAGE_RETENTION_DAYS` (7) |
| code_sources의 파일 | 7일 지나면 파일만 삭제, 행은 유지 | `CODE_SOURCE_RETENTION_DAYS` (7) |
| 체크포인트 | 진행 중인 run이 없는 세션은 최신 1개만 남김 | |
| messages, runs, memory_history, batch_report_jobs | 자동 삭제 없음 | |

정리는 worker의 보존 작업(`src/dtest/worker/maintenance.py`)이 1시간마다 5,000행씩 나눠 지웁니다. 배치 리포트 작업에 보존 기간을 새로 두려면 복구 조회 기간(`BATCH_REPORT_RECOVERY_LOOKBACK_DAYS`, 14일)보다 길어야 합니다. 짧으면 지운 리포트를 복구 작업이 다시 씁니다.

## 9. 엔티티별 속성

모든 엔티티의 모든 속성입니다. 앱 테이블 19개와 같은 데이터베이스에 있는 LangGraph, Alembic 테이블 7개를 함께 적었습니다. 키는 PK 기본키, FK 외래키 제약, UK 유일 제약입니다. 필수는 값이 반드시 있어야 하는 속성입니다.

### 9.1 users (사용자)

SSO로 처음 로그인할 때 만들어집니다. employee_id(사번)가 사람을 구분하는 값이고 중복될 수 없습니다. role은 user 또는 admin입니다. is_active가 거짓이면 로그인과 API 호출이 모두 막히고, 진행 중이던 run과 executor 커널이 취소됩니다. batches_disable_pending은 비활성화된 사용자의 배치를 batch에서 아직 끄지 못했다는 표시이고, worker가 성공할 때까지 다시 시도합니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 사용자 ID | `id` | PK | 필수 | 기본키 |
| 2 | 사번 | `employee_id` | UK | 필수 | SSO 사번. UNIQUE |
| 3 | 이름 | `name` |  | 필수 | SSO에서 받은 이름 |
| 4 | 영문 이름 | `english_name` |  | 선택 | 영문 이름 |
| 5 | 부서 | `department` |  | 선택 | 부서 |
| 6 | 메일 | `email` |  | 선택 | 메일 |
| 7 | 권한 | `role` |  | 필수 | user, admin. DB 제약 없음 |
| 8 | 활성 여부 | `is_active` |  | 필수 | 거짓이면 로그인과 호출 차단 |
| 9 | 배치 끄기 대기 | `batches_disable_pending` |  | 필수 | 비활성화 뒤 batch 배치 끄기 대기 |
| 10 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 11 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.2 projects (프로젝트)

대화를 묶는 단위입니다. system_prompt는 그 프로젝트의 모든 대화에 들어가는 지시문, code_level은 코드 생성 수준의 기본값입니다. 사용자마다 첫 로그인 때 기본 프로젝트(is_default)가 하나 만들어집니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 프로젝트 ID | `id` | PK | 필수 | 기본키 |
| 2 | 프로젝트 이름 | `name` |  | 필수 | 프로젝트 이름 |
| 3 | 설명 | `description` |  | 필수 | 설명 |
| 4 | 프로젝트 지시문 | `system_prompt` |  | 필수 | 프로젝트 지시문 |
| 5 | 기본 코드 생성 수준 | `code_level` |  | 선택 | 코드 생성 수준 기본값 |
| 6 | 기본 프로젝트 여부 | `is_default` |  | 필수 | 첫 로그인 때 만든 기본 프로젝트 |
| 7 | 생성자 ID | `created_by` | FK | 필수 | 프로젝트를 만든 사용자. FK → users.id |
| 8 | 삭제 시각 | `deleted_at` |  | 선택 | 논리 삭제 시각 |
| 9 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 10 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.3 project_members (프로젝트 구성원)

프로젝트와 사용자의 다대다 관계입니다. 현재는 만든 사람이 owner로 한 줄 들어가는 것이 전부이고, 프로젝트 공유 기능을 나중에 붙일 수 있게 테이블만 준비되어 있습니다. 프로젝트 접근 권한은 이 테이블로 판단합니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 프로젝트 ID | `project_id` | PK,FK | 필수 | PK, FK → projects.id |
| 2 | 사용자 ID | `user_id` | PK,FK | 필수 | PK, FK → users.id |
| 3 | 구성원 역할 | `role` |  | 필수 | owner, editor, viewer |
| 4 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |

### 9.4 sessions (채팅 세션)

프로젝트 안의 대화 하나입니다. active_run_id는 지금 진행 중인 run이고, 값이 있는 동안에는 새 턴을 시작할 수 없습니다(세션당 한 턴 규칙). title_source는 제목이 어떻게 정해졌는지입니다. 첫 메시지에서 딴 것은 initial, 첫 답변 뒤 LLM이 요약한 것은 auto, 사용자가 바꾼 것은 user입니다. 세션 id는 LangGraph 체크포인트의 thread id로도 쓰입니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 세션 ID | `id` | PK | 필수 | PK. LangGraph thread id로도 사용 |
| 2 | 프로젝트 ID | `project_id` | FK | 필수 | FK → projects.id |
| 3 | 사용자 ID | `user_id` | FK | 필수 | FK → users.id |
| 4 | 제목 | `title` |  | 필수 | 제목 |
| 5 | 제목 출처 | `title_source` |  | 필수 | initial, auto, user |
| 6 | 코드 생성 수준 | `code_level` |  | 선택 | 세션의 코드 생성 수준. 비면 프로젝트 값 |
| 7 | 진행 중 실행 ID | `active_run_id` |  | 선택 | 진행 중인 run. FK 제약 없음 |
| 8 | 삭제 시각 | `deleted_at` |  | 선택 | 논리 삭제 시각 |
| 9 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 10 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.5 messages (메시지)

화면에 보이는 대화 내용입니다. Agent가 실제로 참고하는 대화 이력은 체크포인트에 따로 있으므로, 이 테이블을 고쳐도 Agent의 기억은 바뀌지 않습니다. attachments에는 이미지 참조와 결과물 링크가 들어갑니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 메시지 ID | `id` | PK | 필수 | 기본키 |
| 2 | 세션 ID | `session_id` | FK | 필수 | FK → sessions.id |
| 3 | 실행 ID | `run_id` |  | 선택 | 이 메시지를 만든 run |
| 4 | 작성 주체 | `role` |  | 필수 | user, assistant |
| 5 | 본문 | `content` |  | 필수 | 본문 |
| 6 | 첨부 | `attachments` |  | 필수 | 이미지 참조, 결과물 링크 |
| 7 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |

### 9.6 runs (실행)

사용자 메시지 한 건에 대한 Agent 실행 한 턴입니다. 작업 큐 역할도 합니다. worker는 status와 lease_expires_at을 보고 가져갈 run을 고릅니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 실행 ID | `id` | PK | 필수 | 기본키 |
| 2 | 세션 ID | `session_id` | FK | 필수 | FK → sessions.id |
| 3 | 프로젝트 ID | `project_id` |  | 필수 | 대화의 프로젝트. 조회용 사본 (projects.id 값, FK 제약 없음) |
| 4 | 사용자 ID | `user_id` |  | 필수 | 요청한 사용자. 조회용 사본 (users.id 값, FK 제약 없음) |
| 5 | 실행 상태 | `status` |  | 필수 | queued, running, waiting_input, waiting_executor, succeeded, failed, cancelled |
| 6 | 모델 별칭 | `model` |  | 필수 | 사용한 모델 별칭 |
| 7 | 입력 | `input` |  | 필수 | 사용자 입력 |
| 8 | 재개 값 | `resume` |  | 선택 | 이어 갈 때 넘길 값 |
| 9 | 대기 대상 | `waiting` |  | 선택 | 기다리는 대상. executor 대기면 execution_id 포함 |
| 10 | 실패 사유 | `error` |  | 선택 | 실패 사유 |
| 11 | 취소 요청 여부 | `cancel_requested` |  | 필수 | 취소 요청 여부 |
| 12 | 처리 인스턴스 | `lease_owner` |  | 선택 | 실행 중인 인스턴스 식별자 |
| 13 | 처리 권한 만료 시각 | `lease_expires_at` |  | 선택 | 실행 권한 만료 시각 |
| 14 | 가져간 횟수 | `attempts` |  | 필수 | 실행을 가져간 횟수 |
| 15 | 종료 시각 | `finished_at` |  | 선택 | 끝난 시각 |
| 16 | 이벤트 복구 확인 시각 | `recovery_checked_at` |  | 선택 | 놓친 executor 이벤트를 마지막으로 확인한 시각 |
| 17 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 18 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.7 run_events (실행 이벤트)

화면에 실시간으로 보내는 이벤트 중 저장하는 것들입니다(상태 변경, 도구 호출, 계획 카드, 최종 답변 등). 브라우저가 끊겼다 다시 붙으면 마지막으로 받은 id 다음부터 이 테이블에서 다시 읽어 줍니다. 토큰 단위 스트리밍과 executor 진행 이벤트는 저장하지 않습니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 이벤트 번호 | `id` | PK | 필수 | PK. SSE 이벤트 id로 사용 |
| 2 | 세션 ID | `session_id` |  | 필수 | 이벤트가 속한 대화 (sessions.id 값) |
| 3 | 실행 ID | `run_id` |  | 필수 | 이벤트를 낸 run (runs.id 값) |
| 4 | 이벤트 종류 | `type` |  | 필수 | 이벤트 종류 |
| 5 | 이벤트 내용 | `data` |  | 필수 | 이벤트 내용 |
| 6 | 생성 시각 | `created_at` |  | 필수 | 보존 정리 기준 |

### 9.8 run_requests (실행 요청 키)

POST /sessions/{id}/runs의 Idempotency-Key를 하루 동안 기억합니다. 같은 키로 같은 요청이 다시 오면 새 run을 만들지 않고 처음 만든 run을 돌려줍니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 세션 ID | `session_id` | PK | 필수 | 기본키 |
| 2 | 요청 키 | `key` | PK | 필수 | PK. 요청의 Idempotency-Key |
| 3 | 요청 해시 | `request_hash` |  | 필수 | 요청 본문 해시. 같은 키에 다른 본문이면 거부 |
| 4 | 실행 ID | `run_id` |  | 필수 | 처음 만든 run |
| 5 | 재개 요청 여부 | `resumed` |  | 필수 | 새 run이 아니라 기존 run을 이어 간 요청인지 |
| 6 | 생성 시각 | `created_at` |  | 필수 | 보존 정리 기준 |

### 9.9 executor_inbox (executor 이벤트 보관함)

executor가 Redis 스트림으로 보낸 이벤트를 중복 없이 보관합니다. event_id가 기본키라 같은 이벤트가 두 번 와도 한 줄만 남습니다. executor를 기다리던 run은 이 테이블의 이벤트를 근거로 다시 시작됩니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 이벤트 ID | `event_id` | PK | 필수 | PK. executor가 준 이벤트 id |
| 2 | executor 실행 ID | `execution_id` |  | 필수 | executor 실행 id |
| 3 | 이벤트 종류 | `event_type` |  | 필수 | 이벤트 종류 |
| 4 | 이벤트 순번 | `event_sequence` |  | 필수 | 실행 안에서의 순번 |
| 5 | 이벤트 내용 | `payload` |  | 필수 | executor에 다시 조회해 확인한 이벤트 내용 |
| 6 | 수신 시각 | `received_at` |  | 필수 | 보존 정리 기준 |

### 9.10 code_sources (코드 파일 기록)

Agent가 executor로 보낸 코드 파일 하나하나의 기록입니다. 어떤 run의 어떤 도구 호출에서 만들어졌는지, 어떤 skill과 tool인지, 사용자가 승인하거나 고쳤는지, executor의 어느 실행 단계가 되었는지를 잇습니다. 파일은 전달 수단일 뿐이고, 실제 실행 기록은 executor가 제출 시점에 뜬 사본과 노트북입니다. 그래서 파일은 7일 뒤 지우고(file_deleted_at) 이 행만 남깁니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 코드 파일 ID | `id` | PK | 필수 | 기본키 |
| 2 | 사용자 ID | `user_id` |  | 필수 | 코드를 만든 사용자 (users.id 값, FK 제약 없음) |
| 3 | 프로젝트 ID | `project_id` |  | 필수 | 코드가 속한 프로젝트 (projects.id 값, FK 제약 없음) |
| 4 | 세션 ID | `session_id` |  | 필수 | 이 코드를 만든 대화 (sessions.id 값) |
| 5 | 실행 ID | `run_id` |  | 필수 | 이 코드를 만든 run (runs.id 값) |
| 6 | 도구 호출 ID | `tool_call_id` |  | 필수 | Agent의 도구 호출 id |
| 7 | 파일 경로 | `path` | UK | 필수 | executor 기준 상대 경로. UNIQUE (중복 방지 키) |
| 8 | 파일 해시 | `sha256` |  | 필수 | 파일 해시 |
| 9 | 파일 크기 | `size_bytes` |  | 필수 | 파일 크기(바이트) |
| 10 | 코드 종류 | `kind` |  | 필수 | setup, tool, custom |
| 11 | skill 이름 | `skill` |  | 선택 | 사용한 skill 이름. tool 코드가 아니면 비어 있음 |
| 12 | tool 이름 | `tool` |  | 선택 | 사용한 tool 이름. tool 코드가 아니면 비어 있음 |
| 13 | 호출 키 | `call_key` |  | 선택 | 계획 안의 호출 키 |
| 14 | tool 버전 | `tool_version` |  | 선택 | tool 파일 버전 |
| 15 | 목적 | `purpose` |  | 선택 | 코드의 목적 |
| 16 | 승인자 ID | `approved_by` |  | 선택 | 승인한 사용자 |
| 17 | 사용자 수정 여부 | `edited` |  | 선택 | 사용자가 코드를 고쳤는지 |
| 18 | executor 실행 ID | `execution_id` |  | 선택 | 이 코드를 실행한 executor 실행 id |
| 19 | executor 작업 ID | `operation_id` |  | 선택 | executor 쪽 작업(operation) id |
| 20 | executor 단계 ID | `step_id` |  | 선택 | executor 쪽 단계(step) id |
| 21 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 22 | 파일 삭제 시각 | `file_deleted_at` |  | 선택 | 파일을 지운 시각 |

### 9.11 images (이미지)

사용자가 메시지에 붙인 이미지의 메타 정보입니다. 파일 자체는 공유 저장소(STORAGE_ROOT) 아래 path에 있습니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 이미지 ID | `id` | PK | 필수 | 기본키 |
| 2 | 사용자 ID | `user_id` |  | 필수 | 이미지를 보낸 사용자 (users.id 값, FK 제약 없음) |
| 3 | 프로젝트 ID | `project_id` |  | 필수 | 이미지가 속한 프로젝트 (projects.id 값, FK 제약 없음) |
| 4 | 세션 ID | `session_id` |  | 필수 | 이미지를 보낸 대화 (sessions.id 값, FK 제약 없음) |
| 5 | 실행 ID | `run_id` |  | 선택 | 이미지를 처음 쓴 run |
| 6 | 파일 이름 | `name` |  | 선택 | 파일 이름 |
| 7 | 형식 | `mime_type` |  | 필수 | 형식 |
| 8 | 파일 크기 | `size_bytes` |  | 필수 | 파일 크기(바이트) |
| 9 | 가로 크기 | `width` |  | 필수 | 이미지 가로 크기(픽셀) |
| 10 | 세로 크기 | `height` |  | 필수 | 이미지 세로 크기(픽셀) |
| 11 | 파일 해시 | `sha256` |  | 필수 | 파일 해시 |
| 12 | 저장 경로 | `path` |  | 필수 | STORAGE_ROOT 아래 경로 |
| 13 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |

### 9.12 memory_history (메모리 변경 이력)

메모리가 바뀔 때마다 바뀌기 전과 후를 남깁니다. actor_type으로 사용자가 고쳤는지 Agent가 고쳤는지 구분합니다. 화면에서 이전 상태로 되돌릴 때 씁니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 이력 번호 | `id` | PK | 필수 | 기본키 |
| 2 | 프로젝트 ID | `project_id` |  | 필수 | 메모리가 속한 프로젝트 (projects.id 값, FK 제약 없음) |
| 3 | 메모리 주제 ID | `item_id` |  | 필수 | 메모리 주제 id |
| 4 | 변경 종류 | `action` |  | 필수 | create, update, delete |
| 5 | 변경 전 내용 | `before` |  | 선택 | 변경 전 주제 내용. 새로 만든 경우 비어 있음 |
| 6 | 변경 후 내용 | `after` |  | 선택 | 변경 후 주제 내용. 지운 경우 비어 있음 |
| 7 | 변경 주체 종류 | `actor_type` |  | 필수 | user, agent |
| 8 | 변경 주체 ID | `actor_id` |  | 필수 | 바꾼 주체. 사용자면 users.id, Agent면 run id |
| 9 | 세션 ID | `session_id` |  | 선택 | Agent가 바꾼 경우 그 대화. 사용자가 바꾸면 비어 있음 |
| 10 | 실행 ID | `run_id` |  | 선택 | Agent가 바꾼 경우 그 run. 사용자가 바꾸면 비어 있음 |
| 11 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |

### 9.13 memory_extraction_state (메모리 정리 상태)

프로젝트마다 한 줄입니다. 대화가 끝나면 dirty가 켜지고 pending_turns가 올라갑니다. 대화가 잠잠해지면 worker가 lease를 잡고, processed_until_* 위치 다음의 메시지를 읽어 기억할 내용을 정리합니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 프로젝트 ID | `project_id` | PK | 필수 | 기본키 |
| 2 | 처리 완료 메시지 시각 | `processed_until_at` |  | 선택 | 처리한 마지막 메시지의 시각 |
| 3 | 처리 완료 메시지 ID | `processed_until_id` |  | 필수 | 처리한 마지막 메시지 id |
| 4 | 처리 대기 여부 | `dirty` |  | 필수 | 처리할 대화가 있음 |
| 5 | 마지막 대화 시각 | `last_activity_at` |  | 필수 | 마지막 대화 시각 |
| 6 | 미처리 턴 수 | `pending_turns` |  | 필수 | 아직 처리하지 않은 턴 수 |
| 7 | 처리 인스턴스 | `lease_owner` |  | 선택 | 처리 중인 인스턴스 |
| 8 | 처리 권한 만료 시각 | `lease_expires_at` |  | 선택 | 처리 권한 만료 시각. 재시도 대기 시각으로도 사용 |
| 9 | 시도 횟수 | `attempts` |  | 필수 | 시도 횟수 |
| 10 | 마지막 오류 | `last_error` |  | 선택 | 마지막 오류 |
| 11 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.14 workflows (워크플로우)

저장된 분석 절차입니다. document가 Workflow 1.0 형식의 본문이고, user_queries는 이 워크플로우를 찾을 때 쓸 질문 예시입니다. lifecycle은 개인이 저장한 candidate와 관리자가 승격한 template 두 가지입니다. 내용을 고치면 revision이 올라갑니다. index_state는 검색 색인 상태(not_indexed, ready, failed)입니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 워크플로우 ID | `id` | PK | 필수 | 기본키 |
| 2 | 워크플로우 이름 | `name` |  | 필수 | 이름 |
| 3 | 원래 요청 | `user_request` |  | 필수 | 원래 사용자 요청 |
| 4 | 워크플로우 문서 | `document` |  | 필수 | Workflow 1.0 문서 |
| 5 | 질문 예시 | `user_queries` |  | 필수 | 검색용 질문 예시 |
| 6 | 태그 | `tags` |  | 필수 | 태그 |
| 7 | 단계 | `lifecycle` |  | 필수 | candidate, template |
| 8 | 작성자 ID | `author_id` | FK | 필수 | FK → users.id |
| 9 | 출처 실행 ID | `source_run_id` |  | 선택 | 이 워크플로우가 나온 run |
| 10 | 원본 워크플로우 ID | `source_workflow_id` |  | 선택 | 복사해 온 원본 |
| 11 | 수정 번호 | `revision` |  | 필수 | 수정할 때마다 1씩 늘어나는 번호 |
| 12 | 색인 상태 | `index_state` |  | 필수 | not_indexed, ready, failed |
| 13 | 삭제 시각 | `deleted_at` |  | 선택 | 논리 삭제 시각 |
| 14 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 15 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.15 workflow_query_vectors (워크플로우 검색 벡터)

user_queries의 질문마다 임베딩 한 줄입니다. 워크플로우를 고치면 이전 벡터의 active를 끄고 새 revision의 벡터를 만듭니다. 삭제되지 않은 template의 벡터만 active이고, 검색은 active인 행만 봅니다. model에는 모델이름:차원 형태의 값이 들어가 임베딩 모델이 바뀐 것을 구분합니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 벡터 번호 | `id` | PK | 필수 | 기본키 |
| 2 | 워크플로우 ID | `workflow_id` | FK | 필수 | FK → workflows.id |
| 3 | 수정 번호 | `revision` |  | 필수 | 어느 수정 번호의 워크플로우에서 만든 벡터인지 |
| 4 | 질문 문장 | `query` |  | 필수 | 질문 문장 |
| 5 | 임베딩 모델 | `model` |  | 필수 | 임베딩모델:차원 |
| 6 | 임베딩 | `embedding` |  | 필수 | 임베딩. 컬럼에 차원을 고정하지 않음 |
| 7 | 검색 대상 여부 | `active` |  | 필수 | 검색 대상인지 |

### 9.16 batch_report_jobs (배치 리포트 작업)

batch의 배치 실행이 성공하면 그 결과를 분석해 리포트를 쓰는 작업입니다. 실행 한 건에 작업 하나이고 idempotency_key(batch-report:{execution_id})로 중복을 막습니다. owner_id는 배치를 만든 사용자이고 그 사용자만 리포트를 봅니다. markdown은 리포트 본문, summary는 같은 배치의 다음 실행이 비교용으로 읽는 요약입니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 리포트 작업 ID | `id` | PK | 필수 | 기본키 |
| 2 | 중복 방지 키 | `idempotency_key` | UK | 필수 | UNIQUE. batch-report:{execution_id} |
| 3 | 소유자 ID | `owner_id` |  | 필수 | 배치를 만든 사용자(users.id) |
| 4 | executor 실행 ID | `execution_id` |  | 필수 | executor 실행 id |
| 5 | 배치 ID | `batch_id` |  | 선택 | batch 배치 id |
| 6 | 배치 실행 ID | `batch_run_id` |  | 선택 | batch 실행 id |
| 7 | 실행 정보 | `execution` |  | 필수 | 작업을 시작한 실행 정보 |
| 8 | 작업 상태 | `state` |  | 필수 | QUEUED, COLLECTING, GENERATING, MATERIALIZING, SUCCEEDED, FAILED |
| 9 | 실패 단계 | `failed_stage` |  | 선택 | 실패한 단계 |
| 10 | 리포트 제목 | `title` |  | 선택 | 리포트 제목 |
| 11 | 리포트 본문 | `markdown` |  | 선택 | 리포트 본문 |
| 12 | 요약 | `summary` |  | 선택 | 다음 실행이 읽는 요약 |
| 13 | Artifact ID | `artifact_id` |  | 선택 | 저장된 executor Artifact |
| 14 | 실패 사유 | `error` |  | 선택 | 실패 사유 |
| 15 | 처리 인스턴스 | `lease_owner` |  | 선택 | 처리 중인 인스턴스 |
| 16 | 처리 권한 만료 시각 | `lease_expires_at` |  | 선택 | 처리 권한 만료. 노트북 대기 중에는 다음 시도 시각 |
| 17 | 노트북 대기 시작 시각 | `collecting_since` |  | 선택 | 노트북을 기다리기 시작한 시각 |
| 18 | 종료 시각 | `finished_at` |  | 선택 | 끝난 시각 |
| 19 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 20 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.17 batch_report_events (배치 리포트 이벤트)

리포트 작업의 진행 이벤트입니다. 채팅 이벤트와 같은 형식이라 화면이 같은 컴포넌트로 그립니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 이벤트 번호 | `id` | PK | 필수 | 기본키 |
| 2 | 작업 ID | `job_id` |  | 필수 | 리포트 작업 |
| 3 | 이벤트 종류 | `type` |  | 필수 | 이벤트 종류 |
| 4 | 이벤트 내용 | `data` |  | 필수 | 이벤트 내용 |
| 5 | 생성 시각 | `created_at` |  | 필수 | 보존 정리 기준 |

### 9.18 api_clients (API 클라이언트)

다른 서비스와 에이전트에 발급한 API 키입니다. 키 원문은 저장하지 않고 SHA-256(key_sha256)과 앞부분(key_prefix)만 남깁니다. tenant는 이 키로 만든 실행과 배치가 속할 executor tenant입니다. kind가 standard이면 X-User-Id 사용자의 것만 조회하고, master이면 tenant 전체를 조회합니다. batches_disable_pending은 tenant의 키가 모두 폐기된 뒤 batch에서 그 tenant의 배치를 아직 끄지 못했다는 표시입니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 클라이언트 ID | `id` | PK | 필수 | 기본키 |
| 2 | 클라이언트 이름 | `name` | UK | 필수 | 클라이언트 이름. UNIQUE |
| 3 | tenant | `tenant` |  | 필수 | executor tenant |
| 4 | 키 앞부분 | `key_prefix` |  | 필수 | 키 앞부분(식별용) |
| 5 | 키 해시 | `key_sha256` | UK | 필수 | 키의 SHA-256. UNIQUE |
| 6 | 키 상태 | `status` |  | 필수 | active, revoked |
| 7 | 키 종류 | `kind` |  | 필수 | standard, master |
| 8 | 용도 | `description` |  | 선택 | 용도와 담당자 |
| 9 | 발급자 ID | `created_by` |  | 필수 | 발급한 관리자 |
| 10 | 폐기 시각 | `revoked_at` |  | 선택 | 폐기 시각 |
| 11 | 마지막 사용 시각 | `last_used_at` |  | 선택 | 마지막 사용 시각 |
| 12 | 배치 끄기 대기 | `batches_disable_pending` |  | 필수 | tenant 폐기 뒤 batch 배치 끄기 대기 |
| 13 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 14 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.19 gaia_sessions (gaia 세션 대응)

gaia 채팅 화면의 세션 하나가 우리 세션 하나에 대응합니다. 기본키가 (사용자, gaia 세션 id)라서 다른 사용자가 같은 gaia 세션 id를 보내도 남의 세션에 닿지 않습니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 사용자 ID | `user_id` | PK,FK | 필수 | PK, FK → users.id |
| 2 | gaia 세션 ID | `gaia_session_id` | PK | 필수 | PK. gaia가 준 세션 id |
| 3 | 우리 세션 ID | `session_id` | FK | 필수 | FK → sessions.id |
| 4 | 생성 시각 | `created_at` |  | 필수 | 행을 만든 시각 |
| 5 | 수정 시각 | `updated_at` |  | 필수 | 행을 마지막으로 바꾼 시각 |

### 9.20 alembic_version (마이그레이션 버전)

지금 적용된 마이그레이션 번호 하나를 담습니다. 인스턴스가 기동할 때 이 값을 보고 남은 마이그레이션을 실행합니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 마이그레이션 번호 | `version_num` | PK | 필수 | 적용된 마이그레이션 번호 (예: 0008) |

### 9.21 checkpoint_migrations (체크포인트 스키마 버전)

LangGraph 체크포인트 테이블의 스키마 버전 기록입니다. 기동 때 checkpointer.setup()이 남은 단계를 적용합니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 버전 번호 | `v` | PK | 필수 | 적용한 LangGraph 체크포인트 마이그레이션 번호 |

### 9.22 checkpoints (대화 상태 체크포인트)

Agent 그래프의 단계별 상태입니다. thread_id가 우리 sessions.id이고, run이 멈췄다 이어 갈 때 가장 최근 체크포인트를 읽습니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 스레드 ID | `thread_id` | PK | 필수 | 대화 스레드. 우리 sessions.id 값 (FK 제약 없음) |
| 2 | 체크포인트 이름공간 | `checkpoint_ns` | PK | 필수 | 하위 그래프 구분. 최상위 그래프는 빈 문자열 |
| 3 | 체크포인트 ID | `checkpoint_id` | PK | 필수 | 체크포인트 id. 시간 순서로 정렬되는 값 |
| 4 | 이전 체크포인트 ID | `parent_checkpoint_id` |  | 선택 | 바로 앞 체크포인트 id |
| 5 | 직렬화 형식 | `type` |  | 선택 | 직렬화 형식 (현재 쓰지 않음) |
| 6 | 그래프 상태 | `checkpoint` |  | 필수 | 그래프 상태. 채널별 버전과 값이 작은 채널의 값 |
| 7 | 메타데이터 | `metadata` |  | 필수 | 단계 정보 (source, step, writes 등) |

### 9.23 checkpoint_blobs (체크포인트 채널 값)

큰 채널 값(메시지 이력 등)을 체크포인트와 따로 저장합니다. 같은 버전은 한 번만 저장하고 여러 체크포인트가 함께 참조합니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 스레드 ID | `thread_id` | PK | 필수 | 대화 스레드. 우리 sessions.id 값 |
| 2 | 체크포인트 이름공간 | `checkpoint_ns` | PK | 필수 | 하위 그래프 구분 |
| 3 | 채널 | `channel` | PK | 필수 | 채널 이름 (messages 등) |
| 4 | 채널 버전 | `version` | PK | 필수 | 채널 값의 버전 |
| 5 | 직렬화 형식 | `type` |  | 필수 | 직렬화 형식 (msgpack 등). 값이 없으면 empty |
| 6 | 채널 값 | `blob` |  | 선택 | 직렬화한 채널 값 |

### 9.24 checkpoint_writes (체크포인트 대기 쓰기)

한 단계 안에서 노드가 낸 값 중 아직 다음 체크포인트에 합쳐지지 않은 것입니다. 단계 중간에 멈춰도 끝난 노드를 다시 돌리지 않게 해 줍니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 스레드 ID | `thread_id` | PK | 필수 | 대화 스레드. 우리 sessions.id 값 |
| 2 | 체크포인트 이름공간 | `checkpoint_ns` | PK | 필수 | 하위 그래프 구분 |
| 3 | 체크포인트 ID | `checkpoint_id` | PK | 필수 | 이 쓰기가 속한 체크포인트 |
| 4 | task ID | `task_id` | PK | 필수 | 값을 낸 노드 실행(task) id |
| 5 | 순번 | `idx` | PK | 필수 | task 안에서의 순번 |
| 6 | 채널 | `channel` |  | 필수 | 값을 쓸 채널 |
| 7 | 직렬화 형식 | `type` |  | 선택 | 직렬화 형식 |
| 8 | 값 | `blob` |  | 필수 | 직렬화한 값 |
| 9 | task 경로 | `task_path` |  | 필수 | task의 그래프 안 경로. 정렬에 사용 |

### 9.25 store_migrations (store 스키마 버전)

LangGraph store 테이블의 스키마 버전 기록입니다. 기동 때 store.setup()이 남은 단계를 적용합니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 버전 번호 | `v` | PK | 필수 | 적용한 LangGraph store 마이그레이션 번호 |

### 9.26 store (LangGraph store)

이름공간(prefix)별 키-값 저장소입니다. 이 서비스는 세 가지 이름공간을 씁니다. project_memory.{project_id}는 프로젝트 메모리 주제 본문, tool_effects.{run_id}는 도구가 executor에 한 번만 요청하도록 남긴 결과, batch_memory.{batch_id}는 배치 리포트가 다음 실행에 넘기는 요약입니다. 벡터 색인은 쓰지 않으므로 store_vectors 테이블은 없습니다.

| No | 속성명 | 컬럼 | 키 | 필수 | 설명 |
| --- | --- | --- | --- | --- | --- |
| 1 | 이름공간 | `prefix` | PK | 필수 | 이름공간을 점(.)으로 이은 값. 예: project_memory.{project_id} |
| 2 | 키 | `key` | PK | 필수 | 이름공간 안의 키. 예: 메모리 주제 id, {tool_call_id}:{도구 이름} |
| 3 | 값 | `value` |  | 필수 | 저장한 값 |
| 4 | 생성 시각 | `created_at` |  | 선택 | 행을 만든 시각 |
| 5 | 수정 시각 | `updated_at` |  | 선택 | 행을 마지막으로 바꾼 시각 |
| 6 | 만료 시각 | `expires_at` |  | 선택 | 만료 시각. 이 서비스는 TTL을 쓰지 않아 비어 있음 |
| 7 | TTL(분) | `ttl_minutes` |  | 선택 | TTL(분). 이 서비스는 쓰지 않음 |


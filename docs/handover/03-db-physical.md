# DB 물리 설계서

기준: internal/gaia 브랜치, 마이그레이션 0008, 2026-11-22.
모델은 `src/dtest/core/models.py`, 마이그레이션은 `src/dtest/migrations/versions/`에 있습니다.

## 1. DB 구성

| 항목 | 값 |
| --- | --- |
| DBMS | PostgreSQL (로컬 검증은 16). `vector` 확장(pgvector)이 필요합니다 |
| 데이터베이스 이름 | `agentic` (환경별 `DATABASE_URL`의 마지막 부분) |
| 스키마 | `public` |
| 접속 설정 | `DATABASE_URL` (`postgresql+psycopg://사용자:비밀번호@호스트:5432/agentic`) |
| 드라이버 | psycopg 3. 앱 테이블은 SQLAlchemy 비동기, LangGraph는 psycopg 풀 |
| 문자 집합, 시간대 | UTF-8, 모든 시각 컬럼은 `timestamptz`이고 UTC로 저장 |
| 같은 서버를 쓰는 서비스 | executor, pr-batch (각자 자기 데이터베이스) |
| 서버 연결 한도 | `max_connections` 100, superuser 예약 3 (로컬 기준, 운영 값은 확인 필요) |

확인 필요: 운영 DB의 버전, 서버 주소, 계정과 권한, `max_connections`, dev와 prd가 서버나 데이터베이스를 같이 쓰는지. 5.4절의 주의 사항을 함께 봅니다.

기동 계정에 필요한 권한은 다음과 같습니다.

- 데이터베이스 `agentic`에 대한 테이블 생성, 변경, 인덱스 생성 권한 (마이그레이션을 Pod가 직접 실행하므로)
- `CREATE EXTENSION IF NOT EXISTS vector` 실행 권한. 권한을 줄 수 없으면 DBA가 확장을 먼저 만들어 둡니다. 이미 있으면 이 문장은 아무 일도 하지 않습니다.

## 2. 테이블 목록

| # | 테이블 | 기본키 | 행 증가 | 자동 정리 |
| --- | --- | --- | --- | --- |
| 1 | users | id | 사용자 수 | 없음 |
| 2 | projects | id | 적음 | 없음 (논리 삭제) |
| 3 | project_members | (project_id, user_id) | 적음 | 없음 |
| 4 | sessions | id | 대화 수 | 없음 (논리 삭제) |
| 5 | messages | id | 턴당 2행 안팎 | 없음 |
| 6 | runs | id | 턴당 1행 | 없음 |
| 7 | run_events | id (bigint) | 턴당 수십 행. 가장 빨리 큼 | 30일 |
| 8 | run_requests | (session_id, key) | 턴당 1행 | 1일 |
| 9 | executor_inbox | event_id | 분석 1건당 수 행~수십 행 | 7일 |
| 10 | code_sources | id | 분석 단계당 1행 | 파일만 7일, 행은 유지 |
| 11 | images | id | 첨부 이미지 수 | 세션 삭제 7일 뒤 |
| 12 | memory_history | id (bigint) | 메모리 변경 수 | 없음 |
| 13 | memory_extraction_state | project_id | 프로젝트당 1행 | 없음 |
| 14 | workflows | id | 적음 | 없음 (논리 삭제) |
| 15 | workflow_query_vectors | id (bigint) | 워크플로우 수정 횟수 × 질문 수 | 없음 |
| 16 | batch_report_jobs | id | 배치 실행 성공 1건당 1행 | 없음 |
| 17 | batch_report_events | id (bigint) | 리포트 1건당 수십 행 | 30일 |
| 18 | api_clients | id | 적음 | 없음 |
| 19 | gaia_sessions | (user_id, gaia_session_id) | gaia 대화 수 | 없음 |
| - | alembic_version | version_num | 1행 | Alembic 관리 |
| - | checkpoints, checkpoint_writes, checkpoint_blobs, checkpoint_migrations | LangGraph 정의 | 턴의 그래프 단계마다 | 쉬는 세션은 최신 1개만 남김 |
| - | store, store_migrations | LangGraph 정의 | 프로젝트 메모리 주제 수 | 없음 |

## 3. 테이블 명세

타입 표기: `varchar(36)`은 UUID 문자열입니다. NULL 열이 "N"이면 NOT NULL입니다. 기본값 열의 "(앱)"은 DB 기본값이 아니라 애플리케이션이 넣는 값이라는 뜻입니다. DB에 직접 INSERT할 때는 이 값을 직접 넣어야 합니다.

`created_at`, `updated_at`이 있는 테이블은 애플리케이션이 현재 시각(UTC)을 넣고, `updated_at`은 수정할 때마다 갱신합니다.

### 3.1 users

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| employee_id | varchar(64) | N | | SSO 사번. UNIQUE |
| name | varchar(200) | N | | 이름 |
| english_name | varchar(200) | Y | | 영문 이름 |
| department | varchar(200) | Y | | 부서 |
| email | varchar(320) | Y | | 메일 |
| role | varchar(16) | N | (앱) `user` | `user`, `admin`. DB 제약 없음 |
| is_active | boolean | N | (앱) true | 거짓이면 로그인과 호출 차단 |
| batches_disable_pending | boolean | N | false | 비활성화 뒤 pr-batch 배치 끄기 대기 |
| created_at, updated_at | timestamptz | N | (앱) | |

### 3.2 projects

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| name | varchar(200) | N | | 프로젝트 이름 |
| description | text | N | (앱) 빈 문자열 | 설명 |
| system_prompt | text | N | (앱) 빈 문자열 | 프로젝트 지시문 |
| code_level | integer | Y | | 코드 생성 수준 기본값 |
| is_default | boolean | N | (앱) false | 첫 로그인 때 만든 기본 프로젝트 |
| created_by | varchar(36) | N | | FK → users.id |
| deleted_at | timestamptz | Y | | 논리 삭제 시각 |
| created_at, updated_at | timestamptz | N | (앱) | |

### 3.3 project_members

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| project_id | varchar(36) | N | | PK, FK → projects.id |
| user_id | varchar(36) | N | | PK, FK → users.id |
| role | varchar(16) | N | (앱) `owner` | `owner`, `editor`, `viewer` |
| created_at | timestamptz | N | (앱) | |

### 3.4 sessions

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK. LangGraph thread id로도 사용 |
| project_id | varchar(36) | N | | FK → projects.id |
| user_id | varchar(36) | N | | FK → users.id |
| title | varchar(200) | N | (앱) `새 대화` | 제목 |
| title_source | varchar(16) | N | `initial` | `initial`, `auto`, `user` |
| code_level | integer | Y | | 세션의 코드 생성 수준. 비면 프로젝트 값 |
| active_run_id | varchar(36) | Y | | 진행 중인 run. FK 제약 없음 |
| deleted_at | timestamptz | Y | | 논리 삭제 시각 |
| created_at, updated_at | timestamptz | N | (앱) | |

### 3.5 messages

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| session_id | varchar(36) | N | | FK → sessions.id |
| run_id | varchar(36) | Y | | 이 메시지를 만든 run |
| role | varchar(16) | N | | `user`, `assistant` |
| content | text | N | | 본문 |
| attachments | jsonb | N | (앱) `[]` | 이미지 참조, 결과물 링크 |
| created_at | timestamptz | N | (앱) | |

### 3.6 runs

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| session_id | varchar(36) | N | | FK → sessions.id |
| project_id | varchar(36) | N | | 조회용 사본. FK 제약 없음 |
| user_id | varchar(36) | N | | 조회용 사본. FK 제약 없음 |
| status | varchar(24) | N | | `queued`, `running`, `waiting_input`, `waiting_executor`, `succeeded`, `failed`, `cancelled` |
| model | varchar(64) | N | | 사용한 모델 별칭 |
| input | jsonb | N | | 사용자 입력 |
| resume | jsonb | Y | | 이어 갈 때 넘길 값 |
| waiting | jsonb | Y | | 기다리는 대상. executor 대기면 `execution_id` 포함 |
| error | text | Y | | 실패 사유 |
| cancel_requested | boolean | N | (앱) false | 취소 요청 여부 |
| lease_owner | varchar(128) | Y | | 실행 중인 Pod 식별자 |
| lease_expires_at | timestamptz | Y | | 실행 권한 만료 시각 |
| attempts | integer | N | (앱) 0 | 실행을 가져간 횟수 |
| finished_at | timestamptz | Y | | 끝난 시각 |
| recovery_checked_at | timestamptz | Y | | 놓친 executor 이벤트를 마지막으로 확인한 시각 |
| created_at, updated_at | timestamptz | N | (앱) | |

### 3.7 run_events

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | bigint | N | 자동 증가 | PK. SSE 이벤트 id로 사용 |
| session_id | varchar(36) | N | | 세션 |
| run_id | varchar(36) | N | | run |
| type | varchar(40) | N | | 이벤트 종류 |
| data | jsonb | N | | 이벤트 내용 |
| created_at | timestamptz | N | (앱) | 보존 정리 기준 |

### 3.8 run_requests

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| session_id | varchar(36) | N | | PK |
| key | varchar(128) | N | | PK. 요청의 `Idempotency-Key` |
| request_hash | varchar(64) | N | | 요청 본문 해시. 같은 키에 다른 본문이면 거부 |
| run_id | varchar(36) | N | | 처음 만든 run |
| resumed | boolean | N | | 새 run이 아니라 기존 run을 이어 간 요청인지 |
| created_at | timestamptz | N | (앱) | 보존 정리 기준 |

### 3.9 executor_inbox

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| event_id | varchar(36) | N | | PK. executor가 준 이벤트 id |
| execution_id | varchar(36) | N | | executor 실행 id |
| event_type | varchar(64) | N | | 이벤트 종류 |
| event_sequence | integer | N | | 실행 안에서의 순번 |
| payload | jsonb | N | | executor에 다시 조회해 확인한 이벤트 내용 |
| received_at | timestamptz | N | (앱) | 보존 정리 기준 |

### 3.10 code_sources

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| user_id, project_id | varchar(36) | N | | 소유 정보 |
| session_id, run_id | varchar(36) | N | | 만든 대화와 run |
| tool_call_id | varchar(128) | N | | Agent의 도구 호출 id |
| path | varchar(1024) | N | | executor 기준 상대 경로. UNIQUE (중복 방지 키) |
| sha256 | varchar(64) | N | | 파일 해시 |
| size_bytes | integer | N | | 파일 크기 |
| kind | varchar(16) | N | | `setup`, `tool`, `custom` |
| skill, tool | varchar(128) | Y | | 사용한 skill과 tool |
| call_key | varchar(32) | Y | | 계획 안의 호출 키 |
| tool_version | varchar(64) | Y | | tool 파일 버전 |
| purpose | text | Y | | 코드의 목적 |
| approved_by | varchar(36) | Y | | 승인한 사용자 |
| edited | boolean | Y | | 사용자가 코드를 고쳤는지 |
| execution_id, operation_id, step_id | varchar(36) | Y | | executor 쪽 식별자 |
| created_at | timestamptz | N | (앱) | |
| file_deleted_at | timestamptz | Y | | 파일을 지운 시각 |

### 3.11 images

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| user_id, project_id, session_id | varchar(36) | N | | 소유 정보 |
| run_id | varchar(36) | Y | | 사용한 run |
| name | varchar(255) | Y | | 파일 이름 |
| mime_type | varchar(32) | N | | 형식 |
| size_bytes, width, height | integer | N | | 크기 |
| sha256 | varchar(64) | N | | 파일 해시 |
| path | varchar(1024) | N | | `STORAGE_ROOT` 아래 경로 |
| created_at | timestamptz | N | (앱) | |

### 3.12 memory_history

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | bigint | N | 자동 증가 | PK |
| project_id | varchar(36) | N | | 프로젝트 |
| item_id | varchar(64) | N | | 메모리 주제 id |
| action | varchar(16) | N | | `create`, `update`, `delete` |
| before, after | jsonb | Y | | 변경 전과 후 |
| actor_type | varchar(16) | N | | `user`, `agent` |
| actor_id | varchar(64) | N | | 바꾼 주체 |
| session_id, run_id | varchar(36) | Y | | Agent가 바꾼 경우의 대화와 run |
| created_at | timestamptz | N | (앱) | |

### 3.13 memory_extraction_state

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| project_id | varchar(36) | N | | PK |
| processed_until_at | timestamptz | Y | | 처리한 마지막 메시지의 시각 |
| processed_until_id | varchar(36) | N | 빈 문자열 | 처리한 마지막 메시지 id |
| dirty | boolean | N | false | 처리할 대화가 있음 |
| last_activity_at | timestamptz | N | (앱) | 마지막 대화 시각 |
| pending_turns | integer | N | 0 | 아직 처리하지 않은 턴 수 |
| lease_owner | varchar(128) | Y | | 처리 중인 Pod |
| lease_expires_at | timestamptz | Y | | 처리 권한 만료 시각. 재시도 대기 시각으로도 사용 |
| attempts | integer | N | 0 | 시도 횟수 |
| last_error | text | Y | | 마지막 오류 |
| updated_at | timestamptz | N | (앱) | |

### 3.14 workflows

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| name | varchar(200) | N | | 이름 |
| user_request | text | N | | 원래 사용자 요청 |
| document | jsonb | N | | Workflow 1.0 문서 |
| user_queries | jsonb | N | (앱) `[]` | 검색용 질문 예시 |
| tags | jsonb | N | (앱) `[]` | 태그 |
| lifecycle | varchar(16) | N | (앱) `candidate` | `candidate`, `template` |
| author_id | varchar(36) | N | | FK → users.id |
| source_run_id | varchar(36) | Y | | 이 워크플로우가 나온 run |
| source_workflow_id | varchar(36) | Y | | 복사해 온 원본 |
| revision | integer | N | (앱) 1 | 수정 번호 |
| index_state | varchar(16) | N | (앱) `not_indexed` | `not_indexed`, `ready`, `failed` |
| deleted_at | timestamptz | Y | | 논리 삭제 시각 |
| created_at, updated_at | timestamptz | N | (앱) | |

### 3.15 workflow_query_vectors

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | bigint | N | 자동 증가 | PK |
| workflow_id | varchar(36) | N | | FK → workflows.id |
| revision | integer | N | | 어느 수정 번호의 벡터인지 |
| query | text | N | | 질문 문장 |
| model | varchar(200) | N | | `임베딩모델:차원` |
| embedding | vector | N | | 임베딩. 컬럼에 차원을 고정하지 않음 |
| active | boolean | N | (앱) false | 검색 대상인지 |

### 3.16 batch_report_jobs

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| idempotency_key | varchar(200) | N | | UNIQUE. `batch-report:{execution_id}` |
| owner_id | varchar(64) | N | | 배치를 만든 사용자(users.id) |
| execution_id | varchar(36) | N | | executor 실행 id |
| batch_id | varchar(64) | Y | | pr-batch 배치 id |
| batch_run_id | varchar(64) | Y | | pr-batch 실행 id |
| execution | jsonb | N | | 작업을 시작한 실행 정보 |
| state | varchar(16) | N | (앱) `QUEUED` | `QUEUED`, `COLLECTING`, `GENERATING`, `MATERIALIZING`, `SUCCEEDED`, `FAILED` |
| failed_stage | varchar(16) | Y | | 실패한 단계 |
| title | varchar(200) | Y | | 리포트 제목 |
| markdown | text | Y | | 리포트 본문 |
| summary | text | Y | | 다음 실행이 읽는 요약 |
| artifact_id | varchar(36) | Y | | 저장된 executor Artifact |
| error | text | Y | | 실패 사유 |
| lease_owner | varchar(128) | Y | | 처리 중인 Pod |
| lease_expires_at | timestamptz | Y | | 처리 권한 만료. 노트북 대기 중에는 다음 시도 시각 |
| collecting_since | timestamptz | Y | | 노트북을 기다리기 시작한 시각 |
| finished_at | timestamptz | Y | | 끝난 시각 |
| created_at, updated_at | timestamptz | N | (앱) | |

### 3.17 batch_report_events

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | bigint | N | 자동 증가 | PK |
| job_id | varchar(36) | N | | 리포트 작업 |
| type | varchar(40) | N | | 이벤트 종류 |
| data | jsonb | N | | 이벤트 내용 |
| created_at | timestamptz | N | (앱) | 보존 정리 기준 |

### 3.18 api_clients

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | varchar(36) | N | (앱) UUID | PK |
| name | varchar(64) | N | | 클라이언트 이름. UNIQUE |
| tenant | varchar(64) | N | | executor tenant |
| key_prefix | varchar(32) | N | | 키 앞부분(식별용) |
| key_sha256 | varchar(64) | N | | 키의 SHA-256. UNIQUE |
| status | varchar(16) | N | (앱) `active` | `active`, `revoked` |
| kind | varchar(16) | N | `standard` | `standard`, `master` |
| description | text | Y | | 용도와 담당자 |
| created_by | varchar(36) | N | | 발급한 관리자 |
| revoked_at | timestamptz | Y | | 폐기 시각 |
| last_used_at | timestamptz | Y | | 마지막 사용 시각 |
| batches_disable_pending | boolean | N | false | tenant 폐기 뒤 pr-batch 배치 끄기 대기 |
| created_at, updated_at | timestamptz | N | (앱) | |

### 3.19 gaia_sessions

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| user_id | varchar(36) | N | | PK, FK → users.id |
| gaia_session_id | varchar(200) | N | | PK. gaia가 준 세션 id |
| session_id | varchar(36) | N | | FK → sessions.id |
| created_at, updated_at | timestamptz | N | (앱) | |

## 4. 인덱스

기본키와 UNIQUE 제약의 인덱스는 생략했습니다.

| 테이블 | 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- | --- |
| sessions | ix_sessions_project_id | project_id | 프로젝트의 세션 목록 |
| messages | ix_messages_session_created | (session_id, created_at) | 대화 내용 조회 |
| runs | ix_runs_session_id | session_id | 세션의 run 조회 |
| runs | ix_runs_status | status | 상태별 조회 |
| runs | ix_runs_claim | (status, lease_expires_at) | worker가 가져갈 run 고르기 |
| runs | ix_runs_waiting_execution | `waiting ->> 'execution_id'`, 조건 `status = 'waiting_executor'` | executor 이벤트가 왔을 때 기다리는 run 찾기 |
| run_events | ix_run_events_session_id_id | (session_id, id) | SSE 재접속 시 이어 받기 |
| run_events | ix_run_events_run_id_id | (run_id, id) | run 단위 이벤트 조회 (0005에서 추가) |
| run_events | ix_run_events_created_at | created_at | 보존 정리 |
| run_requests | ix_run_requests_created_at | created_at | 보존 정리 |
| executor_inbox | ix_executor_inbox_execution_id | execution_id | 실행별 이벤트 조회 |
| executor_inbox | ix_executor_inbox_received_at | received_at | 보존 정리 |
| code_sources | ix_code_sources_session_id, _run_id, _execution_id, _created_at | 각 컬럼 | 대화, run, 실행별 조회와 보존 정리 |
| images | ix_images_session_id | session_id | 세션의 이미지 |
| memory_history | ix_memory_history_project_id | project_id | 프로젝트의 메모리 이력 |
| memory_extraction_state | ix_memory_extraction_claim | last_activity_at, 조건 `dirty` | 정리할 프로젝트 고르기 |
| workflows | ix_workflows_author_id | author_id | 내 워크플로우 목록 |
| workflow_query_vectors | ix_workflow_query_vectors_workflow_id | workflow_id | 워크플로우의 벡터 |
| workflow_query_vectors | ix_wqv_hnsw_{차원} | `embedding::vector(차원)` 코사인 HNSW, 조건 `active` | 워크플로우 유사도 검색 |
| batch_report_jobs | ix_batch_report_jobs_owner_id, _execution_id, _batch_id, _state | 각 컬럼 | 내 리포트 목록, 실행·배치별 조회, 처리할 작업 고르기 |
| batch_report_events | ix_batch_report_events_job_id, _created_at | 각 컬럼 | 작업의 이벤트, 보존 정리 |

### 4.1 벡터 인덱스 주의

- `ix_wqv_hnsw_{차원}`은 Alembic이 아니라 기동 시 `WorkflowService.ensure_index()`가 `CREATE INDEX IF NOT EXISTS`로 만듭니다. 이름에 `EMBEDDING_DIMS` 값이 들어갑니다(예: `ix_wqv_hnsw_1024`).
- HNSW 인덱스는 2,000차원 이하만 됩니다. `EMBEDDING_DIMS`는 임베딩 모델의 실제 출력 차원과 같아야 합니다.
- `EMBEDDING_DIMS`나 임베딩 모델을 바꾸면 새 차원의 인덱스가 하나 더 생기고, 예전 벡터는 `model` 값이 달라 검색에서 빠집니다. 기존 워크플로우는 다시 색인해야 검색되고, 예전 인덱스는 직접 지워야 합니다.
- `EMBEDDING_PROVIDER`가 `none`이면 인덱스를 만들지 않고 검색 추천만 꺼집니다.

## 5. 마이그레이션

### 5.1 적용 방식

Pod가 시작할 때 `AUTO_MIGRATE`가 true(기본)이면 아래를 순서대로 한 번 실행합니다(`src/dtest/core/bootstrap.py`의 `migrate`).

1. `pg_advisory_lock(7340001)`을 잡습니다. 여러 Pod가 동시에 떠도 한 Pod만 진행하고 나머지는 기다립니다.
2. `CREATE EXTENSION IF NOT EXISTS vector`
3. Alembic `upgrade head` (앱 테이블)
4. LangGraph checkpointer와 store의 `setup()` (LangGraph 테이블)
5. 예전 항목형 프로젝트 메모리를 기본 주제로 옮김 (이미 옮겼으면 아무 일도 하지 않음)
6. 워크플로우 벡터 인덱스 생성
7. 잠금 해제

`AUTO_MIGRATE`를 false로 두면 Pod는 스키마를 건드리지 않습니다. 이때는 배포 전에 같은 이미지와 같은 설정으로 `python scripts/migrate.py`를 한 번 실행합니다. 실패하면 0이 아닌 코드로 끝납니다.

### 5.2 이력

| 번호 | 내용 |
| --- | --- |
| 0001 | 기준 스키마. 테이블 16개와 인덱스 |
| 0002 | memory_extraction_state 테이블과 `ix_memory_extraction_claim` |
| 0003 | api_clients 테이블, users에 `batches_disable_pending` 컬럼 |
| 0004 | gaia_sessions 테이블. 이미 있으면 건너뜀 |
| 0005 | `ix_run_events_run_id_id` 인덱스 |
| 0006 | api_clients의 `pending` 상태를 `active`로 변경 (데이터만) |
| 0007 | api_clients에 `batches_disable_pending` 컬럼 |
| 0008 | api_clients에 `kind` 컬럼 (기본값 `standard`) |

0004의 내력: gaia_sessions는 원래 internal/gaia에서 0002번이었습니다. main의 0002, 0003과 번호가 겹쳐 0004로 옮겼습니다. 예전 0002(gaia_sessions)로 올린 DB가 남아 있다면 테이블은 있지만 지금의 0002, 0003이 빠진 상태입니다. 그런 DB는 아래를 실행한 뒤 다시 올리면 기존 테이블은 그대로 두고 나머지가 적용됩니다.

```sql
UPDATE alembic_version SET version_num = '0001';
```

### 5.3 새 마이그레이션 작성 규칙

- 파일은 `src/dtest/migrations/versions/`에 `NNNN_설명.py`로 만들고 `down_revision`을 직전 번호로 둡니다.
- 이전 버전 코드가 계속 동작하는 변경만 합니다. 컬럼 추가는 NULL 허용이거나 DB 기본값(`server_default`)을 둡니다. 인덱스는 추가만 합니다. 롤링 업데이트 중에는 새 스키마 위에서 옛 Pod가 돌기 때문입니다.
- 컬럼 삭제나 이름 변경은 두 번에 나눕니다. 먼저 코드가 그 컬럼을 쓰지 않게 배포하고, 다음 배포에서 지웁니다.
- 큰 테이블(run_events)의 인덱스 추가는 테이블 잠금 시간을 확인합니다. Alembic 기본은 `CREATE INDEX`라 쓰기가 잠깁니다.
- 모델(`models.py`)과 마이그레이션을 같이 고칩니다. 로컬에서 빈 DB에 처음부터 올려 보고, 직전 버전 DB에서도 올려 봅니다.
- main과 internal/gaia 양쪽에 같은 번호로 들어가야 합니다. 한쪽에만 번호를 쓰면 0004와 같은 충돌이 다시 생깁니다.

### 5.4 주의

- 마이그레이션이 실패하면 `AUTO_MIGRATE`가 켜진 모든 Pod가 시작에 실패합니다. 롤링 업데이트로 옛 Pod가 이미 내려갔다면 서비스가 멈춥니다. 운영은 `AUTO_MIGRATE: false`와 사전 실행을 권장합니다.
- 두 환경(예: dev와 prd)이 같은 데이터베이스를 가리키면 스키마와 데이터를 함께 씁니다. dev에 새 마이그레이션을 배포하는 순간 prd의 스키마도 바뀌고, 한쪽 worker가 다른 쪽의 run을 가져가 실행합니다. 환경마다 데이터베이스를 따로 두어야 합니다. 서버만 같이 쓰는 것은 연결 수만 관리하면 됩니다(6.2절).

## 6. 연결 풀

### 6.1 풀 구성

프로세스(Pod) 하나가 풀 두 개를 가집니다. `pg_stat_activity.application_name`으로 구분됩니다.

| 풀 | application_name | 용도 | 크기 설정 | Pod당 최대 |
| --- | --- | --- | --- | --- |
| 앱 풀 | `pr-agentic-app` | 앱 테이블 (SQLAlchemy) | `DB_POOL_SIZE` 3, 같은 수만큼 overflow | 6 |
| 그래프 풀 | `pr-agentic-graph` | LangGraph 체크포인트와 store (psycopg) | `CHECKPOINT_POOL_SIZE` 8 | 8 |

- 앱 풀은 연결을 빌려줄 때마다 살아 있는지 확인합니다(`pool_pre_ping`).
- 그래프 풀은 연결을 빌려줄 때마다 확인하고 죽은 연결은 새로 만듭니다. TCP keepalive를 켜서 `DB_KEEPALIVE_IDLE_SECONDS`(60초) 동안 조용하면 10초 간격으로 확인 패킷을 보내고 3번 무응답이면 끊습니다. Pod와 DB 사이 장비(방화벽, LB, NAT)가 조용한 연결을 끊어 "server closed the connection unexpectedly"로 턴이 실패하던 문제 때문에 넣은 것입니다. 이 값은 그 장비의 idle 제한 시간보다 짧아야 합니다.
- 그래프 풀에서 연결을 `CHECKPOINT_POOL_TIMEOUT_SECONDS`(30초) 안에 얻지 못하면 그 턴이 실패합니다. `CHECKPOINT_POOL_SIZE`는 `RUN_CONCURRENCY`의 절반 이상으로 둡니다.
- 그래프 풀은 `prepare_threshold 0`(prepared statement 미사용)이라 PgBouncer transaction 모드 뒤에 둘 수 있습니다.

### 6.2 연결 예산

같은 PostgreSQL 서버를 세 서비스가 씁니다. 모든 풀이 꽉 찼을 때의 최대 연결 수입니다.

| 서비스 | Pod당 최대 | 구성 | 평소 Pod | 최대 Pod |
| --- | --- | --- | --- | --- |
| pr-agentic-service | 14 | 앱 풀 3 + overflow 3, 그래프 풀 8 | 2 | 4 (HPA) |
| executor | 16 | 풀 5 + overflow 10, readiness 1 | 1 | 1 |
| pr-batch | 6 | 풀 2 + overflow 4 | 1 | 2 (HPA) |

| 상황 | 합계 |
| --- | --- |
| 평소 (2 + 1 + 1) | 50 |
| 우리 배포 중 (Pod 1개 추가) | 64 |
| 모두 최대 (4 + 1 + 2) | 84 |

`max_connections` 100에서 superuser 예약 3을 빼면 97이므로 최대일 때 13이 남습니다. 이 여유는 운영 접속과 마이그레이션 실행이 씁니다. Pod 수(HPA max), `DB_POOL_SIZE`, `CHECKPOINT_POOL_SIZE` 중 하나라도 올릴 때는 이 표를 다시 계산합니다. DB 계정에 연결 한도(`CONNECTION LIMIT`)가 걸려 있다면 위 서비스별 최대보다 커야 합니다.

현재 연결 수는 아래로 봅니다.

```sql
SELECT application_name, state, count(*)
FROM pg_stat_activity
WHERE application_name LIKE 'pr-agentic-%'
GROUP BY 1, 2 ORDER BY 1, 2;
```

## 7. 용량과 증가

| 테이블 | 증가 요인 | 상한을 두는 장치 |
| --- | --- | --- |
| run_events | 턴마다 상태, 도구 호출, 계획 카드, 최종 답변 이벤트 | 30일 보존. 토큰 스트리밍과 executor 진행 이벤트는 저장하지 않음 |
| checkpoints, checkpoint_writes, checkpoint_blobs | 실행 중 그래프 단계마다 상태 저장 (상태 1개 약 20KB) | 쉬는 세션은 최신 1개만 남김(1시간마다 200세션씩) |
| executor_inbox | 분석 1건의 executor 이벤트 | 7일 보존 |
| messages, runs | 턴 수 | 없음. 계속 증가 |
| batch_report_jobs | 배치 실행 수. 리포트 본문(markdown) 포함 | 없음. 계속 증가 |
| code_sources | 분석 단계 수 | 행은 남고 파일만 7일 뒤 삭제 |
| workflow_query_vectors | 워크플로우 수정마다 새 벡터. 예전 revision 벡터도 남음 | 없음 |

보존 정리는 worker 안의 `Retention` 루프가 1시간마다 실행하고, 한 번에 5,000행씩 `FOR UPDATE SKIP LOCKED`로 나눠 지웁니다. 여러 Pod가 동시에 돌아도 서로 기다리지 않습니다. 실패하면 로그에 `retention_sweep_failed`가 남고 다음 주기에 다시 시도합니다.

삭제만으로는 디스크가 줄지 않습니다. 반환은 PostgreSQL autovacuum이 맡으므로 run_events와 checkpoint 계열 테이블의 autovacuum이 돌고 있는지 확인합니다.

테이블 크기는 아래로 봅니다.

```sql
SELECT relname,
       pg_size_pretty(pg_total_relation_size(relid)) AS total,
       n_live_tup, n_dead_tup, last_autovacuum
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 15;
```

보존 정리가 도는지는 가장 오래된 이벤트의 날짜로 확인합니다. 30일보다 훨씬 오래된 행이 있으면 정리가 멈춘 것입니다.

```sql
SELECT min(created_at) FROM run_events;
SELECT min(received_at) FROM executor_inbox;
```

## 8. 백업과 복구

확인 필요: 운영 DB의 백업 주기, 보관 기간, 복구 절차, 담당 DBA. 저장소에는 기록이 없습니다.

백업 범위를 정할 때 알아야 할 점은 다음과 같습니다.

- 앱 테이블과 LangGraph 테이블(checkpoints 계열, store)은 같은 시점으로 함께 백업하고 함께 복구해야 합니다. 프로젝트 메모리 본문은 store에, 그 이력은 memory_history에 있고, 멈춰 있는 run의 상태는 runs와 checkpoints에 나뉘어 있습니다.
- executor의 DB와 공유 저장소는 별도 시스템입니다. 우리 DB만 과거 시점으로 되돌리면 그 뒤에 만들어진 executor 실행과 Artifact는 우리 쪽 기록이 없는 상태가 됩니다. 반대로 executor만 되돌리면 우리 run이 가리키는 `execution_id`가 executor에 없어 그 run은 이어 갈 수 없습니다.
- Redis는 백업 대상이 아닙니다. 비면 사용자가 다시 로그인하고, executor 이벤트 소비자 그룹은 다음 읽기 때 다시 만들어집니다.
- 복구 뒤에는 `alembic_version`의 값이 배포할 이미지의 마이그레이션 번호 이하인지 확인합니다. 더 높으면 그 이미지는 모르는 스키마 위에서 돌게 됩니다.

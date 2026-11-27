# Table 정의서

| 항목 | 내용 |
| --- | --- |
| 시스템 | gaia-api-service (사내 데이터 분석 Agent 서비스) |
| 스키마 버전 | 마이그레이션 0008 |
| DBMS | PostgreSQL, `vector` 확장(pgvector) 필요. 스키마 `public` |
| 데이터베이스 | dev: `dtest` / prd: `dtestprd` (`DATABASE_URL`의 마지막 부분) |
| 모델 정의 | `src/dtest/core/models.py`, `src/dtest/gaia_bridge/models.py` |
| 마이그레이션 | `src/dtest/migrations/versions/` (Alembic, 0001~0008) |
| 같은 내용의 엑셀 | `06-table-definition.xlsx` |

## 1. 표기 규칙

| 항목 | 규칙 |
| --- | --- |
| 타입 | `varchar(36)`은 UUID 문자열입니다. 시각 컬럼은 모두 `timestamptz`이고 UTC로 저장합니다 |
| NULL | N이면 NOT NULL입니다 |
| 키 | PK 기본키, FK 외래키 제약, UK UNIQUE 제약 |
| 기본값 | (앱)은 DB 기본값이 아니라 애플리케이션이 넣는 값입니다. DB에 직접 INSERT할 때는 직접 넣어야 합니다 |
| 참조 | FK 제약은 핵심 계층(사용자, 프로젝트, 세션, 메시지, run, 워크플로우)에만 있습니다. 나머지는 값으로만 참조합니다 |
| 삭제 | 프로젝트, 세션, 워크플로우는 지우지 않고 `deleted_at`에 시각을 적습니다(논리 삭제) |

## 2. 테이블 목록

| No | 테이블 | 한글명 | 영역 | 기본키 | 컬럼 수 | 행 증가 | 자동 정리 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | users | 사용자 | 사용자와 프로젝트 | id | 11 | 사용자 수 | 없음 |
| 2 | projects | 프로젝트 | 사용자와 프로젝트 | id | 10 | 적음 | 없음 (논리 삭제) |
| 3 | project_members | 프로젝트 구성원 | 사용자와 프로젝트 | (project_id, user_id) | 4 | 적음 | 없음 |
| 4 | sessions | 채팅 세션 | 대화 | id | 10 | 대화 수 | 없음 (논리 삭제) |
| 5 | messages | 메시지 | 대화 | id | 7 | 턴당 2행 안팎 | 없음 |
| 6 | runs | 실행 | 실행 | id | 18 | 턴당 1행 | 없음 |
| 7 | run_events | 실행 이벤트 | 실행 | id (bigint) | 6 | 턴당 수십 행. 가장 빨리 큼 | 30일 |
| 8 | run_requests | 실행 요청 키 | 실행 | (session_id, key) | 6 | 턴당 1행 | 1일 |
| 9 | executor_inbox | executor 이벤트 보관함 | executor 연동 | event_id | 6 | 분석 1건당 수 행~수십 행 | 7일 |
| 10 | code_sources | 코드 파일 기록 | executor 연동 | id | 22 | 분석 단계당 1행 | 파일만 7일, 행은 유지 |
| 11 | images | 이미지 | 대화 | id | 13 | 첨부 이미지 수 | 세션 삭제 7일 뒤 |
| 12 | memory_history | 메모리 변경 이력 | 프로젝트 메모리 | id (bigint) | 11 | 메모리 변경 수 | 없음 |
| 13 | memory_extraction_state | 메모리 정리 상태 | 프로젝트 메모리 | project_id | 11 | 프로젝트당 1행 | 없음 |
| 14 | workflows | 워크플로우 | 워크플로우 | id | 15 | 적음 | 없음 (논리 삭제) |
| 15 | workflow_query_vectors | 워크플로우 검색 벡터 | 워크플로우 | id (bigint) | 7 | 워크플로우 수정 횟수 × 질문 수 | 없음 |
| 16 | batch_report_jobs | 배치 리포트 작업 | 배치 리포트 | id | 20 | 배치 실행 성공 1건당 1행 | 없음 |
| 17 | batch_report_events | 배치 리포트 이벤트 | 배치 리포트 | id (bigint) | 5 | 리포트 1건당 수십 행 | 30일 |
| 18 | api_clients | API 클라이언트 | 서비스 간 인증 | id | 14 | 적음 | 없음 |
| 19 | gaia_sessions | gaia 세션 대응 | gaia 연동 | (user_id, gaia_session_id) | 5 | gaia 대화 수 | 없음 |
| - | alembic_version | 마이그레이션 버전 | 마이그레이션 | version_num | 1 | 1행 | Alembic 관리 |
| - | checkpoint_migrations | 체크포인트 스키마 버전 | LangGraph 체크포인트 | v | 1 | 적용한 마이그레이션 수 | LangGraph 관리 |
| - | checkpoints | 대화 상태 체크포인트 | LangGraph 체크포인트 | (thread_id, checkpoint_ns, checkpoint_id) | 7 | 턴의 그래프 단계마다 | 쉬는 세션은 최신 1개만 남김 |
| - | checkpoint_blobs | 체크포인트 채널 값 | LangGraph 체크포인트 | (thread_id, checkpoint_ns, channel, version) | 6 | 채널 값이 바뀔 때마다 | 쉬는 세션은 최신 체크포인트가 쓰는 것만 남김 |
| - | checkpoint_writes | 체크포인트 대기 쓰기 | LangGraph 체크포인트 | (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) | 9 | 단계 안의 노드 실행마다 | 쉬는 세션은 최신 체크포인트 것만 남김 |
| - | store_migrations | store 스키마 버전 | LangGraph store | v | 1 | 적용한 마이그레이션 수 | LangGraph 관리 |
| - | store | LangGraph store | LangGraph store | (prefix, key) | 7 | 메모리 주제 수 + 도구 실행 수 + 배치 실행 수 | 없음 (TTL 쓰지 않음) |

모두 26개 테이블, 233개 컬럼입니다. 1~19는 앱 테이블이고, 번호가 없는 7개는 LangGraph와 Alembic이 같은 데이터베이스에 만드는 테이블입니다.

## 3. 테이블 정의

### 3.1 users (사용자)

| 항목 | 내용 |
| --- | --- |
| 영역 | 사용자와 프로젝트 |
| 기본키 | id |
| 설명 | SSO로 처음 로그인할 때 만들어집니다. employee_id(사번)가 사람을 구분하는 값이고 중복될 수 없습니다. role은 user 또는 admin입니다. is_active가 거짓이면 로그인과 API 호출이 모두 막히고, 진행 중이던 run과 executor 커널이 취소됩니다. batches_disable_pending은 비활성화된 사용자의 배치를 batch에서 아직 끄지 못했다는 표시이고, worker가 성공할 때까지 다시 시도합니다. |
| 행 증가 | 사용자 수 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 사용자 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `employee_id` | 사번 | varchar(64) | N | UK |  | SSO 사번. UNIQUE |
| 3 | `name` | 이름 | varchar(200) | N |  |  | SSO에서 받은 이름 |
| 4 | `english_name` | 영문 이름 | varchar(200) | Y |  |  | 영문 이름 |
| 5 | `department` | 부서 | varchar(200) | Y |  |  | 부서 |
| 6 | `email` | 메일 | varchar(320) | Y |  |  | 메일 |
| 7 | `role` | 권한 | varchar(16) | N |  | (앱) user | user, admin. DB 제약 없음 |
| 8 | `is_active` | 활성 여부 | boolean | N |  | (앱) true | 거짓이면 로그인과 호출 차단 |
| 9 | `batches_disable_pending` | 배치 끄기 대기 | boolean | N |  | false | 비활성화 뒤 batch 배치 끄기 대기 |
| 10 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 11 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

없음

### 3.2 projects (프로젝트)

| 항목 | 내용 |
| --- | --- |
| 영역 | 사용자와 프로젝트 |
| 기본키 | id |
| 설명 | 대화를 묶는 단위입니다. system_prompt는 그 프로젝트의 모든 대화에 들어가는 지시문, code_level은 코드 생성 수준의 기본값입니다. 사용자마다 첫 로그인 때 기본 프로젝트(is_default)가 하나 만들어집니다. |
| 행 증가 | 적음 |
| 자동 정리 | 없음 (논리 삭제) |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 프로젝트 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `name` | 프로젝트 이름 | varchar(200) | N |  |  | 프로젝트 이름 |
| 3 | `description` | 설명 | text | N |  | (앱) 빈 문자열 | 설명 |
| 4 | `system_prompt` | 프로젝트 지시문 | text | N |  | (앱) 빈 문자열 | 프로젝트 지시문 |
| 5 | `code_level` | 기본 코드 생성 수준 | integer | Y |  |  | 코드 생성 수준 기본값 |
| 6 | `is_default` | 기본 프로젝트 여부 | boolean | N |  | (앱) false | 첫 로그인 때 만든 기본 프로젝트 |
| 7 | `created_by` | 생성자 ID | varchar(36) | N | FK |  | 프로젝트를 만든 사용자. FK → users.id |
| 8 | `deleted_at` | 삭제 시각 | timestamptz | Y |  |  | 논리 삭제 시각 |
| 9 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 10 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

없음

### 3.3 project_members (프로젝트 구성원)

| 항목 | 내용 |
| --- | --- |
| 영역 | 사용자와 프로젝트 |
| 기본키 | (project_id, user_id) |
| 설명 | 프로젝트와 사용자의 다대다 관계입니다. 현재는 만든 사람이 owner로 한 줄 들어가는 것이 전부이고, 프로젝트 공유 기능을 나중에 붙일 수 있게 테이블만 준비되어 있습니다. 프로젝트 접근 권한은 이 테이블로 판단합니다. |
| 행 증가 | 적음 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `project_id` | 프로젝트 ID | varchar(36) | N | PK,FK |  | PK, FK → projects.id |
| 2 | `user_id` | 사용자 ID | varchar(36) | N | PK,FK |  | PK, FK → users.id |
| 3 | `role` | 구성원 역할 | varchar(16) | N |  | (앱) owner | owner, editor, viewer |
| 4 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

없음

### 3.4 sessions (채팅 세션)

| 항목 | 내용 |
| --- | --- |
| 영역 | 대화 |
| 기본키 | id |
| 설명 | 프로젝트 안의 대화 하나입니다. active_run_id는 지금 진행 중인 run이고, 값이 있는 동안에는 새 턴을 시작할 수 없습니다(세션당 한 턴 규칙). title_source는 제목이 어떻게 정해졌는지입니다. 첫 메시지에서 딴 것은 initial, 첫 답변 뒤 LLM이 요약한 것은 auto, 사용자가 바꾼 것은 user입니다. 세션 id는 LangGraph 체크포인트의 thread id로도 쓰입니다. |
| 행 증가 | 대화 수 |
| 자동 정리 | 없음 (논리 삭제) |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 세션 ID | varchar(36) | N | PK | (앱) UUID | PK. LangGraph thread id로도 사용 |
| 2 | `project_id` | 프로젝트 ID | varchar(36) | N | FK |  | FK → projects.id |
| 3 | `user_id` | 사용자 ID | varchar(36) | N | FK |  | FK → users.id |
| 4 | `title` | 제목 | varchar(200) | N |  | (앱) 새 대화 | 제목 |
| 5 | `title_source` | 제목 출처 | varchar(16) | N |  | initial | initial, auto, user |
| 6 | `code_level` | 코드 생성 수준 | integer | Y |  |  | 세션의 코드 생성 수준. 비면 프로젝트 값 |
| 7 | `active_run_id` | 진행 중 실행 ID | varchar(36) | Y |  |  | 진행 중인 run. FK 제약 없음 |
| 8 | `deleted_at` | 삭제 시각 | timestamptz | Y |  |  | 논리 삭제 시각 |
| 9 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 10 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_sessions_project_id | project_id | 프로젝트의 세션 목록 |

### 3.5 messages (메시지)

| 항목 | 내용 |
| --- | --- |
| 영역 | 대화 |
| 기본키 | id |
| 설명 | 화면에 보이는 대화 내용입니다. Agent가 실제로 참고하는 대화 이력은 체크포인트에 따로 있으므로, 이 테이블을 고쳐도 Agent의 기억은 바뀌지 않습니다. attachments에는 이미지 참조와 결과물 링크가 들어갑니다. |
| 행 증가 | 턴당 2행 안팎 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 메시지 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `session_id` | 세션 ID | varchar(36) | N | FK |  | FK → sessions.id |
| 3 | `run_id` | 실행 ID | varchar(36) | Y |  |  | 이 메시지를 만든 run |
| 4 | `role` | 작성 주체 | varchar(16) | N |  |  | user, assistant |
| 5 | `content` | 본문 | text | N |  |  | 본문 |
| 6 | `attachments` | 첨부 | jsonb | N |  | (앱) [] | 이미지 참조, 결과물 링크 |
| 7 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_messages_session_created | (session_id, created_at) | 대화 내용 조회 |

### 3.6 runs (실행)

| 항목 | 내용 |
| --- | --- |
| 영역 | 실행 |
| 기본키 | id |
| 설명 | 사용자 메시지 한 건에 대한 Agent 실행 한 턴입니다. 작업 큐 역할도 합니다. worker는 status와 lease_expires_at을 보고 가져갈 run을 고릅니다. |
| 행 증가 | 턴당 1행 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 실행 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `session_id` | 세션 ID | varchar(36) | N | FK |  | FK → sessions.id |
| 3 | `project_id` | 프로젝트 ID | varchar(36) | N |  |  | 대화의 프로젝트. 조회용 사본 (projects.id 값, FK 제약 없음) |
| 4 | `user_id` | 사용자 ID | varchar(36) | N |  |  | 요청한 사용자. 조회용 사본 (users.id 값, FK 제약 없음) |
| 5 | `status` | 실행 상태 | varchar(24) | N |  |  | queued, running, waiting_input, waiting_executor, succeeded, failed, cancelled |
| 6 | `model` | 모델 별칭 | varchar(64) | N |  |  | 사용한 모델 별칭 |
| 7 | `input` | 입력 | jsonb | N |  |  | 사용자 입력 |
| 8 | `resume` | 재개 값 | jsonb | Y |  |  | 이어 갈 때 넘길 값 |
| 9 | `waiting` | 대기 대상 | jsonb | Y |  |  | 기다리는 대상. executor 대기면 execution_id 포함 |
| 10 | `error` | 실패 사유 | text | Y |  |  | 실패 사유 |
| 11 | `cancel_requested` | 취소 요청 여부 | boolean | N |  | (앱) false | 취소 요청 여부 |
| 12 | `lease_owner` | 처리 인스턴스 | varchar(128) | Y |  |  | 실행 중인 인스턴스 식별자 |
| 13 | `lease_expires_at` | 처리 권한 만료 시각 | timestamptz | Y |  |  | 실행 권한 만료 시각 |
| 14 | `attempts` | 가져간 횟수 | integer | N |  | (앱) 0 | 실행을 가져간 횟수 |
| 15 | `finished_at` | 종료 시각 | timestamptz | Y |  |  | 끝난 시각 |
| 16 | `recovery_checked_at` | 이벤트 복구 확인 시각 | timestamptz | Y |  |  | 놓친 executor 이벤트를 마지막으로 확인한 시각 |
| 17 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 18 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_runs_session_id | session_id | 세션의 run 조회 |
| ix_runs_status | status | 상태별 조회 |
| ix_runs_claim | (status, lease_expires_at) | worker가 가져갈 run 고르기 |
| ix_runs_waiting_execution | waiting ->> 'execution_id', 조건 status = 'waiting_executor' | executor 이벤트가 왔을 때 기다리는 run 찾기 |

### 3.7 run_events (실행 이벤트)

| 항목 | 내용 |
| --- | --- |
| 영역 | 실행 |
| 기본키 | id (bigint) |
| 설명 | 화면에 실시간으로 보내는 이벤트 중 저장하는 것들입니다(상태 변경, 도구 호출, 계획 카드, 최종 답변 등). 브라우저가 끊겼다 다시 붙으면 마지막으로 받은 id 다음부터 이 테이블에서 다시 읽어 줍니다. 토큰 단위 스트리밍과 executor 진행 이벤트는 저장하지 않습니다. |
| 행 증가 | 턴당 수십 행. 가장 빨리 큼 |
| 자동 정리 | 30일 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 이벤트 번호 | bigint | N | PK | 자동 증가 | PK. SSE 이벤트 id로 사용 |
| 2 | `session_id` | 세션 ID | varchar(36) | N |  |  | 이벤트가 속한 대화 (sessions.id 값) |
| 3 | `run_id` | 실행 ID | varchar(36) | N |  |  | 이벤트를 낸 run (runs.id 값) |
| 4 | `type` | 이벤트 종류 | varchar(40) | N |  |  | 이벤트 종류 |
| 5 | `data` | 이벤트 내용 | jsonb | N |  |  | 이벤트 내용 |
| 6 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 보존 정리 기준 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_run_events_session_id_id | (session_id, id) | SSE 재접속 시 이어 받기 |
| ix_run_events_run_id_id | (run_id, id) | run 단위 이벤트 조회 (0005에서 추가) |
| ix_run_events_created_at | created_at | 보존 정리 |

### 3.8 run_requests (실행 요청 키)

| 항목 | 내용 |
| --- | --- |
| 영역 | 실행 |
| 기본키 | (session_id, key) |
| 설명 | POST /sessions/{id}/runs의 Idempotency-Key를 하루 동안 기억합니다. 같은 키로 같은 요청이 다시 오면 새 run을 만들지 않고 처음 만든 run을 돌려줍니다. |
| 행 증가 | 턴당 1행 |
| 자동 정리 | 1일 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `session_id` | 세션 ID | varchar(36) | N | PK |  | 기본키 |
| 2 | `key` | 요청 키 | varchar(128) | N | PK |  | PK. 요청의 Idempotency-Key |
| 3 | `request_hash` | 요청 해시 | varchar(64) | N |  |  | 요청 본문 해시. 같은 키에 다른 본문이면 거부 |
| 4 | `run_id` | 실행 ID | varchar(36) | N |  |  | 처음 만든 run |
| 5 | `resumed` | 재개 요청 여부 | boolean | N |  |  | 새 run이 아니라 기존 run을 이어 간 요청인지 |
| 6 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 보존 정리 기준 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_run_requests_created_at | created_at | 보존 정리 |

### 3.9 executor_inbox (executor 이벤트 보관함)

| 항목 | 내용 |
| --- | --- |
| 영역 | executor 연동 |
| 기본키 | event_id |
| 설명 | executor가 Redis 스트림으로 보낸 이벤트를 중복 없이 보관합니다. event_id가 기본키라 같은 이벤트가 두 번 와도 한 줄만 남습니다. executor를 기다리던 run은 이 테이블의 이벤트를 근거로 다시 시작됩니다. |
| 행 증가 | 분석 1건당 수 행~수십 행 |
| 자동 정리 | 7일 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `event_id` | 이벤트 ID | varchar(36) | N | PK |  | PK. executor가 준 이벤트 id |
| 2 | `execution_id` | executor 실행 ID | varchar(36) | N |  |  | executor 실행 id |
| 3 | `event_type` | 이벤트 종류 | varchar(64) | N |  |  | 이벤트 종류 |
| 4 | `event_sequence` | 이벤트 순번 | integer | N |  |  | 실행 안에서의 순번 |
| 5 | `payload` | 이벤트 내용 | jsonb | N |  |  | executor에 다시 조회해 확인한 이벤트 내용 |
| 6 | `received_at` | 수신 시각 | timestamptz | N |  | (앱) | 보존 정리 기준 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_executor_inbox_execution_id | execution_id | 실행별 이벤트 조회 |
| ix_executor_inbox_received_at | received_at | 보존 정리 |

### 3.10 code_sources (코드 파일 기록)

| 항목 | 내용 |
| --- | --- |
| 영역 | executor 연동 |
| 기본키 | id |
| 설명 | Agent가 executor로 보낸 코드 파일 하나하나의 기록입니다. 어떤 run의 어떤 도구 호출에서 만들어졌는지, 어떤 skill과 tool인지, 사용자가 승인하거나 고쳤는지, executor의 어느 실행 단계가 되었는지를 잇습니다. 파일은 전달 수단일 뿐이고, 실제 실행 기록은 executor가 제출 시점에 뜬 사본과 노트북입니다. 그래서 파일은 7일 뒤 지우고(file_deleted_at) 이 행만 남깁니다. |
| 행 증가 | 분석 단계당 1행 |
| 자동 정리 | 파일만 7일, 행은 유지 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 코드 파일 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `user_id` | 사용자 ID | varchar(36) | N |  |  | 코드를 만든 사용자 (users.id 값, FK 제약 없음) |
| 3 | `project_id` | 프로젝트 ID | varchar(36) | N |  |  | 코드가 속한 프로젝트 (projects.id 값, FK 제약 없음) |
| 4 | `session_id` | 세션 ID | varchar(36) | N |  |  | 이 코드를 만든 대화 (sessions.id 값) |
| 5 | `run_id` | 실행 ID | varchar(36) | N |  |  | 이 코드를 만든 run (runs.id 값) |
| 6 | `tool_call_id` | 도구 호출 ID | varchar(128) | N |  |  | Agent의 도구 호출 id |
| 7 | `path` | 파일 경로 | varchar(1024) | N | UK |  | executor 기준 상대 경로. UNIQUE (중복 방지 키) |
| 8 | `sha256` | 파일 해시 | varchar(64) | N |  |  | 파일 해시 |
| 9 | `size_bytes` | 파일 크기 | integer | N |  |  | 파일 크기(바이트) |
| 10 | `kind` | 코드 종류 | varchar(16) | N |  |  | setup, tool, custom |
| 11 | `skill` | skill 이름 | varchar(128) | Y |  |  | 사용한 skill 이름. tool 코드가 아니면 비어 있음 |
| 12 | `tool` | tool 이름 | varchar(128) | Y |  |  | 사용한 tool 이름. tool 코드가 아니면 비어 있음 |
| 13 | `call_key` | 호출 키 | varchar(32) | Y |  |  | 계획 안의 호출 키 |
| 14 | `tool_version` | tool 버전 | varchar(64) | Y |  |  | tool 파일 버전 |
| 15 | `purpose` | 목적 | text | Y |  |  | 코드의 목적 |
| 16 | `approved_by` | 승인자 ID | varchar(36) | Y |  |  | 승인한 사용자 |
| 17 | `edited` | 사용자 수정 여부 | boolean | Y |  |  | 사용자가 코드를 고쳤는지 |
| 18 | `execution_id` | executor 실행 ID | varchar(36) | Y |  |  | 이 코드를 실행한 executor 실행 id |
| 19 | `operation_id` | executor 작업 ID | varchar(36) | Y |  |  | executor 쪽 작업(operation) id |
| 20 | `step_id` | executor 단계 ID | varchar(36) | Y |  |  | executor 쪽 단계(step) id |
| 21 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 22 | `file_deleted_at` | 파일 삭제 시각 | timestamptz | Y |  |  | 파일을 지운 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_code_sources_session_id | session_id | 대화별 코드 조회 |
| ix_code_sources_run_id | run_id | run별 코드 조회 |
| ix_code_sources_execution_id | execution_id | 실행별 코드 조회 |
| ix_code_sources_created_at | created_at | 보존 정리 |

### 3.11 images (이미지)

| 항목 | 내용 |
| --- | --- |
| 영역 | 대화 |
| 기본키 | id |
| 설명 | 사용자가 메시지에 붙인 이미지의 메타 정보입니다. 파일 자체는 공유 저장소(STORAGE_ROOT) 아래 path에 있습니다. |
| 행 증가 | 첨부 이미지 수 |
| 자동 정리 | 세션 삭제 7일 뒤 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 이미지 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `user_id` | 사용자 ID | varchar(36) | N |  |  | 이미지를 보낸 사용자 (users.id 값, FK 제약 없음) |
| 3 | `project_id` | 프로젝트 ID | varchar(36) | N |  |  | 이미지가 속한 프로젝트 (projects.id 값, FK 제약 없음) |
| 4 | `session_id` | 세션 ID | varchar(36) | N |  |  | 이미지를 보낸 대화 (sessions.id 값, FK 제약 없음) |
| 5 | `run_id` | 실행 ID | varchar(36) | Y |  |  | 이미지를 처음 쓴 run |
| 6 | `name` | 파일 이름 | varchar(255) | Y |  |  | 파일 이름 |
| 7 | `mime_type` | 형식 | varchar(32) | N |  |  | 형식 |
| 8 | `size_bytes` | 파일 크기 | integer | N |  |  | 파일 크기(바이트) |
| 9 | `width` | 가로 크기 | integer | N |  |  | 이미지 가로 크기(픽셀) |
| 10 | `height` | 세로 크기 | integer | N |  |  | 이미지 세로 크기(픽셀) |
| 11 | `sha256` | 파일 해시 | varchar(64) | N |  |  | 파일 해시 |
| 12 | `path` | 저장 경로 | varchar(1024) | N |  |  | STORAGE_ROOT 아래 경로 |
| 13 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_images_session_id | session_id | 세션의 이미지 |

### 3.12 memory_history (메모리 변경 이력)

| 항목 | 내용 |
| --- | --- |
| 영역 | 프로젝트 메모리 |
| 기본키 | id (bigint) |
| 설명 | 메모리가 바뀔 때마다 바뀌기 전과 후를 남깁니다. actor_type으로 사용자가 고쳤는지 Agent가 고쳤는지 구분합니다. 화면에서 이전 상태로 되돌릴 때 씁니다. |
| 행 증가 | 메모리 변경 수 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 이력 번호 | bigint | N | PK | 자동 증가 | 기본키 |
| 2 | `project_id` | 프로젝트 ID | varchar(36) | N |  |  | 메모리가 속한 프로젝트 (projects.id 값, FK 제약 없음) |
| 3 | `item_id` | 메모리 주제 ID | varchar(64) | N |  |  | 메모리 주제 id |
| 4 | `action` | 변경 종류 | varchar(16) | N |  |  | create, update, delete |
| 5 | `before` | 변경 전 내용 | jsonb | Y |  |  | 변경 전 주제 내용. 새로 만든 경우 비어 있음 |
| 6 | `after` | 변경 후 내용 | jsonb | Y |  |  | 변경 후 주제 내용. 지운 경우 비어 있음 |
| 7 | `actor_type` | 변경 주체 종류 | varchar(16) | N |  |  | user, agent |
| 8 | `actor_id` | 변경 주체 ID | varchar(64) | N |  |  | 바꾼 주체. 사용자면 users.id, Agent면 run id |
| 9 | `session_id` | 세션 ID | varchar(36) | Y |  |  | Agent가 바꾼 경우 그 대화. 사용자가 바꾸면 비어 있음 |
| 10 | `run_id` | 실행 ID | varchar(36) | Y |  |  | Agent가 바꾼 경우 그 run. 사용자가 바꾸면 비어 있음 |
| 11 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_memory_history_project_id | project_id | 프로젝트의 메모리 이력 |

### 3.13 memory_extraction_state (메모리 정리 상태)

| 항목 | 내용 |
| --- | --- |
| 영역 | 프로젝트 메모리 |
| 기본키 | project_id |
| 설명 | 프로젝트마다 한 줄입니다. 대화가 끝나면 dirty가 켜지고 pending_turns가 올라갑니다. 대화가 잠잠해지면 worker가 lease를 잡고, processed_until_* 위치 다음의 메시지를 읽어 기억할 내용을 정리합니다. |
| 행 증가 | 프로젝트당 1행 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `project_id` | 프로젝트 ID | varchar(36) | N | PK |  | 기본키 |
| 2 | `processed_until_at` | 처리 완료 메시지 시각 | timestamptz | Y |  |  | 처리한 마지막 메시지의 시각 |
| 3 | `processed_until_id` | 처리 완료 메시지 ID | varchar(36) | N |  | 빈 문자열 | 처리한 마지막 메시지 id |
| 4 | `dirty` | 처리 대기 여부 | boolean | N |  | false | 처리할 대화가 있음 |
| 5 | `last_activity_at` | 마지막 대화 시각 | timestamptz | N |  | (앱) | 마지막 대화 시각 |
| 6 | `pending_turns` | 미처리 턴 수 | integer | N |  | 0 | 아직 처리하지 않은 턴 수 |
| 7 | `lease_owner` | 처리 인스턴스 | varchar(128) | Y |  |  | 처리 중인 인스턴스 |
| 8 | `lease_expires_at` | 처리 권한 만료 시각 | timestamptz | Y |  |  | 처리 권한 만료 시각. 재시도 대기 시각으로도 사용 |
| 9 | `attempts` | 시도 횟수 | integer | N |  | 0 | 시도 횟수 |
| 10 | `last_error` | 마지막 오류 | text | Y |  |  | 마지막 오류 |
| 11 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_memory_extraction_claim | last_activity_at, 조건 dirty | 정리할 프로젝트 고르기 |

### 3.14 workflows (워크플로우)

| 항목 | 내용 |
| --- | --- |
| 영역 | 워크플로우 |
| 기본키 | id |
| 설명 | 저장된 분석 절차입니다. document가 Workflow 1.0 형식의 본문이고, user_queries는 이 워크플로우를 찾을 때 쓸 질문 예시입니다. lifecycle은 개인이 저장한 candidate와 관리자가 승격한 template 두 가지입니다. 내용을 고치면 revision이 올라갑니다. index_state는 검색 색인 상태(not_indexed, ready, failed)입니다. |
| 행 증가 | 적음 |
| 자동 정리 | 없음 (논리 삭제) |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 워크플로우 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `name` | 워크플로우 이름 | varchar(200) | N |  |  | 이름 |
| 3 | `user_request` | 원래 요청 | text | N |  |  | 원래 사용자 요청 |
| 4 | `document` | 워크플로우 문서 | jsonb | N |  |  | Workflow 1.0 문서 |
| 5 | `user_queries` | 질문 예시 | jsonb | N |  | (앱) [] | 검색용 질문 예시 |
| 6 | `tags` | 태그 | jsonb | N |  | (앱) [] | 태그 |
| 7 | `lifecycle` | 단계 | varchar(16) | N |  | (앱) candidate | candidate, template |
| 8 | `author_id` | 작성자 ID | varchar(36) | N | FK |  | FK → users.id |
| 9 | `source_run_id` | 출처 실행 ID | varchar(36) | Y |  |  | 이 워크플로우가 나온 run |
| 10 | `source_workflow_id` | 원본 워크플로우 ID | varchar(36) | Y |  |  | 복사해 온 원본 |
| 11 | `revision` | 수정 번호 | integer | N |  | (앱) 1 | 수정할 때마다 1씩 늘어나는 번호 |
| 12 | `index_state` | 색인 상태 | varchar(16) | N |  | (앱) not_indexed | not_indexed, ready, failed |
| 13 | `deleted_at` | 삭제 시각 | timestamptz | Y |  |  | 논리 삭제 시각 |
| 14 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 15 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_workflows_author_id | author_id | 내 워크플로우 목록 |

### 3.15 workflow_query_vectors (워크플로우 검색 벡터)

| 항목 | 내용 |
| --- | --- |
| 영역 | 워크플로우 |
| 기본키 | id (bigint) |
| 설명 | user_queries의 질문마다 임베딩 한 줄입니다. 워크플로우를 고치면 이전 벡터의 active를 끄고 새 revision의 벡터를 만듭니다. 삭제되지 않은 template의 벡터만 active이고, 검색은 active인 행만 봅니다. model에는 모델이름:차원 형태의 값이 들어가 임베딩 모델이 바뀐 것을 구분합니다. |
| 행 증가 | 워크플로우 수정 횟수 × 질문 수 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 벡터 번호 | bigint | N | PK | 자동 증가 | 기본키 |
| 2 | `workflow_id` | 워크플로우 ID | varchar(36) | N | FK |  | FK → workflows.id |
| 3 | `revision` | 수정 번호 | integer | N |  |  | 어느 수정 번호의 워크플로우에서 만든 벡터인지 |
| 4 | `query` | 질문 문장 | text | N |  |  | 질문 문장 |
| 5 | `model` | 임베딩 모델 | varchar(200) | N |  |  | 임베딩모델:차원 |
| 6 | `embedding` | 임베딩 | vector | N |  |  | 임베딩. 컬럼에 차원을 고정하지 않음 |
| 7 | `active` | 검색 대상 여부 | boolean | N |  | (앱) false | 검색 대상인지 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_workflow_query_vectors_workflow_id | workflow_id | 워크플로우의 벡터 |
| ix_wqv_hnsw_{차원} | embedding::vector(차원) 코사인 HNSW, 조건 active | 워크플로우 유사도 검색 |

### 3.16 batch_report_jobs (배치 리포트 작업)

| 항목 | 내용 |
| --- | --- |
| 영역 | 배치 리포트 |
| 기본키 | id |
| 설명 | batch의 배치 실행이 성공하면 그 결과를 분석해 리포트를 쓰는 작업입니다. 실행 한 건에 작업 하나이고 idempotency_key(batch-report:{execution_id})로 중복을 막습니다. owner_id는 배치를 만든 사용자이고 그 사용자만 리포트를 봅니다. markdown은 리포트 본문, summary는 같은 배치의 다음 실행이 비교용으로 읽는 요약입니다. |
| 행 증가 | 배치 실행 성공 1건당 1행 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 리포트 작업 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `idempotency_key` | 중복 방지 키 | varchar(200) | N | UK |  | UNIQUE. batch-report:{execution_id} |
| 3 | `owner_id` | 소유자 ID | varchar(64) | N |  |  | 배치를 만든 사용자(users.id) |
| 4 | `execution_id` | executor 실행 ID | varchar(36) | N |  |  | executor 실행 id |
| 5 | `batch_id` | 배치 ID | varchar(64) | Y |  |  | batch 배치 id |
| 6 | `batch_run_id` | 배치 실행 ID | varchar(64) | Y |  |  | batch 실행 id |
| 7 | `execution` | 실행 정보 | jsonb | N |  |  | 작업을 시작한 실행 정보 |
| 8 | `state` | 작업 상태 | varchar(16) | N |  | (앱) QUEUED | QUEUED, COLLECTING, GENERATING, MATERIALIZING, SUCCEEDED, FAILED |
| 9 | `failed_stage` | 실패 단계 | varchar(16) | Y |  |  | 실패한 단계 |
| 10 | `title` | 리포트 제목 | varchar(200) | Y |  |  | 리포트 제목 |
| 11 | `markdown` | 리포트 본문 | text | Y |  |  | 리포트 본문 |
| 12 | `summary` | 요약 | text | Y |  |  | 다음 실행이 읽는 요약 |
| 13 | `artifact_id` | Artifact ID | varchar(36) | Y |  |  | 저장된 executor Artifact |
| 14 | `error` | 실패 사유 | text | Y |  |  | 실패 사유 |
| 15 | `lease_owner` | 처리 인스턴스 | varchar(128) | Y |  |  | 처리 중인 인스턴스 |
| 16 | `lease_expires_at` | 처리 권한 만료 시각 | timestamptz | Y |  |  | 처리 권한 만료. 노트북 대기 중에는 다음 시도 시각 |
| 17 | `collecting_since` | 노트북 대기 시작 시각 | timestamptz | Y |  |  | 노트북을 기다리기 시작한 시각 |
| 18 | `finished_at` | 종료 시각 | timestamptz | Y |  |  | 끝난 시각 |
| 19 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 20 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_batch_report_jobs_owner_id | owner_id | 내 리포트 목록 |
| ix_batch_report_jobs_execution_id | execution_id | 실행별 리포트 찾기 |
| ix_batch_report_jobs_batch_id | batch_id | 배치별 리포트 목록 |
| ix_batch_report_jobs_state | state | 처리할 작업 고르기 |

### 3.17 batch_report_events (배치 리포트 이벤트)

| 항목 | 내용 |
| --- | --- |
| 영역 | 배치 리포트 |
| 기본키 | id (bigint) |
| 설명 | 리포트 작업의 진행 이벤트입니다. 채팅 이벤트와 같은 형식이라 화면이 같은 컴포넌트로 그립니다. |
| 행 증가 | 리포트 1건당 수십 행 |
| 자동 정리 | 30일 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 이벤트 번호 | bigint | N | PK | 자동 증가 | 기본키 |
| 2 | `job_id` | 작업 ID | varchar(36) | N |  |  | 리포트 작업 |
| 3 | `type` | 이벤트 종류 | varchar(40) | N |  |  | 이벤트 종류 |
| 4 | `data` | 이벤트 내용 | jsonb | N |  |  | 이벤트 내용 |
| 5 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 보존 정리 기준 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| ix_batch_report_events_job_id | job_id | 작업의 이벤트 |
| ix_batch_report_events_created_at | created_at | 보존 정리 |

### 3.18 api_clients (API 클라이언트)

| 항목 | 내용 |
| --- | --- |
| 영역 | 서비스 간 인증 |
| 기본키 | id |
| 설명 | 다른 서비스와 에이전트에 발급한 API 키입니다. 키 원문은 저장하지 않고 SHA-256(key_sha256)과 앞부분(key_prefix)만 남깁니다. tenant는 이 키로 만든 실행과 배치가 속할 executor tenant입니다. kind가 standard이면 X-User-Id 사용자의 것만 조회하고, master이면 tenant 전체를 조회합니다. batches_disable_pending은 tenant의 키가 모두 폐기된 뒤 batch에서 그 tenant의 배치를 아직 끄지 못했다는 표시입니다. |
| 행 증가 | 적음 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `id` | 클라이언트 ID | varchar(36) | N | PK | (앱) UUID | 기본키 |
| 2 | `name` | 클라이언트 이름 | varchar(64) | N | UK |  | 클라이언트 이름. UNIQUE |
| 3 | `tenant` | tenant | varchar(64) | N |  |  | executor tenant |
| 4 | `key_prefix` | 키 앞부분 | varchar(32) | N |  |  | 키 앞부분(식별용) |
| 5 | `key_sha256` | 키 해시 | varchar(64) | N | UK |  | 키의 SHA-256. UNIQUE |
| 6 | `status` | 키 상태 | varchar(16) | N |  | (앱) active | active, revoked |
| 7 | `kind` | 키 종류 | varchar(16) | N |  | standard | standard, master |
| 8 | `description` | 용도 | text | Y |  |  | 용도와 담당자 |
| 9 | `created_by` | 발급자 ID | varchar(36) | N |  |  | 발급한 관리자 |
| 10 | `revoked_at` | 폐기 시각 | timestamptz | Y |  |  | 폐기 시각 |
| 11 | `last_used_at` | 마지막 사용 시각 | timestamptz | Y |  |  | 마지막 사용 시각 |
| 12 | `batches_disable_pending` | 배치 끄기 대기 | boolean | N |  | false | tenant 폐기 뒤 batch 배치 끄기 대기 |
| 13 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 14 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

없음

### 3.19 gaia_sessions (gaia 세션 대응)

| 항목 | 내용 |
| --- | --- |
| 영역 | gaia 연동 |
| 기본키 | (user_id, gaia_session_id) |
| 설명 | gaia 채팅 화면의 세션 하나가 우리 세션 하나에 대응합니다. 기본키가 (사용자, gaia 세션 id)라서 다른 사용자가 같은 gaia 세션 id를 보내도 남의 세션에 닿지 않습니다. |
| 행 증가 | gaia 대화 수 |
| 자동 정리 | 없음 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `user_id` | 사용자 ID | varchar(36) | N | PK,FK |  | PK, FK → users.id |
| 2 | `gaia_session_id` | gaia 세션 ID | varchar(200) | N | PK |  | PK. gaia가 준 세션 id |
| 3 | `session_id` | 우리 세션 ID | varchar(36) | N | FK |  | FK → sessions.id |
| 4 | `created_at` | 생성 시각 | timestamptz | N |  | (앱) | 행을 만든 시각 |
| 5 | `updated_at` | 수정 시각 | timestamptz | N |  | (앱) | 행을 마지막으로 바꾼 시각 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

없음

### 3.20 alembic_version (마이그레이션 버전)

| 항목 | 내용 |
| --- | --- |
| 영역 | 마이그레이션 |
| 기본키 | version_num |
| 설명 | 지금 적용된 마이그레이션 번호 하나를 담습니다. 인스턴스가 기동할 때 이 값을 보고 남은 마이그레이션을 실행합니다. |
| 행 증가 | 1행 |
| 자동 정리 | Alembic 관리 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `version_num` | 마이그레이션 번호 | varchar(32) | N | PK |  | 적용된 마이그레이션 번호 (예: 0008) |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

없음

### 3.21 checkpoint_migrations (체크포인트 스키마 버전)

| 항목 | 내용 |
| --- | --- |
| 영역 | LangGraph 체크포인트 |
| 기본키 | v |
| 설명 | LangGraph 체크포인트 테이블의 스키마 버전 기록입니다. 기동 때 checkpointer.setup()이 남은 단계를 적용합니다. |
| 행 증가 | 적용한 마이그레이션 수 |
| 자동 정리 | LangGraph 관리 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `v` | 버전 번호 | integer | N | PK |  | 적용한 LangGraph 체크포인트 마이그레이션 번호 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

없음

### 3.22 checkpoints (대화 상태 체크포인트)

| 항목 | 내용 |
| --- | --- |
| 영역 | LangGraph 체크포인트 |
| 기본키 | (thread_id, checkpoint_ns, checkpoint_id) |
| 설명 | Agent 그래프의 단계별 상태입니다. thread_id가 우리 sessions.id이고, run이 멈췄다 이어 갈 때 가장 최근 체크포인트를 읽습니다. |
| 행 증가 | 턴의 그래프 단계마다 |
| 자동 정리 | 쉬는 세션은 최신 1개만 남김 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `thread_id` | 스레드 ID | text | N | PK |  | 대화 스레드. 우리 sessions.id 값 (FK 제약 없음) |
| 2 | `checkpoint_ns` | 체크포인트 이름공간 | text | N | PK | '' | 하위 그래프 구분. 최상위 그래프는 빈 문자열 |
| 3 | `checkpoint_id` | 체크포인트 ID | text | N | PK |  | 체크포인트 id. 시간 순서로 정렬되는 값 |
| 4 | `parent_checkpoint_id` | 이전 체크포인트 ID | text | Y |  |  | 바로 앞 체크포인트 id |
| 5 | `type` | 직렬화 형식 | text | Y |  |  | 직렬화 형식 (현재 쓰지 않음) |
| 6 | `checkpoint` | 그래프 상태 | jsonb | N |  |  | 그래프 상태. 채널별 버전과 값이 작은 채널의 값 |
| 7 | `metadata` | 메타데이터 | jsonb | N |  | '{}' | 단계 정보 (source, step, writes 등) |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| checkpoints_thread_id_idx | thread_id | 세션별 체크포인트 조회 |

### 3.23 checkpoint_blobs (체크포인트 채널 값)

| 항목 | 내용 |
| --- | --- |
| 영역 | LangGraph 체크포인트 |
| 기본키 | (thread_id, checkpoint_ns, channel, version) |
| 설명 | 큰 채널 값(메시지 이력 등)을 체크포인트와 따로 저장합니다. 같은 버전은 한 번만 저장하고 여러 체크포인트가 함께 참조합니다. |
| 행 증가 | 채널 값이 바뀔 때마다 |
| 자동 정리 | 쉬는 세션은 최신 체크포인트가 쓰는 것만 남김 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `thread_id` | 스레드 ID | text | N | PK |  | 대화 스레드. 우리 sessions.id 값 |
| 2 | `checkpoint_ns` | 체크포인트 이름공간 | text | N | PK | '' | 하위 그래프 구분 |
| 3 | `channel` | 채널 | text | N | PK |  | 채널 이름 (messages 등) |
| 4 | `version` | 채널 버전 | text | N | PK |  | 채널 값의 버전 |
| 5 | `type` | 직렬화 형식 | text | N |  |  | 직렬화 형식 (msgpack 등). 값이 없으면 empty |
| 6 | `blob` | 채널 값 | bytea | Y |  |  | 직렬화한 채널 값 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| checkpoint_blobs_thread_id_idx | thread_id | 세션별 채널 값 조회 |

### 3.24 checkpoint_writes (체크포인트 대기 쓰기)

| 항목 | 내용 |
| --- | --- |
| 영역 | LangGraph 체크포인트 |
| 기본키 | (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) |
| 설명 | 한 단계 안에서 노드가 낸 값 중 아직 다음 체크포인트에 합쳐지지 않은 것입니다. 단계 중간에 멈춰도 끝난 노드를 다시 돌리지 않게 해 줍니다. |
| 행 증가 | 단계 안의 노드 실행마다 |
| 자동 정리 | 쉬는 세션은 최신 체크포인트 것만 남김 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `thread_id` | 스레드 ID | text | N | PK |  | 대화 스레드. 우리 sessions.id 값 |
| 2 | `checkpoint_ns` | 체크포인트 이름공간 | text | N | PK | '' | 하위 그래프 구분 |
| 3 | `checkpoint_id` | 체크포인트 ID | text | N | PK |  | 이 쓰기가 속한 체크포인트 |
| 4 | `task_id` | task ID | text | N | PK |  | 값을 낸 노드 실행(task) id |
| 5 | `idx` | 순번 | integer | N | PK |  | task 안에서의 순번 |
| 6 | `channel` | 채널 | text | N |  |  | 값을 쓸 채널 |
| 7 | `type` | 직렬화 형식 | text | Y |  |  | 직렬화 형식 |
| 8 | `blob` | 값 | bytea | N |  |  | 직렬화한 값 |
| 9 | `task_path` | task 경로 | text | N |  | '' | task의 그래프 안 경로. 정렬에 사용 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| checkpoint_writes_thread_id_idx | thread_id | 세션별 대기 쓰기 조회 |

### 3.25 store_migrations (store 스키마 버전)

| 항목 | 내용 |
| --- | --- |
| 영역 | LangGraph store |
| 기본키 | v |
| 설명 | LangGraph store 테이블의 스키마 버전 기록입니다. 기동 때 store.setup()이 남은 단계를 적용합니다. |
| 행 증가 | 적용한 마이그레이션 수 |
| 자동 정리 | LangGraph 관리 |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `v` | 버전 번호 | integer | N | PK |  | 적용한 LangGraph store 마이그레이션 번호 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

없음

### 3.26 store (LangGraph store)

| 항목 | 내용 |
| --- | --- |
| 영역 | LangGraph store |
| 기본키 | (prefix, key) |
| 설명 | 이름공간(prefix)별 키-값 저장소입니다. 이 서비스는 세 가지 이름공간을 씁니다. project_memory.{project_id}는 프로젝트 메모리 주제 본문, tool_effects.{run_id}는 도구가 executor에 한 번만 요청하도록 남긴 결과, batch_memory.{batch_id}는 배치 리포트가 다음 실행에 넘기는 요약입니다. 벡터 색인은 쓰지 않으므로 store_vectors 테이블은 없습니다. |
| 행 증가 | 메모리 주제 수 + 도구 실행 수 + 배치 실행 수 |
| 자동 정리 | 없음 (TTL 쓰지 않음) |

| No | 컬럼명 | 한글명 | 데이터 타입 | NULL | 키 | 기본값 | 설명 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `prefix` | 이름공간 | text | N | PK |  | 이름공간을 점(.)으로 이은 값. 예: project_memory.{project_id} |
| 2 | `key` | 키 | text | N | PK |  | 이름공간 안의 키. 예: 메모리 주제 id, {tool_call_id}:{도구 이름} |
| 3 | `value` | 값 | jsonb | N |  |  | 저장한 값 |
| 4 | `created_at` | 생성 시각 | timestamptz | Y |  | CURRENT_TIMESTAMP | 행을 만든 시각 |
| 5 | `updated_at` | 수정 시각 | timestamptz | Y |  | CURRENT_TIMESTAMP | 행을 마지막으로 바꾼 시각 |
| 6 | `expires_at` | 만료 시각 | timestamptz | Y |  |  | 만료 시각. 이 서비스는 TTL을 쓰지 않아 비어 있음 |
| 7 | `ttl_minutes` | TTL(분) | integer | Y |  |  | TTL(분). 이 서비스는 쓰지 않음 |

인덱스 (기본키와 UNIQUE 제약이 만드는 인덱스는 위 표의 PK, UK 컬럼):

| 인덱스 | 컬럼 | 받치는 조회 |
| --- | --- | --- |
| store_prefix_idx | prefix text_pattern_ops | 이름공간 앞부분으로 찾기 |
| idx_store_expires_at | expires_at (expires_at IS NOT NULL) | TTL 정리 (이 서비스는 쓰지 않음) |


# pr-agentic-service 설계 v1

상태: 인터뷰 완료, 1차 구현 완료(2026-10-13). 구현 기준 문서.

## 1. 확정 사항

| 항목 | 결정 |
| --- | --- |
| 배포 | 1레포 1서비스, 단일 컨테이너, CPU HPA. min/max replica 직접 설정 |
| 저장소 | PostgreSQL 1개 DB(앱 테이블 + LangGraph checkpointer + Store), Redis |
| 프론트 | 별도 레포. 이 레포는 OpenAPI + 연동 가이드 + 테스트용 HTML 제공 |
| 인증 | prj_re `standalone/sso` 구조를 분석해 `src/app/auth`에 네이티브로 구현 (별도 패키지 설치 없음). 사내 SDK는 adapter 한 곳에서 연결, 로컬은 고정 사용자 dev adapter |
| 사용자 생성 | 최초 SSO 시 User + 기본 Project 생성. Session은 첫 메시지 전송 시 생성 |
| 세션 동시성 | 세션당 run 1개. 답변 생성이든 코드 실행 대기든 끝날 때까지 새 메시지 거부(409). 다른 작업은 새 세션에서 |
| execution | execution 1개 = 커널 1개 = 노트북 1개. 종료 시 커널도 종료 |
| executor 입력 | PATH 타입 우선, 공유 RWX PVC 마운트 |
| executor 인증 | 헤더 없음. idempotency key는 body (MCP와 통일, 문제 없음) |
| 데이터 | S3. `load_data`가 S3 존재 확인과 데이터레이크 적재까지 처리 (수시간~수일 가능) |
| LLM | 사내 게이트웨이, vLLM, OpenAI 호환, tool calling 활성 |
| skill/tool 경로 | 환경변수로 지정. 기본값은 레포 내 고정 경로 (`assets/skills`, `assets/tools`, `assets/knowledge`) |
| HITL | 코드 실행 전 승인 필수. 파라미터 부족·추가 정보 필요 시 수시로 질문 |
| 실패 대응 | 승인된 계획은 끝까지 실행. 중간 실패 시 Agent가 파라미터 수정·보완 코드로 유동 대응 |
| 결과 | SSE로 진행 상황 + 최종 답변. 리포트는 executor Artifact POST. `.md`/`.ipynb` 랜딩 페이지 |
| 메모리 | LangGraph Store. Agent 자동 갱신 + 채팅 알림 + 수동 CRUD API |

## 2. 런타임 구조

```text
[Pod N개, 동일 이미지, uvicorn worker 1개]
 ├─ FastAPI (REST + SSE)
 ├─ RunScheduler          PG 큐에서 run을 lease로 가져와 그래프 실행 (Pod당 동시 실행 상한)
 └─ ExecutorEventConsumer Redis consumer group으로 executor.events 수신 → 해당 run 재개
```

- 실행 엔진 하나, lease 하나. run = PG 레코드 1개.
- 승인·질문·executor 대기는 LangGraph `interrupt`로 끝내고 슬롯을 반납한다. 세션은 잠긴 상태로 남지만 Pod는 점유하지 않는다. 수일짜리 적재도 Pod 수명과 무관하다.
- Pod가 죽으면 lease 만료 후 다른 Pod가 체크포인트에서 재개한다. executor 호출의 idempotency key를 결정적으로 만들어 재실행 시 같은 receipt를 받는다.
- SSE 이벤트는 PG 기록 + Redis Stream 전파, `Last-Event-ID`로 재연결.
- Pod당 동시 실행 상한으로 CPU 비례하지 않는 부하를 제한. minReplicas 2 이상. grace는 기본값이어도 재개가 보장된다.

## 3. Agent 구성

고정 단계 그래프가 아니라, 메인 Agent가 대화를 이끌고 필요할 때 전문 서브에이전트에게 위임하는 구조다. 어떤 순서로 무엇을 할지는 모델이 판단한다. 코드 실행 승인만 도구 안에서 강제한다.

| Agent | 역할 | 볼 수 있는 skill | 도구 |
| --- | --- | --- | --- |
| main | 대화, 일반·도메인 Q&A, 위임 판단, 메모리 갱신 | `knowledge/*` | `read_skill`, `ask_user`, `delegate_analysis`, `update_project_memory` |
| analyst | 실행 계획, 승인 요청, 실행, 실패 복구 | `skills/*` (분석 skill) + tool 카탈로그 | `read_skill`, `search_tools`, `read_tool`, `ask_user`, `run_plan`, `read_step_result` |
| reporter | 실행 코드·결과 종합, 특이사항, 추가 분석 제안 | 리포트 작성 skill | `read_step_result`, `publish_report` |

- **skill 범위는 Agent별로 고정한다.** 각 Agent 프롬프트 `prompts/<agent>.md`의 frontmatter에 허용 skill 디렉터리를 선언한다. 프롬프트에는 이름·설명 목록만 넣고 본문은 `read_skill`로 필요할 때만 읽는다. analyst는 Q&A용 지식 skill을 보지 못하고, main은 tool 카탈로그를 보지 못한다. 도메인 지식이 분석에 필요하면 main이 위임할 때 필요한 내용만 요약해 넘긴다.
- 프롬프트는 전부 `.md`로 관리한다. 코드 수정 없이 동작을 바꿀 수 있다.
- 코드 조립은 결정적이다. tool 파일 AST 파싱 → docstring 제거 → 함수 정의 + 호출 코드 + 결과 관측 출력 → `.py`로 PVC 저장 → PATH Step. tool 호출 1개 = Step 1개.
- 상태는 작게 유지한다(메시지, 현재 execution 바인딩, 계획 요약). 소스는 sha256 참조로만 남긴다.

### 코드 생성 레벨

| 레벨 | 이름 | Agent가 할 수 있는 것 |
| --- | --- | --- |
| 1 | tools_only | 등록된 tool 선택과 인자 결정만 |
| 2 | tools_with_glue | 1 + tool 사이 짧은 연결 코드(컬럼 선택, 형변환, 필터 등) |
| 3 | tools_first | 2 + 맞는 tool이 없거나 실패를 메울 때 새 함수 작성 |
| 4 | free_code | tool은 참고만, 전체 코드를 Agent가 직접 작성 |

- Agent가 작성한 코드는 레벨과 무관하게 승인 화면에 전문을 보여준다.
- 레벨은 세션 설정이며 Project 기본값을 상속한다. 시스템 기본값은 3.
- 실패 복구도 레벨을 따른다 (레벨 1이면 인자 수정과 다른 tool 선택만 가능).

## 4. executor 사용안 (구현 반영)

| 상황 | 사용 방식 |
| --- | --- |
| 분석 시작 | 세션의 커널이 없으면 MULTI execution 생성. 승인된 계획의 실행 구간 1개 = Operation 1개 (tool 호출 1개 = Step 1개) |
| 조건부 tool | 조건부 호출 앞에서 Operation을 끊고, 앞 결과를 본 Agent의 판단(decisions)으로 다음 Operation을 append |
| 실패 보완 | 인자 수정(`revise_call`) 후 재실행, 또는 레벨이 허락하면 Agent 코드(`run_custom_code`, 승인 필수)를 같은 커널에 append |
| 후속 질문 | 커널이 살아 있으면 같은 execution에 append (이전 결과 변수 재사용) |
| 대기 | `operation_wait_timeout_seconds` 30분. 만료되면 다음 실행 때 새 execution을 열고 성공했던 호출부터 다시 실행 |
| 종료 | **리포트 작성 시 finalize**: executor의 리포트 Artifact 등록이 SUCCEEDED execution에서만 가능하므로, `write_report`가 finalize → 리포트 생성 → `append_to_notebook`으로 노트북에도 추가 |
| 장기 적재 | `load_data` 류 Step이 오래 걸려도 run은 `waiting_executor`로 대기(Pod 점유 없음). 세션은 그동안 잠김 |
| 재실행 안전 | executor 호출은 run·tool_call 기반 idempotency key를 쓰고, 결과를 LangGraph Store에 기록해 재개 시 다시 호출하지 않음 |

## 5. API / 프론트 연동 (초안)

- 인증: `GET /api/v1/auth/login/sso`, `GET /api/v1/auth/session`, `POST /api/v1/auth/logout` (sso 패키지 제공)
- `GET /api/v1/users/me`, Project·Session·Message CRUD, Project memory CRUD
- `POST /api/v1/sessions/{id}/messages` → run 생성 (202, 세션이 바쁘면 409)
- `POST /api/v1/runs/{id}/resume` → HITL 응답 (승인, 수정, 답변)
- `POST /api/v1/runs/{id}/cancel`
- `GET /api/v1/sessions/{id}/events` → SSE (`run_status`, `token`, `thinking`, `tool_call`, `hitl_request`, `execution_progress`, `artifact`, `message_final`, `memory_updated`, `error`)
- `GET /api/v1/artifacts/{id}/content` → executor 아티팩트 프록시, `GET /view/artifacts/{id}` → `.md`/`.ipynb` 랜딩 페이지
- 전달물: OpenAPI + `docs/api-guide.md` (SSE 이벤트 카탈로그, HITL payload 예시)
- 테스트 HTML: `/dev` 정적 페이지 (운영 비활성)

## 6. prj_re에서 가져올 것 / 버릴 것

- 가져옴: `standalone/sso`의 흐름(로그인 flow, Redis 세션, CSRF)을 네이티브로 이식, skill `.md` 형식(frontmatter + Tool list 표), tool 파일 규약(파일명 = 함수명, 함수 내부 import), AST 기반 docstring 제거, 게이트웨이 대응(`tools=[]` 제거, thinking 옵션), PATH 소스 content-addressed 저장
- 버림: 고정 단계 상태머신, 다중 worker·lease, DB 분리, 77필드 flat state, 승인 스냅샷에 전체 소스 저장

## 7. 레포 구조 (구현)

```text
src/
  main.py        RUN_MODE=all | api | worker
  api_service/   라우터, SSO, 스키마 (agent를 import하지 않음)
  agent/         그래프, persona middleware, 도구, 코드 조립, 리포트, prompts/*.md
  worker/        run 스케줄러, executor 이벤트 consumer, 배치 리포트 작업
  core/          설정, 모델, 이벤트 버스, executor 클라이언트, 메모리·Workflow 서비스, 카탈로그
assets/          skills/ tools/ knowledge/
migrations/  web/dev/  scripts/  tests/  deploy/kubernetes/
```

의존 방향: `api_service → core`, `worker → agent → core`. 메모리·Workflow의 저장 규칙은 API와 Agent가 함께 지켜야 하므로 core에, Agent가 그것을 쓰는 방식(도구·프롬프트 주입)은 agent에 둔다.

## 7.1 Agent 구성 (구현)

- 그래프 하나에 persona 두 개(main, analyst). `start_analysis` / `finish_analysis` 도구로 전환하고, middleware가 매 모델 호출마다 해당 persona의 프롬프트·도구만 노출한다.
- main은 `knowledge/`만, analyst는 분석 `skills/`와 tool 카탈로그만 읽는다. 상대 persona가 읽은 자료는 대화 이력에서 "(생략)"으로 가린다.
- reporter는 도구 없는 단일 LLM 호출(대화형 리포트와 pr-batch 리포트 공용).
- 프로젝트 지침과 메모리는 매 모델 호출 시 시스템 프롬프트에 넣고 메시지 이력에는 남기지 않는다.

## 8. Project memory (인터뷰 반영안)

### 8.1 확정·제안

| 항목 | 내용 |
| --- | --- |
| 저장 | LangGraph `AsyncPostgresStore` (같은 PG). namespace `("project_memory", project_id)` |
| 소유 | 지금은 Project 1인 소유. 권한은 `project_members(role)` 테이블로 판단해 다인 공유로 확장 가능. namespace에 user_id를 넣지 않음 |
| 개인 메모리 | 없음 |
| 분류 | prj_re 인터뷰 결과를 따름: `background`(프로젝트 배경), `analysis_preferences`(분석 선호), `report_preferences`(보고서 선호), `shared_findings`(공유할 주요 발견) |
| 단위 | 항목(item) 단위. 항목 = 분류 + 제목 + 본문(≤ 1,000자) + version + author(user/agent) + 출처 세션 |
| 읽기 | run 시작 시 항목 목록(분류·제목)은 항상 주입, 본문은 현재 요청과 관련도 높은 상위 항목만 주입. 더 필요하면 `search_memory` 도구 |
| 쓰기 | 별도 후처리 단계 없이, 대화 중 필요할 때 main Agent가 `save_memory` 도구로 갱신. 갱신 시 채팅에 `memory_updated` 이벤트 |
| 동시 수정 | 항목별 version CAS. 충돌 시 최신본을 다시 읽어 병합 |
| 사용자 작성 항목 | Agent가 직접 수정 불가 (8.3 참고) |
| 이력 | 항목별 변경 이력(이전 본문, 변경자, 출처 세션·run, 시각) 보관 |
| 총량 | 프로젝트당 본문 합계 30,000자 (약 100개 항목 수준). 모델 주입 예산은 4,000 토큰 |
| 멀티턴 | 세션 = LangGraph thread. 대화 이력은 checkpointer 메시지로 항상 이어짐. 메모리는 메시지에 누적하지 않고 매 run 시작 시 최신본을 주입(오래된 메모리가 이력에 남아 혼동하는 것 방지). 이력이 길어지면 요약 middleware로 압축 |

### 8.2 임베딩 사용 방식

- 항목 저장 시 `제목 + 본문`을 게이트웨이 임베딩 모델로 벡터화해 Store 인덱스(pgvector)에 넣는다. LangGraph Store의 `index={"embed": ..., "dims": ..., "fields": ["title", "content"]}` 설정만으로 동작한다.
- **읽기**: run 시작 시 사용자 메시지로 `store.asearch(namespace, query=메시지, limit=k)` → 관련 항목 본문만 주입. 메모리가 커져도 프롬프트 크기가 일정하다.
- **쓰기 중복 방지**: `save_memory` 호출 시 유사도가 높은 기존 항목이 있으면 새 항목을 만들지 않고 그 항목 갱신으로 유도한다 ("보고서는 짧게"가 여러 개 쌓이는 문제 방지).
- 총량이 작아 전부 넣어도 되는 동안에는 검색 효과가 크지 않다. 그래서 핵심 가치는 "중복 방지"와 "커졌을 때 선택"이다.
- 전제: PostgreSQL에 `pgvector` 확장 설치 가능해야 함. 불가하면 키워드 검색으로 대체.

### 8.3 "사용자 작성 항목은 Agent가 수정 제안만" 의 의미

사용자가 API/화면에서 직접 쓴 항목은 `author=user`로 잠근다. Agent가 대화 중 그 항목이 현재 요청과 충돌하거나 낡았다고 판단하면:

1. 직접 고치지 않고 `ask_user` HITL로 "프로젝트 메모리의 '보고서 선호: 결론 먼저' 항목을 '표 위주로'로 바꿀까요?"를 묻는다.
2. 사용자가 승인하면 그때 수정하고, 항목은 계속 `author=user` 잠금 상태를 유지한다. 거절하면 이번 세션 요청으로만 반영한다.

Agent가 만든 항목(`author=agent`)은 승인 없이 수정·삭제할 수 있다.

### 8.4 shared_findings 자동 식별

- 사용자가 "기억해줘"라고 하면 즉시 저장한다.
- 명시하지 않아도 main Agent가 다음 조건을 모두 만족하는 결론을 식별해 저장한다.
  1. 성공한 executor 실행 결과에 근거한다 (추측·일반론 제외).
  2. 이번 세션을 넘어 프로젝트에 계속 유효한 사실이다 (예: "A라인 불량의 주 요인은 챔버 온도"). 일회성 수치 나열은 제외.
  3. 사용자가 반박하지 않았다.
- 저장 항목에는 근거 출처(세션, run, 리포트 artifact 링크)를 남긴다. 상세 수치는 리포트에 두고 메모리에는 결론 문장만 둔다.
- 저장되면 채팅에 `memory_updated` 알림이 뜨고, 사용자는 화면에서 바로 삭제할 수 있다.
- 판단 기준은 `prompts/main.md`에 있어 운영 중 조정 가능하다.

### 8.5 임베딩 설정

- 모델과 차원은 설정값(`EMBEDDING_MODEL`, `EMBEDDING_DIMS`)이며 지금 확정할 필요 없다. 기동 시 Store 인덱스가 설정 차원으로 생성된다.
- 참고: Qwen3-Embedding 0.6B = 1024, 4B = 2560, 8B = 4096차원. pgvector HNSW 인덱스는 `vector` 타입 2,000차원까지라 4B/8B는 출력 차원을 1024 등으로 줄여 쓰는 것을 권장한다 (Qwen3-Embedding은 차원 축소 지원).
- 배포 후 모델이나 차원을 바꾸면 재색인이 필요하다. `scripts/reindex_memory.py`를 함께 제공한다.
- 로컬 개발은 게이트웨이 없이 동작하도록 임베딩 비활성 시 키워드 검색으로 대체한다.

## 9. Workflow

표준: **Workflow 1.0** (`docs/specs/workflow-1.0/`, 사용자 제공). prj_re의 2.0은 참고만 하고 따르지 않는다.

### 9.1 규격 요약과 해석

- 구조: `actor`, `name`, `user_request`, `execution_mode(static|adaptive)`, `allow_immediate_execution`, `steps[]{skill, tools[]{tool, execution(always|conditional), arguments}}`.
- 인자 출처는 `literal`, `input`, `tool_output(step_index, tool_index, output)` 세 가지. `input`은 호출별 개별 입력이며 값은 워크플로우에 저장하지 않고 실행별로 관리한다.
- 조건은 워크플로우에 식으로 적지 않는다. `conditional` Tool의 실행 여부는 **해당 skill `.md`의 Tool list(실행 조건, condition_tool)** 를 보고 Agent가 판단한다.
- 코드, 실제 입력값, 실행 상태는 담지 않는다.

### 9.2 내부 실행 계획과의 관계

analyst의 실행 계획 = **Workflow 1.0 문서 + 실행 바인딩**.

| 구성 | 내용 | 저장 시 |
| --- | --- | --- |
| `workflow` | Workflow 1.0 그대로 | 그대로 저장 |
| `input_values` | `(step_index, tool_index, param)` → 값. 질문에서 추출하거나 HITL로 받음 | 저장 안 함 |
| `condition_decisions` | conditional Tool별 실행/생략 판단과 근거 | 저장 안 함 |
| `custom_steps` | 레벨 2~4에서 Agent가 작성한 코드 Step (위치, 코드, 출력 이름) | 저장 안 함 |

- `execution_mode`는 서버가 자동 산출한다 (conditional이 하나라도 있으면 adaptive).
- 검증은 2단계: JSON Schema(구조) + 의미 검증(skill/tool 등록 여부, skill-tool 소속, 실행 방식이 skill 규칙과 일치, 필수 인자, `tool_output`이 앞선 호출의 등록 출력인지, 조건부 출력 참조의 유효성).

### 9.3 실행 방식 (executor MULTI와의 매핑)

- 조건부 판단이 없는 구간은 한 Operation으로 묶어 실행한다 (Tool 호출 1개 = Step 1개).
- `conditional` Tool을 만나면 Operation 경계를 둔다. 앞 Operation 결과에서 condition_tool의 출력을 읽고 Agent가 실행 여부를 판단한 뒤 다음 Operation을 append한다. MULTI의 append 구조에 그대로 맞는다.
- 생략된 조건부 Tool의 출력을 참조하는 호출은 의미 검증 단계에서 허용 여부를 확인한다.
- 실패 시에는 레벨에 따라 인자 수정, 다른 tool, 보완 코드(`custom_steps`)로 복구한다.

### 9.4 저장 (Agent 코드가 포함된 계획)

- 저장되는 것은 등록 tool로 이루어진 부분뿐이다. `custom_steps`는 제외한다.
- 제외 후에도 남은 `tool_output` 참조가 모두 유효하면 저장하고 "Agent 작성 코드 N개는 제외됨"을 안내한다.
- 등록 tool이 Agent 코드의 출력을 참조하고 있으면 그 연결이 끊기므로 저장을 막고 이유를 보여준다.
- `actor`는 사용자가 저장하면 `USER/사번`, Agent 제안을 승인해 저장하면 `AGENT/agent 이름`.

### 9.5 등록·검색·추천

- API: candidate 등록, 조회, 수정(revision CAS), 승격(template, 작성자가 직접), 복제, 삭제, 재색인, 검색. 권한은 candidate 작성자 전용, template 전체 조회.
- 검색: 등록 시 `user_queries`(이 워크플로우가 답하는 질문 예시)를 쿼리별 임베딩 → pgvector HNSW → 워크플로우 단위로 묶어 유사도 순 반환. 기준값 기본 0.93 (설정).
- 추천: analyst의 `search_workflows` 도구(검색 풀은 template만). 강제 단계 아님. 추천 template과 새로 생성한 계획을 합쳐 `PLAN_CANDIDATES`개를 승인 화면에 제시 (9.7 참고).
- 등록 경로: (1) 사용자가 결과 화면에서 저장, (2) 분석 성공 후 Agent가 저장 제안 → 사용자 승인.

### 9.6 배치 (pr-batch 연동)

pr-batch(`/Users/a10054/SKAX_PROJECT/pr-batch`, 개발 중)는 사용자 스크립트(노트북) 업로드·버전, 배치 등록(일정·정책), 수동 실행·이력을 담당한다. 이 서비스의 역할은 두 가지다 (pr-batch `docs/architecture.md` 10장, `docs/integrations.md`).

1. **배치 진입 게이트웨이**: 프론트는 이 서비스의 `/api/v1/batch/...`를 호출하고, 이 서비스가 SSO로 확인한 사용자 ID로 pr-batch 전용 단기 JWT(HS256, `aud=pr-batch`, `scope=batch:manage`, 수명 5분 이하)를 발급해 pr-batch API(scripts, batches, runs)를 중계한다. 세션 노트북을 배치 스크립트로 등록하는 경로도 여기서 제공한다.
2. **배치 리포트 API 제공**: pr-batch가 배치 실행 후 호출하는 `/internal/v1/execution-reports` (접수, 상태, 재시도)를 이 서비스가 구현한다. pr-batch 서비스 토큰(`iss=pr-batch`, `aud=prj_re-report`)을 검증하고, reporter Agent를 대화·승인 없이 실행 결과(셀 출력, manifest)만 근거로 돌려 리포트를 executor Artifact로 저장한다.

### 9.7 확정

- `allow_immediate_execution=true` template + 질문에서 입력값이 모두 채워짐 → 승인 HITL 생략. Agent 작성 코드가 섞이면 항상 승인.
- 추천 검색 대상: 승격된 template만. candidate(저장했지만 승격 전, 작성자만 보는 워크플로우)는 검색 풀에 넣지 않는다.
- **계획 후보 수**: 한 번에 제안하는 실행 계획 수는 설정값 `PLAN_CANDIDATES`(기본 5). 검색으로 template k개가 추천되면 나머지 5-k개를 analyst가 새로 생성해 함께 보여준다. 사용자는 승인 화면에서 하나를 골라 입력값을 확인·수정하고 승인한다. 추천 template 후보에는 출처와 유사도를 표시한다.

## 10. prj_re 기능 중 포함 범위 (확정)

- 포함: Project `system_prompt`(프로젝트 지침, 모든 Agent 프롬프트 뒤에 주입), 관리자 역할(admin/user)과 사용자 관리 API, run별 LLM 선택(서버 등록 별칭만, run 중 변경 불가)
- 제외: 메시지 수정 API, Dataset Registry

# 통합테스트 시나리오 및 진행방안 설계

2026-11-01 작성 · 2026-11-04 현행화 · 원본 문서: https://claude.ai/artifact/6Cvg7McSJyRnCqwDBq8eSk (11/01 시점. 현행본은 이 파일)

## 요약

**결론: 사전 준비(PREP)를 끝내면 dev에서 예습하고 prd(오픈 전)에서 본 테스트를 합니다. 8개 영역 76개 시나리오(P0 39개)를 두 환경 모두에서 돌립니다.** 진행 현황은 상황판(엑셀, 이후 컨플루언스)으로, 시나리오별 수행 내용·결과·증빙은 시나리오마다 컨플루언스 페이지로 남깁니다.

- 기준 커밋: pr-agentic-service main `c7daac1`, internal/gaia `746c568`. executor·pr-batch·prj_re 기준 커밋은 PREP-01에서 수행 시점에 기록합니다.
- 11/04 현행화: 익스큐터 actor 제거, 통합 루트 상대경로, gaia access key 우회, 키워드 판정의 모델 판단 교체, 코드 레벨 4, 실패 재시도 상한, 실패 원인 표시를 반영했습니다. 신규 시나리오는 RUN-15~17, OPS-10, GAIA-07입니다.
- 세 서비스 모두 헤더 모드가 삭제되어 모든 환경이 키 인증입니다.
- **prd도 오픈 전이라 장애 주입, 키·tenant 폐기, 사용자 비활성화, DB 리셋까지 prd에서 그대로 합니다.**
- 가능한 한 우리 화면에서 수행합니다. 화면 칸이 X인 시나리오는 따로 모아 수행합니다(아래 "화면 수행 기준"). prd도 오픈 전 동안 화면을 켭니다(`WEB_CONSOLE_ENABLED: true`, 오픈 때 끔).

## ID 규칙

영역 약어-번호입니다. PREP 사전 준비 · AUTH 인증 · RUN 세션·run 실행 · EXEC executor 연동 · BAT 배치 · TEN tenant·사용자 · ADM 관리자 · OPS 장애·설정·부하 · GAIA gaia. 11/01판의 A1~H6은 번호가 그대로 이어집니다(A1 → AUTH-01, D3 → BAT-03).

## 테스트 대상과 연동 경로

연동 경로는 아홉 개입니다. 시나리오마다 어느 경로를 지나는지 아래 번호(I1~I9)로 표시했습니다. 모든 경로를 한 번 이상 지나야 통합테스트가 끝난 것으로 봅니다.

```
  브라우저                 key 호출자                gaia
  SSO 쿠키+X-CSRF-Token    X-Api-Key+X-User-Id      내부망, 사번 전달
        | I1                    | I2                     | I8
        v                       v                        v
  +--------------------------------------------------------------+   I9   +-----------+
  | pr-agentic-service                                           | -----> | SSO (idp) |
  | API · 에이전트 워커 · 배치 리포트 · tenant dtest-agent-service |        | prj_re    |
  +--------------------------------------------------------------+        +-----------+
        | I3 · I4                ^ I5                    | I6
        v                        |                       v
  +-----------+   이벤트   +--------------------------+   +-----------+
  | executor  | ---------> | Redis 스트림               |   | pr-batch  |
  | 실행·작업 |            | executor.events.<tenant> |   | 스크립트· |
  | 공간·이벤트|            +--------------------------+   | 배치·일정 |
  +-----------+                                         +-----------+
        ^                                                     |
        +---------- I7 배치 실행: pr-batch 키로 executor에 직접 제출 ----+

  공유 자원: PostgreSQL(서비스별 DB 3개) · Redis · 공유 PV(입력 코드·실행 결과)
```

| 경로 | 보내는 쪽 → 받는 쪽 | 인증 | 확인할 것 |
| --- | --- | --- | --- |
| I1 | 브라우저 → 우리 API | SSO 쿠키 + `X-CSRF-Token` | `users.id` = 소문자 사번, 쓰기 요청에 CSRF |
| I2 | key 호출자(Swagger·상위 에이전트) → 우리 API | `X-Api-Key` + `X-User-Id` | 우리 tenant 키는 `own_tenant`, 감사 로그 `api_client_request` |
| I3 | 우리 → executor | `EXECUTOR_API_KEY`(relay) + `X-Tenant-Id` | 실행 제출·조회·취소, 작업 공간 `tenants/{tenant}/users/{사번}` |
| I4 | 우리 → executor (시스템 화면) | `EXECUTOR_ADMIN_API_KEY`(ops) | 런타임·점검 탭, 비어 있으면 503 |
| I5 | executor → Redis → 우리 워커 | 스트림 `executor.events.dtest-agent-service` | 이벤트를 받고 executor에 다시 물어본 뒤 run 재개, 놓친 이벤트 복구 |
| I6 | 우리 → pr-batch | `BATCH_API_KEY`(relay + admin) | 스크립트·배치 게이트웨이, `disable-by-owner`, `disable-by-tenant` |
| I7 | pr-batch → executor | pr-batch의 `EXECUTOR_API_KEY` | `trigger {type: BATCH}` + `X-User-Id`(owner), 배치의 tenant로 제출 |
| I8 | gaia → 우리 (internal/gaia만) | gaia가 넘기는 사번 | gaia 세션 ↔ 우리 세션 매핑, 확인 단계 자동 응답 |
| I9 | 우리 → SSO(idp) | idp 로그인 페이지·userinfo | `SSO_ALLOWED_ORIGINS`, 사번 표기(대소문자), 관리자 최초 로그인 |

공유 자원: PostgreSQL(서비스별 DB 3개), Redis(이벤트 스트림), 공유 PV(입력 코드·실행 결과).

## 사전 준비 순서 (PREP)

순서가 중요한 것은 세 가지입니다. 관리자 사번은 관리자가 처음 로그인하기 전에 넣어야 하고, DB·Redis·PV는 세 서비스를 동시에 비워야 하고, 배포는 executor → pr-batch → 우리 순서로 해야 합니다. dev와 prd에서 같은 순서를 밟습니다.

| ID | 할 일 | 담당 | 완료 확인 |
| --- | --- | --- | --- |
| PREP-01 | 기준 커밋 고정: 네 저장소의 테스트 대상 커밋을 이 문서와 상황판에 적고, 테스트 중에는 병합한 변경만 다시 배포 | 우리 | 커밋 표 갱신 |
| PREP-02 | 환경별 키 생성: executor `scripts/generate_api_keys.py <env>`로 우리→executor, ops, pr-batch→executor 키를 만들고, 우리→pr-batch 키도 같은 방식(임의 문자열 + SHA-256)으로 만듦. 환경끼리 키 공유 금지 | 우리 + executor | 키 4개, 해시 4개 |
| PREP-03 | 해시 교환: executor `AUTH_CLIENTS`의 `pr-agentic-service`·`pr-batch`·`ops`, pr-batch `AUTH_CLIENTS`의 `pr-agentic-service`를 0000…에서 실제 해시로 교체. 키 원문은 우리 `EXECUTOR_API_KEY`·`EXECUTOR_ADMIN_API_KEY`·`BATCH_API_KEY`, pr-batch `EXECUTOR_API_KEY`에 | executor, pr-batch | 세 서비스 설정 diff |
| PREP-04 | 우리 설정 채우기: `config.{env}.yml`의 `<...>` 자리(DATABASE_URL, REDIS_URL, PUBLIC_API_ORIGIN, FRONTEND_ORIGIN, CORS_ORIGINS, LLM_API_KEY, MODELS, EXECUTOR·BATCH 주소), `SSO_ALLOWED_ORIGINS`, `ADMIN_EMPLOYEE_IDS`. Redis는 executor가 이벤트를 쓰는 같은 Redis. `EXECUTOR_RESULT_ROOT`는 통합 루트(`/mnt/data/dtest`). 임베딩을 쓰면 `EMBEDDING_PROVIDER: openai`, `EMBEDDING_SEND_DIMENSIONS: false`(bge-m3)로 두고 `scripts/check_embedding.sh`(Windows는 `.ps1`)로 확인. 추적을 쓰면 `PHOENIX_ENDPOINT`·`PHOENIX_API_KEY`·`SERVICE_ID` | 우리 | `<`가 남은 값 0개 (`grep '<' config.{env}.yml`), 임베딩 확인 통과 |
| PREP-05 | internal/gaia만: `src/dtest/idp_login.py`의 `SSO_LOGIN_PAGE`·`USERINFO_URL`·`FIELDS`, 템플릿 고정값(`PORT`, `PROJECT_NAME`, `SERVICE_NAME`), HCP·gaia 의존성 추가 후 `uv lock`, `GAIA_DEPLOYMENT` 값 | 우리 + SSO 담당 | userinfo 응답 필드명 확인 |
| PREP-06 | 세 서비스 중지 후 동시 리셋: 우리·executor·pr-batch DB, 공유 PV의 `tenants/*/users/*`와 우리 `STORAGE_ROOT` 아래, Redis의 `executor.events.*` 스트림과 컨슈머 그룹. 우리 컨테이너는 UID 1000으로 돌므로 `STORAGE_ROOT`에 UID 1000 쓰기 권한 확인 | 세 팀 + 인프라 | DB 테이블 비어 있음, 스트림 없음, 쓰기 확인 |
| PREP-07 | 배포: executor(통합 루트 상대경로 버전) → pr-batch → 우리. 마이그레이션은 기동 시 자동(우리 0007까지) | 각 팀 | 각 서비스 health 200 |
| PREP-08 | 연결 스모크(S0, 아래) | 우리 | S0 전부 통과 |
| PREP-09 | 관리자 최초 로그인 → `/users/me`에서 admin 확인 → 테스트 키 2개 발급: 우리 tenant(`own_tenant: true`)와 외부 tenant 가정 `it-ext` | 우리 | 키 원문 2개 보관 |
| PREP-10 | 테스트 데이터: 합성 nce 데이터, `scripts/seed_test_workflows.py`, 배치용 노트북 1개(성공용)과 일부러 실패하는 노트북 1개 | 우리 | 데이터 조회 가능 |

**테스트 계정:** 관리자 1명, 일반 사용자 A와 B(공유 프로젝트·권한 확인용). 비활성화 시나리오는 B로 합니다. 수행자가 여러 명이면 사람마다 일반 계정을 따로 둡니다.

**S0 연결 스모크** (시나리오 전에 5분 안에 끝내는 확인)

1. 우리 → executor: 관리자 화면 실행 목록 200 (I3), 시스템 > 런타임 탭 200 (I4)
2. 우리 → pr-batch: 배치 화면 런타임 목록 200 (`GET /api/v1/batch/runtimes`, I6)
3. pr-batch → executor: 일정 있는 배치를 하나 만들어 `enable_blocked_reason`이 `EXECUTOR_NOT_CONFIGURED`가 아닌지 (I7)
4. Redis: `XINFO GROUPS executor.events.dtest-agent-service`에 우리 그룹이 있음 (I5)

401이 나면 해당 쌍의 키·해시부터 다시 봅니다. 많이 틀리는 곳은 3번입니다.

## 시나리오

모든 시나리오를 dev(예습)와 prd(본 테스트)에서 한 번씩 돌립니다. P0는 prd 종료 전에 모두 통과해야 하고, P1은 실패해도 우회책과 담당이 있으면 넘어갑니다.

- **화면:** O 우리 화면만으로 수행 · 일부 화면 + 보조 확인 · X 화면 밖. 괄호는 화면 밖 부분에 필요한 권한(관리자, 운영, gaia 화면).
- **단독:** 서비스 중지, 리셋, 폐기·비활성화처럼 그 시간에 다른 사람의 테스트를 깨뜨리는 시나리오. 시간을 정해 혼자 수행합니다.

### A. 인증 (AUTH)

| ID | 시나리오 | 기대 결과 | 경로 | 화면 | 단독 | 우선 |
| --- | --- | --- | --- | --- | --- | --- |
| AUTH-01 | SSO 첫 로그인 | `users.id` = 소문자 사번, 기본 프로젝트 생성 | I1 I9 | O |  | P0 |
| AUTH-02 | `ADMIN_EMPLOYEE_IDS`에 있는 사번의 최초 로그인 | admin, `/users/me` `permissions.system: true` | I1 I9 | O |  | P0 |
| AUTH-03 | 브라우저 쓰기 요청에 `X-CSRF-Token` 없음 | 403 | I1 | O |  | P0 |
| AUTH-04 | 키 + `X-User-Id`로 `GET /users/me` | 200, 감사 로그에 client·tenant·user·`request_id` | I2 | O |  | P0 |
| AUTH-05 | `X-User-Id`가 우리 DB에 없는 사번 / 형식 위반 | 403 / 400 | I2 | O |  | P0 |
| AUTH-06 | 키로 관리자 API 호출 | 403 "SSO login" | I2 | O |  | P0 |
| AUTH-07 | 키 개별 폐기 | 60초 안에 모든 Pod에서 401 `INVALID_API_KEY` | I2 | O |  | P0 |
| AUTH-08 | 우리 tenant 키를 `own_tenant` 없이 발급 | 422 | I2 | O |  | P1 |
| AUTH-09 | 쿠키와 키를 함께 보냄 | 쿠키 사용자로 처리, 키·`X-User-Id` 무시 | I1 I2 | O |  | P1 |
| AUTH-10 | SSO 로그인 페이지 도메인이 `SSO_ALLOWED_ORIGINS`에 없음 | 502, 로그 `sso_login_url_rejected` | I9 | X (운영) | 단독 | P1 |
| AUTH-11 | 비관리자 사용자가 dev 역할 변경 `POST /auth/dev/role` | 비관리자 dev 역할 변경은 dev·prd에서 404 (로컬 전용) | I1 | O |  | P1 |

### B. 세션·run 실행 (RUN)

| ID | 시나리오 | 기대 결과 | 경로 | 화면 | 단독 | 우선 |
| --- | --- | --- | --- | --- | --- | --- |
| RUN-01 | 브라우저: 새 세션 + 분석 요청 → plan_approval 승인 → executor 실행 → 리포트 | run `succeeded`, `execution_completed`·`artifact` 이벤트, 답변에 attachments | I1 I3 I5 | O |  | P0 |
| RUN-02 | 같은 흐름을 키 호출자로 (Swagger 가이드 1절) | RUN-01과 같음, executor `X-User-Id` = 사번 | I2 I3 I5 | O |  | P0 |
| RUN-03 | Ingress를 거친 SSE `GET /sessions/{id}/events` | token이 묶여 오지 않고 5분 넘게 연결 유지 | I1 | O |  | P0 |
| RUN-04 | code_approval·question·workflow_save 응답 | 202 `resumed: true`, 같은 run이 이어짐 | I1 | O |  | P0 |
| RUN-05 | 실행 중 run 취소 (채팅 중지 버튼) | run `cancelled`, executor 실행도 취소(소유자 `X-User-Id`) | I1 I3 | O |  | P0 |
| RUN-06 | `waiting_executor` 중 우리 워커 재시작 | 놓친 이벤트 복구로 run이 이어짐(복구 주기 120초) | I3 I5 | 일부 (운영) | 단독 | P0 |
| RUN-07 | reject_templates (`allow_reject_templates: true`인 카드) | 새 계획의 plan_approval 재도착. false인 카드에 보내면 422 | I1 | O |  | P1 |
| RUN-08 | 자동 실행 조건 충족(후보 1개, 유사도 0.77 이상). 임베딩을 켠 환경(`EMBEDDING_PROVIDER: openai`, `EMBEDDING_SEND_DIMENSIONS: false`)에서만 | `plan_auto_approved` 이벤트, 새로고침 후에도 남음 | I1 | O |  | P1 |
| RUN-09 | 진행 중 세션에 새 턴 | 409 `SESSION_BUSY` | I1 | O |  | P1 |
| RUN-10 | 오래된 `interrupt_id`로 재개 | 409 `STALE_INTERRUPT` | I1 | O |  | P1 |
| RUN-11 | 필수 입력을 비우고 승인 | 계획 카드에 빈 필수 입력 수가 표시되고 승인 버튼은 막히지 않음. 승인하면 422 `INVALID_ANSWER`, `details[].location`이 그 칸 | I1 | O |  | P1 |
| RUN-12 | 공유 프로젝트에서 B가 A의 세션을 이어 실행 | 이어지는 executor 호출의 `X-User-Id`는 A(실행 소유자) | I1 I3 | O |  | P1 |
| RUN-13 | 실행 중 세션 삭제 | 진행 중 executor 실행 취소 | I1 I3 | O |  | P1 |
| RUN-14 | 분석 시나리오 묶음 `scripts/run_scenarios.py` | 점수표 JSON, 이전 기준선 이상 | I1 I3 | X (운영) |  | P1 |
| RUN-15 | 코드 레벨 4로 분석 요청 (세션 또는 프로젝트 설정) | 계획 승인 카드 없이 바로 `run_custom_code` 실행. 레벨 3에서는 기존처럼 plan_approval | I1 I3 I5 | O |  | P1 |
| RUN-16 | 임베딩 없는 환경(`EMBEDDING_PROVIDER: none`)에서 템플릿이 있는 요청 | 채팅 모델이 고른 후보가 나오고 similarity는 null, 자동 실행 없이 항상 승인 카드 | I1 | O |  | P1 |
| RUN-17 | 일회성 지시와 지속 선호를 섞어 대화 | 지속 선호만 프로젝트 공유 메모리에 남고 일회성 지시는 남지 않음 | I1 | O |  | P1 |

### C. executor 연동·게이트웨이 (EXEC)

| ID | 시나리오 | 기대 결과 | 경로 | 화면 | 단독 | 우선 |
| --- | --- | --- | --- | --- | --- | --- |
| EXEC-01 | 우리 tenant 키 + `X-User-Id`로 `GET /executor/executions` | 본인 실행만 | I2 I3 | O |  | P0 |
| EXEC-02 | INLINE `print(1+1)` 제출(curl) | result에 `2`. 작업 공간은 PV `tenants/dtest-agent-service/users/<사번>/…`, 결과 경로는 통합 루트 기준 `executor/executions/<id>/…`이고 세션 화면 이미지·단계 결과가 열림 | I2 I3 | O |  | P0 |
| EXEC-03 | 외부 tenant(`it-ext`) 키로 실행 제출 | `tenants/it-ext/…`에 생성, 이벤트는 `executor.events.it-ext`, 우리 run 변화 없음 | I2 I3 | O |  | P0 |
| EXEC-04 | 키로 runtime·maintenance·attempts 경로 | 404, executor로 가지 않음 | I2 | O |  | P0 |
| EXEC-05 | 결과물 `/artifacts/{id}`·`/view/artifacts/{id}` | 프로젝트 멤버만, 비멤버 거부, 외부 tenant 결과물은 안 보임 | I1 I3 | O |  | P0 |
| EXEC-06 | 우리 tenant 키, `X-User-Id` 없이 GET / POST | GET은 우리 tenant 전체, POST는 400 | I2 I3 | O |  | P1 |
| EXEC-07 | 우리 tenant 키로 남의 프로젝트·세션 헤더 | 403 | I2 | O |  | P1 |
| EXEC-08 | 관리자 시스템 > 런타임·점검 탭 | 200. `EXECUTOR_ADMIN_API_KEY`를 비우면 그 탭만 503 | I1 I4 | 일부 (관리자) |  | P1 |

### D. 배치: pr-batch → executor → 리포트 (BAT)

| ID | 시나리오 | 기대 결과 | 경로 | 화면 | 단독 | 우선 |
| --- | --- | --- | --- | --- | --- | --- |
| BAT-01 | 분석 노트북으로 스크립트 등록(`from-notebook`) | pr-batch 스크립트 생성, owner = 사번 | I1 I3 I6 | O |  | P0 |
| BAT-02 | 일정 있는 배치 생성 | `can_enable: true`, tenant `dtest-agent-service` 저장 | I6 | O |  | P0 |
| BAT-03 | 지금 실행 | run `SUBMITTED → RUNNING → COLLECTING → COMPLETED`, executor `trigger {type: BATCH}`, `context.user_id`·`created_by` = `<사번>`, `created_by_client` = pr-batch key 이름 | I6 I7 | O |  | P0 |
| BAT-04 | 배치 리포트 | `/batch-reports` job `SUCCEEDED` + `artifact_id`, 노트북 마지막 셀에 리포트 | I3 I5 | O |  | P0 |
| BAT-05 | 일정에 의한 실행(5분 뒤 1회) | 예정 시각 1분 안에 제출, BAT-03·BAT-04와 같은 결과 | I7 | O |  | P0 |
| BAT-06 | 실패하는 스크립트 | run `FAILED`, 리포트 job 없음 | I7 | O |  | P0 |
| BAT-07 | 같은 배치 2회차 | 리포트가 1회차 요약을 참고(배치 메모리) | I5 | O |  | P1 |
| BAT-08 | 우리 워커를 내린 채 배치 성공 → 재기동 | 10분 안에 복구 스위프로 리포트 생성 | I3 | 일부 (운영) | 단독 | P1 |
| BAT-09 | 일정 없는 배치 / 지난 일정만 있는 배치 | `enable_blocked_reason` `SCHEDULE_REQUIRED` / `NO_FUTURE_OCCURRENCE`, 켜기 409 / 422 | I6 | O |  | P1 |
| BAT-10 | 외부 tenant 키로 배치 등록·실행 | tenant `it-ext`로 저장·제출, 우리 리포트는 만들어지지 않음 | I2 I6 I7 | O |  | P1 |

### E. tenant 폐기·사용자 비활성화 (TEN)

| ID | 시나리오 | 기대 결과 | 경로 | 화면 | 단독 | 우선 |
| --- | --- | --- | --- | --- | --- | --- |
| TEN-01 | 외부 tenant `it-ext` 일괄 폐기 (BAT-10 배치가 켜진 상태) | 키 60초 안에 401, `disable-by-tenant`로 배치 꺼짐(`TENANT_REVOKED`), 응답 `batches_disabled: true`(실패 시 `batches_disable_pending: true`), 이미 제출된 실행은 끝까지 | I6 | O | 단독 | P0 |
| TEN-02 | pr-batch를 내린 채 tenant 폐기 | `batches_disable_pending: true`, pr-batch 복구 후 5분 안에 재시도로 꺼짐 | I6 | 일부 (운영) | 단독 | P0 |
| TEN-03 | 사용자 B 비활성화 | 30초 안에 SSO·키 모두 차단, `disable-by-owner`로 B의 배치 꺼짐, 수동 실행 409 `OWNER_DEACTIVATED` | I1 I6 | O | 단독 | P0 |
| TEN-04 | tenant의 마지막 active 키를 개별 폐기 | TEN-01과 같음 | I6 | O | 단독 | P1 |
| TEN-05 | 우리 tenant 키 폐기 | 그 키만 401, SSO 사용자의 배치는 켜진 채 | I2 | O |  | P1 |
| TEN-06 | B 재활성화 | 로그인 가능, 배치는 꺼진 채 | I1 | O |  | P1 |
| TEN-07 | pr-batch를 내린 채 사용자 비활성화 | `batches_disable_pending`, 5분 재시도로 꺼짐 | I6 | 일부 (운영) | 단독 | P1 |

### F. 관리자 (ADM)

| ID | 시나리오 | 기대 결과 | 경로 | 화면 | 단독 | 우선 |
| --- | --- | --- | --- | --- | --- | --- |
| ADM-01 | 시스템 > API 키 발급·목록·폐기 | 원문은 발급 응답에만 1회, 목록에 원문 없음 | I1 | O |  | P0 |
| ADM-02 | 일반 사용자의 관리자 화면·API 접근 | 메뉴 안 보임, API 403 | I1 | O |  | P0 |
| ADM-03 | 사용자 관리 화면에서 비활성화·재활성화 | TEN-03·TEN-06과 같은 결과를 화면에서 확인 | I1 | O |  | P0 |
| ADM-04 | `/users/me` `permissions` | 관리자·일반 각각 `system`·`all_executions`·`execution_internals` 값이 화면과 일치 | I1 | O |  | P1 |
| ADM-05 | 관리자 전체 실행 보기 + 사용자 필터 | 필터 사번이 `X-User-Id`로 전달되고 그 사람 실행만 | I1 I3 | O |  | P1 |
| ADM-06 | 워크플로 승격·삭제 | `recommendable`·`can_delete` 값대로 버튼 동작 | I1 | O |  | P1 |

### G. 장애·설정 오류·부하 (OPS)

| ID | 시나리오 | 기대 결과 | 경로 | 화면 | 단독 | 우선 |
| --- | --- | --- | --- | --- | --- | --- |
| OPS-01 | executor를 내린 채 분석 요청, 이후 복구 | run이 오류 문구와 함께 끝나고 화면이 멈추지 않음. 복구 후 새 run 정상 | I3 | 일부 (운영) | 단독 | P0 |
| OPS-02 | Redis 재시작 | 컨슈머 그룹 재생성, 놓친 이벤트 복구로 run 완료 | I5 | 일부 (운영) | 단독 | P0 |
| OPS-03 | 키 해시 불일치(일부러 틀린 키) | 화면에는 표준 오류, 로그에 대상 서비스와 401 | I3 I6 | 일부 (운영) | 단독 | P0 |
| OPS-04 | pr-batch를 내린 채 배치 화면 | 표준 오류 형식(code, message), 다른 화면은 정상 | I6 | 일부 (운영) | 단독 | P1 |
| OPS-05 | 백그라운드 루프 정지 | `/healthz` 503 → Pod 재시작 (gaia는 `/api/v1/healthz`) | - | X (운영) | 단독 | P1 |
| OPS-06 | prd 설정에 `<...>` 자리 남김, 빈 `SSO_ALLOWED_ORIGINS` | 기동 실패 | - | X (운영) | 단독 | P1 |
| OPS-07 | 32MB에 가까운 요청, 이미지 한도 초과 | 우리 413/422가 화면에 표시, Ingress가 먼저 끊지 않음 | I1 | O |  | P1 |
| OPS-08 | 없는 모델, LLM 장애 | 422 `UNKNOWN_MODEL` / run `failed`. 오류 문구에 원인(사용량 한도·권한·컨텍스트 초과·서버 오류)과 게이트웨이 메시지, 오류 ID. 주소·비밀값은 가려짐 | - | 일부 (운영) |  | P1 |
| OPS-09 | 동시 사용자 부하(`scripts/loadtest.py`) | executor 런타임·PG 연결 고갈 없음, 커널 대기 1800초 설정 조정 근거 확보 | I3 | X (운영) | 단독 | P1 |
| OPS-10 | 항상 실패하는 코드를 요구하는 요청 | 같은 tool이 연속 5회(`AGENT_TOOL_FAILURE_ANY_LIMIT`) 실패하면 멈추고 턴이 끝남. executor 재개 후에도 턴당 모델 호출 40회 상한 유지, 실행이 계속 늘지 않음 | I1 I3 I5 | O |  | P0 |

### H. gaia (GAIA, internal/gaia, 내부망 prd)

| ID | 시나리오 | 기대 결과 | 경로 | 화면 | 단독 | 우선 |
| --- | --- | --- | --- | --- | --- | --- |
| GAIA-01 | gaia completion 첫 호출 | 사용자·세션 매핑 생성, 답변 스트리밍, 표준 shape(answer, urls, docs, usage, trace_id) | I8 | X (gaia 화면) |  | P0 |
| GAIA-02 | 계획 승인 자동 응답 | 첫 후보 승인, reject_templates 안 보냄, executor 실행까지 | I8 I3 | X (gaia 화면) |  | P0 |
| GAIA-03 | question에서 멈춤 → 다음 gaia 메시지 | 같은 run 재개 | I8 | X (gaia 화면) |  | P0 |
| GAIA-04 | SSO와 gaia의 사번 대소문자 표기 | 같은 사용자로 매핑 (Go/No-Go F8) | I8 I9 | X (gaia 화면) |  | P0 |
| GAIA-05 | 같은 대화가 웹 콘솔 세션에 보임 | 제목 "gaia: …" 세션 | I8 I1 | O |  | P1 |
| GAIA-06 | 호출이 끊긴 뒤 재호출 | 새 run을 만들지 않고 기존 run을 이어서 기다림 | I8 | X (gaia 화면) |  | P1 |
| GAIA-07 | gaia `GAIA_DEPLOYMENT=development` 이상에서 accesskey 없이 호출 | 우리 경로(`/api/v1/`, `/view/`, `/dev/`)는 SSO·API 키로 동작, gaia 템플릿 API는 401 "Access key is required" | I8 | O |  | P0 |

## 화면 수행 기준

- 76개 중 우리 화면만으로 되는 것 56개, 화면 + 보조 확인 10개, 화면 밖 10개입니다(PREP 제외). 화면 보완 S1~S6(11/04)을 반영한 수치입니다. 상세는 공유 폴더 `integration-test/screen-coverage-review.md`.
- 키 호출 시나리오는 관리자 **시스템 > API 호출 시험** 화면에서 합니다. 시나리오를 고르면 경로·본문·헤더가 채워지고, 서버 응답(상태 코드, request id, 본문)을 그대로 보여 줍니다. 키는 저장하지 않고 요청·응답 기록에서 가립니다.
- 화면 밖으로 남는 것은 **운영**(서비스 중지·재시작, 설정 변경, Redis·DB·로그 확인, 부하 스크립트)과 **gaia 화면**입니다. 담당 팀이 수행하고, 결과 확인은 우리 화면에서 같이 합니다.
- 증빙은 화면 우측 상단 **요청·응답** 창(요청·응답 본문, SSE), 오류 메시지의 request id, 채팅 머리의 프로젝트·세션·run id, 실행 이력 > 개요(tenant, created_by, created_by_client)를 씁니다.
- 화면에는 판단 로직을 넣지 않습니다. 화면은 백엔드가 준 값(`permissions`, `can_enable`, `enable_blocked_reason`, `allow_reject_templates`, `recommendable`, `can_delete`, `batches_disable_pending` 등)만 보고 그립니다. 화면에서 막힌 것처럼 보여도 서버가 판정한 결과인지 확인합니다.
- 수행자 PC는 Windows입니다. 명령이 필요하면 PowerShell 기준(`curl.exe`, 줄바꿈은 백틱)으로 씁니다.

## 환경 진행 순서

| 환경 | 구성 | 주로 보는 것 | 들어가는 조건 | 나오는 조건 |
| --- | --- | --- | --- | --- |
| dev (예습) | 클러스터, idp SSO, 실제 LLM, dev 전용 키 | 전 시나리오를 한 번 돌려 절차서와 기대 결과를 다듬음, 결함 조기 발견 | dev의 PREP 완료 | P0 전부 수행(실패는 결함 등록), 절차서 수정 반영 |
| prd (본 테스트, 오픈 전) | 내부망, internal/gaia, prd 전용 키, 운영과 같은 설정 | 전 시나리오 + gaia(GAIA), 부하(OPS-09), 설정 검사(OPS-06), liveness(OPS-05) | dev 종료 + prd의 PREP 완료(리셋은 오픈 전 마지막으로 한 번 더) | P0 100%, P1 90% 이상, 부하 결과로 설정값 확정 |

**환경을 옮길 때** PREP를 처음부터 다시 밟습니다. 키는 환경별로 따로 만들고 DB·Redis·PV도 환경별로 비웁니다. **prd는 본 테스트가 끝난 뒤 오픈 전에 PREP-06(리셋)을 한 번 더** 해서 테스트 데이터·폐기된 키·비활성 사용자를 지웁니다.

**결함을 고친 뒤**에는 main과 internal/gaia 둘 다에 반영하고, 고친 시나리오와 핵심 스모크 4개(AUTH-01, RUN-01, BAT-03, BAT-04)를 그 환경에서 다시 돌립니다(상황판 상태 `재테스트`). 다른 서비스가 고친 경우도 같습니다.

## 통과 기준과 증적

통과 판정은 화면만 보지 않고 세 서비스의 기록이 서로 맞는지까지 봅니다. 시나리오 하나의 통과는 아래 네 가지가 모두 맞는 것입니다.

1. 기대 결과(상태 코드, 상태 값, 오류 코드, 카드·이벤트 종류)가 표와 같음. 에이전트 답변 문구는 매번 달라지므로 문장으로 판정하지 않음
2. 사용자 ID가 세 서비스에서 같은 소문자 사번: 우리 `users.id`, executor `context.user_id`·`created_by`·작업 공간 경로, pr-batch owner
3. tenant가 의도한 값: 우리 요청은 `dtest-agent-service`, 외부 키는 그 키의 tenant
4. 로그에 오류 레벨 기록이 없거나, 있으면 그 시나리오가 일부러 낸 것

| 단계 | 통과 기준 |
| --- | --- |
| 환경 종료 | 그 환경 P0 100%, P1 90% 이상. 남은 P1은 담당·수정 예정일이 있음 (dev는 수행 완료가 기준) |
| 통합테스트 종료 | I1~I9 경로를 모두 한 번 이상 통과, prd P0 100%, 열린 결함에 막는 것(데이터 손상·권한 우회·배치 미중지) 없음 |
| 시간 기준 | 키 폐기 60초, 사용자 차단 30초, 배치 끄기 재시도 5분, 배치 리포트 복구 10분, 놓친 run 이벤트 복구 120초 |

**증적**(시나리오마다 한 줄 기록)

- 우리 `request_id`와 감사 로그 `api_client_request …`
- run ID, executor `execution_id`, pr-batch run ID
- executor `GET /executions/{id}`의 `trigger`·`context`, pr-batch 배치의 owner·tenant·`disabled_reason`
- 화면 스크린샷(브라우저 시나리오만), `run_scenarios.py` 결과 JSON

결과는 상황판(ID · 환경 · 상태 · 링크 · 결함번호)과 시나리오별 컨플루언스 페이지로 남깁니다. 페이지 양식은 `scenario-page-template.md`.

## 설계 리뷰

네 저장소를 읽고 찾은 것입니다. 11/04에 상태를 다시 확인했습니다.

| # | 발견 | 영향 | 조치 | 담당 | 상태 |
| --- | --- | --- | --- | --- | --- |
| R1 | pr-batch `compose.yaml`에 `EXECUTOR_API_KEY` 항목 없음 | 로컬 배치 실행 실패 | pr-batch compose에 기본값 추가 | pr-batch | 로컬 개발용, 통합테스트(dev·prd) 범위 밖 |
| R2 | 우리 `docker-compose.yml`의 `BATCH_API_KEY` 기본값이 빈 값 | 로컬 게이트웨이 호출 401 | pr-batch 로컬 키가 정해지면 기본값으로 | 우리 | 로컬 개발용, 미반영 |
| R3 | `smoke_e2e.py`·`run_scenarios.py`·`loadtest.py`가 dev SSO 로그인만 지원 | dev·prd(idp)에서 RUN-14·OPS-09 자동화 불가 | `X-Api-Key` + `X-User-Id` 모드 옵션 추가 | 우리 | 미반영 |
| R4 | 이전 리셋 요청에 Redis 스트림이 빠져 있음 | 옛 uuid 사용자의 이벤트가 남음 | PREP-06에 포함 | 인프라 | 반영(문서) |
| R5 | Go/No-Go F1·F2·F3·F8 | 미반영이면 OPS-06·GAIA-04 실패 | 반영 여부 확인 | 우리 | 완료(main `f0fed74`, internal/gaia `60aa017`) |
| R6 | pr-batch가 `can_enable`·`can_disable`·`enable_blocked_reason`을 직접 줌 | 우리 계산이 덮으면 BAT-09 사유가 빠짐 | pr-batch 값을 그대로 넘김 | 우리 | 완료(게이트웨이가 그대로 전달, `tests/test_batch_gateway.py`) |
| R7 | local은 dev SSO 어댑터라 실제 idp를 거치지 않음 | | dev 예습으로 대체 | 우리 | 해소(local 단계 없음) |
| R8 | executor 10/21 점검 항목(handover 후 projection·완료 이벤트, 배치 대상 반환 뒤 리포트 저장) 현재 상태 모름 | BAT-04 실패 시 1순위 원인 후보 | executor에 확인 요청 | executor | 확인 대기 |
| R9 | 맥 로컬 저장소 루트의 `인증가이드.md`(예전 pr-auth 토큰 설계) | 테스트 참여자 혼동 | 삭제하거나 "폐기됨" 표시 | 사용자 | 확인 대기 |
| R10 | 우리 화면 `/dev/`가 `APP_ENV` local·dev에서만 열렸음 | prd에서 화면 시나리오 수행 불가 | `WEB_CONSOLE_ENABLED`(prd는 `true`), 화면 로그인 후 API 호스트의 `/dev/`로 복귀. **오픈 때 `false`로** | 우리 | 완료(11/04, 화면 보완 S1~S6) |
| R11 | 결과 경로가 통합 루트 기준만 지원(옛 `executions/...` 삭제, `35313b2`) | executor가 옛 버전이면 이미지·단계 결과를 못 읽음 | PREP-07에서 executor 통합 루트 버전 먼저 | executor | 배포 순서에 반영 |
| R12 | 기본 임베딩이 꺼져 있고(`none`), 게이트웨이 bge-m3는 `dimensions`를 거부 | 임베딩 없으면 RUN-08 자동 실행이 절대 안 일어남 | prd에서 임베딩을 쓸지 정하고 PREP-04에서 확인 | 우리 | 결정 필요 |

**정해야 할 것**

- [ ] 환경별 테스트 일정, 담당자, DB·Redis·PV 리셋을 누가 실행할지
- [ ] prd 오픈 때 화면을 끌지 (`WEB_CONSOLE_ENABLED: false`)
- [ ] prd에서 임베딩을 쓸지 (RUN-08 수행 여부)
- [ ] R3 테스트 스크립트 키 모드 진행 여부
- [ ] 외부 tenant 테스트 이름 `it-ext`를 쓸지, 실제 상위 에이전트 tenant로 할지
- [ ] 결함번호를 어디서 매길지 (Jira 등)

## 다른 팀 요청 (복사용)

아래는 그대로 전달할 수 있는 문구입니다. 11/01 요청(헤더 모드 삭제 후 키 설정, DB 리셋)에 통합테스트에 필요한 것을 더했습니다.

**executor 담당께**

1. 환경별(dev, prd) `scripts/generate_api_keys.py`로 `pr-agentic-service`·`pr-batch`·`ops` 키를 만들어 `AUTH_CLIENTS`의 0000… 해시를 교체하고, 키 원문은 우리와 pr-batch에 전달해 주세요. 로컬 compose의 로컬 키는 지금 값 그대로 유지해 주세요.
2. 환경마다 통합테스트 시작 전에 executor DB, 공유 PV `tenants/*/users/*`, Redis `executor.events.*` 스트림을 우리·pr-batch와 같은 시간에 비워 주세요.
3. 통합 루트(`/mnt/data/dtest`) 상대경로 버전을 우리보다 먼저 배포해 주세요. 우리는 옛 `executions/...` 형식을 더 이상 읽지 않습니다. 함께, 10/21 요청의 두 가지 현재 상태를 알려 주세요. handover가 일어난 SINGLE 실행에서도 노트북 projection `SUCCEEDED`와 `execution.completed`의 `execution{trigger, context}`가 나오는지, 배치 Jupyter 대상이 풀로 돌아간 뒤에도 `POST /executions/{id}/artifacts`(REPORT, `append_to_notebook`)가 되는지입니다.
4. 테스트 중 OPS-01(executor 중지)과 OPS-09(부하)를 할 때 런타임 수와 로그를 함께 봐 주세요.

**pr-batch 담당께**

1. (로컬 개발용, 통합테스트 범위 밖) `compose.yaml`의 `x-batch-env`에 `EXECUTOR_API_KEY` 기본값(executor compose의 `exe_local_batch_…`)을 넣어 주세요.
2. dev·prd `config.{env}.yml`의 `EXECUTOR_API_KEY: REPLACE_EXECUTOR_KEY`를 executor에서 받은 키로, `AUTH_CLIENTS`의 `pr-agentic-service` 해시를 우리 `BATCH_API_KEY`의 SHA-256으로 바꿔 주세요(`admin: true`, `allowed_tenants: ["*"]` 유지).
3. 환경마다 통합테스트 전에 pr-batch DB를 같은 시간에 비워 주세요.
4. TEN-01·TEN-02(tenant 폐기)와 TEN-03(사용자 비활성화)에서 `disabled_reason`이 `TENANT_REVOKED`·`USER_DEACTIVATED`로 남는지 같이 봐 주세요. 추가 개발은 없습니다.

**인프라·SSO 담당께** (prj_re SSO 포함)

1. SSO 로그인 페이지 도메인(스킴 + 호스트, `SSO_ALLOWED_ORIGINS`용), 초기 관리자 사번 목록(SSO가 주는 표기 그대로), 내부망 idp 로그인·userinfo 주소와 응답 필드명을 알려 주세요.
2. 테스트 계정 사번 3개(관리자 1, 일반 2)를 준비해 주세요. 하나는 비활성화 테스트에 씁니다.
3. Ingress: 요청 본문 한도 32MB 이상, SSE 경로의 proxy read timeout 연장과 buffering off. PostgreSQL `max_connections`는 우리 Pod당 14 × 최대 4 = 56에 두 서비스를 더한 값 이상.
4. 리셋 때 Redis `executor.events.*` 스트림 삭제와 공유 PV 정리를 도와 주세요.

**gaia 담당께** (internal/gaia)

1. prd(내부망)에서 우리 workflow(`dtest.analyst`)를 부를 수 있는 gaia 화면 또는 API 경로와 테스트 시간을 정해 주세요.
2. gaia가 넘기는 `user_id`가 SSO 사번과 같은 표기(대소문자 포함)인지 알려 주세요. GAIA-04 결과가 여기에 달려 있습니다.

**우리(pr-agentic-service) 할 일**

- [x] 화면 보완 S1~S6 (설계 리뷰 R10)
- [ ] R3 테스트 스크립트 키 모드
- [ ] 환경별 설정 채우기와 테스트 키 발급(PREP-04·PREP-09)
- [ ] 시나리오별 수행 절차서 (양식은 `scenario-page-template.md`)

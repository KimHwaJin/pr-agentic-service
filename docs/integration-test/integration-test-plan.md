# 통합테스트 시나리오 및 진행방안 설계

2026-11-01 · 원본 문서: https://claude.ai/artifact/6Cvg7McSJyRnCqwDBq8eSk (이 파일은 그 시점의 사본입니다)

## 요약

**결론: 준비 단계(G0)를 끝내면 local → dev → stg 순서로 8개 영역(A~H) 71개 시나리오(P0 37개)를 돌립니다. 다만 시작 전에 막히는 것이 2건 있습니다.** 하나는 pr-batch 로컬 compose에 executor로 보낼 키(`EXECUTOR_API_KEY`)가 없어서 로컬에서 배치 실행이 전부 실패하는 것입니다. 다른 하나는 우리 compose의 `BATCH_API_KEY` 기본값이 비어 있는 것입니다. pr-batch가 로컬 키 `bat_local_agent_…`를 compose에 공개했으므로 그 값을 기본값으로 넣으면 됩니다.

- 기준 커밋: pr-agentic-service main `f5281e1`, internal/gaia `0e1158b` · executor main `170ad98` · pr-batch main `06a3d9a` · prj_re `feature/refactor-base` `d19b360` (맥 로컬, 읽기만 함)
- 세 서비스 모두 헤더 모드가 삭제되어 로컬을 포함한 모든 환경이 키 인증입니다. 그래서 로컬에서도 키 6개가 맞물려야 시나리오가 돕니다.
- 진행 방식: 각 환경은 들어가는 조건과 나오는 조건(게이트)을 둡니다. P0 시나리오가 전부 통과해야 다음 환경으로 넘어갑니다.
- 다른 팀 요청은 마지막 절에 복사용으로 정리했습니다. executor·pr-batch·prj_re 코드는 읽기만 했습니다.

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
| I7 | pr-batch → executor | pr-batch의 `EXECUTOR_API_KEY` | `trigger BATCH` + `actor USER(owner)`, 배치의 tenant로 제출 |
| I8 | gaia → 우리 (internal/gaia만) | gaia가 넘기는 사번 | gaia 세션 ↔ 우리 세션 매핑, 확인 단계 자동 응답 |
| I9 | 우리 → SSO(idp) | idp 로그인 페이지·userinfo | `SSO_ALLOWED_ORIGINS`, 사번 표기(대소문자), 관리자 최초 로그인 |

공유 자원: PostgreSQL(서비스별 DB 3개), Redis(이벤트 스트림), 공유 PV(입력 코드·실행 결과).

## 사전 준비 순서 (G0)

순서가 중요한 것은 세 가지입니다. 관리자 사번은 관리자가 처음 로그인하기 전에 넣어야 하고, DB·Redis·PV는 세 서비스를 동시에 비워야 하고, 배포는 executor → pr-batch → 우리 순서로 해야 합니다. 환경마다(local, dev, stg) 같은 순서를 밟습니다.

| 순서 | 할 일 | 담당 | 완료 확인 |
| --- | --- | --- | --- |
| 1 | 기준 커밋 고정: 네 저장소의 테스트 대상 커밋을 이 문서에 적고, 테스트 중에는 병합한 변경만 다시 배포 | 우리 | 커밋 표 갱신 |
| 2 | 환경별 키 생성: executor `scripts/generate_api_keys.py <env>`로 우리→executor, ops, pr-batch→executor 키를 만들고, 우리→pr-batch 키도 같은 방식(임의 문자열 + SHA-256)으로 만듦. 환경끼리 키 공유 금지 | 우리 + executor | 키 4개, 해시 4개 |
| 3 | 해시 교환: executor `AUTH_CLIENTS`의 `pr-agentic-service`·`pr-batch`·`ops`, pr-batch `AUTH_CLIENTS`의 `pr-agentic-service`를 0000…에서 실제 해시로 교체. 키 원문은 우리 `EXECUTOR_API_KEY`·`EXECUTOR_ADMIN_API_KEY`·`BATCH_API_KEY`, pr-batch `EXECUTOR_API_KEY`에 | executor, pr-batch | 세 서비스 설정 diff |
| 4 | 우리 설정 채우기: `config.{env}.yml`의 `<...>` 자리(DATABASE_URL, REDIS_URL, PUBLIC_API_ORIGIN, FRONTEND_ORIGIN, CORS_ORIGINS, LLM_API_KEY, MODELS, EXECUTOR·BATCH 주소), `SSO_ALLOWED_ORIGINS`, `ADMIN_EMPLOYEE_IDS`. Redis는 executor가 이벤트를 쓰는 같은 Redis여야 함 | 우리 | `<`가 남은 값 0개 (`grep '<' config.{env}.yml`) |
| 5 | internal/gaia만: `src/dtest/idp_login.py`의 `SSO_LOGIN_PAGE`·`USERINFO_URL`·`FIELDS`, 템플릿 고정값(`PORT`, `PROJECT_NAME`, `SERVICE_NAME`), HCP·gaia 의존성 추가 후 `uv lock` | 우리 + SSO 담당 | userinfo 응답 필드명 확인 |
| 6 | 세 서비스 중지 후 동시 리셋: 우리·executor·pr-batch DB, 공유 PV의 `tenants/*/users/*`와 우리 `STORAGE_ROOT` 아래, Redis의 `executor.events.*` 스트림과 컨슈머 그룹 | 세 팀 + 인프라 | DB 테이블 비어 있음, 스트림 없음 |
| 7 | 배포: executor → pr-batch → 우리. 마이그레이션은 기동 시 자동(우리 0006까지) | 각 팀 | 각 서비스 health 200 |
| 8 | 연결 스모크(S0, 아래) | 우리 | S0 전부 통과 |
| 9 | 관리자 최초 로그인 → `/users/me`에서 admin 확인 → 테스트 키 2개 발급: 우리 tenant(`own_tenant: true`)와 외부 tenant 가정 `it-ext` | 우리 | 키 원문 2개 보관 |
| 10 | 테스트 데이터: 합성 nce 데이터, `scripts/seed_test_workflows.py`, 배치용 노트북 1개(성공용)과 일부러 실패하는 노트북 1개 | 우리 | 데이터 조회 가능 |

**테스트 계정:** 사번 3개가 필요합니다. 관리자 1명, 일반 사용자 A와 B(공유 프로젝트·권한 확인용). 비활성화 시나리오는 B로 합니다.

**S0 연결 스모크** (시나리오 전에 5분 안에 끝내는 확인)

1. 우리 → executor: 관리자 화면 실행 목록 200 (I3), 시스템 > 런타임 탭 200 (I4)
2. 우리 → pr-batch: `GET /api/v1/batch/runtimes` 200 (I6)
3. pr-batch → executor: 일정 있는 배치를 하나 만들어 `enable_blocked_reason`이 `EXECUTOR_NOT_CONFIGURED`가 아닌지 (I7)
4. Redis: `XINFO GROUPS executor.events.dtest-agent-service`에 우리 그룹이 있음 (I5)

401이 나면 해당 쌍의 키·해시부터 다시 봅니다. 많이 틀리는 곳은 3번입니다.

## 시나리오

시나리오는 영역별로 A~H입니다. P0는 다음 환경으로 넘어가기 전에 모두 통과해야 하고, P1은 실패해도 우회책과 담당이 있으면 넘어갑니다. 환경 칸의 L·D·S는 local·dev·stg입니다. 실패 케이스는 각 영역 안에 함께 두었고, 서비스 장애와 설정 오류는 G에 모았습니다.

### A. 인증

| ID | 시나리오 | 기대 결과 | 경로 | 환경 | 우선 |
| --- | --- | --- | --- | --- | --- |
| A1 | SSO 첫 로그인 | `users.id` = 소문자 사번, 기본 프로젝트 생성 | I1 I9 | L D S | P0 |
| A2 | `ADMIN_EMPLOYEE_IDS`에 있는 사번의 최초 로그인 | admin, `/users/me` `permissions.system: true` | I1 I9 | D S | P0 |
| A3 | 브라우저 쓰기 요청에 `X-CSRF-Token` 없음 | 403 | I1 | L | P0 |
| A4 | 키 + `X-User-Id`로 `GET /users/me` | 200, 감사 로그에 client·tenant·user·`request_id` | I2 | L D S | P0 |
| A5 | `X-User-Id`가 우리 DB에 없는 사번 / 형식 위반 | 403 / 400 | I2 | L | P0 |
| A6 | 키로 관리자 API 호출 | 403 "SSO login" | I2 | L | P0 |
| A7 | 키 개별 폐기 | 60초 안에 모든 Pod에서 401 `INVALID_API_KEY` | I2 | L D | P0 |
| A8 | 우리 tenant 키를 `own_tenant` 없이 발급 | 422 | I2 | L | P1 |
| A9 | 쿠키와 키를 함께 보냄 | 쿠키 사용자로 처리, 키·`X-User-Id` 무시 | I1 I2 | L | P1 |
| A10 | SSO 로그인 페이지 도메인이 `SSO_ALLOWED_ORIGINS`에 없음 | 502, 로그 `sso_login_url_rejected` | I9 | D | P1 |
| A11 | 비관리자 사용자가 dev 역할 변경 `POST /auth/dev/role` | dev·stg에서는 404 (로컬 전용) | I1 | D S | P1 |

### B. 세션·run 실행

| ID | 시나리오 | 기대 결과 | 경로 | 환경 | 우선 |
| --- | --- | --- | --- | --- | --- |
| B1 | 브라우저: 새 세션 + 분석 요청 → plan_approval 승인 → executor 실행 → 리포트 | run `succeeded`, `execution_completed`·`artifact` 이벤트, 답변에 attachments | I1 I3 I5 | L D S | P0 |
| B2 | 같은 흐름을 키 호출자로 (Swagger 가이드 1절) | B1과 같음, executor `X-User-Id` = 사번 | I2 I3 I5 | L D | P0 |
| B3 | Ingress를 거친 SSE `GET /sessions/{id}/events` | token이 묶여 오지 않고 5분 넘게 연결 유지 | I1 | D S | P0 |
| B4 | code_approval·question·workflow_save 응답 | 202 `resumed: true`, 같은 run이 이어짐 | I1 | L D | P0 |
| B5 | 실행 중 run 취소 | run `cancelled`, executor 실행도 취소(소유자 `X-User-Id`) | I1 I3 | L D | P0 |
| B6 | `waiting_executor` 중 우리 워커 재시작 | 놓친 이벤트 복구로 run이 이어짐(복구 주기 120초) | I3 I5 | L D | P0 |
| B7 | reject_templates (`allow_reject_templates: true`인 카드) | 새 계획의 plan_approval 재도착. false인 카드에 보내면 422 | I1 | L D | P1 |
| B8 | 자동 실행 조건 충족(후보 1개, 유사도 0.77 이상) | `plan_auto_approved` 이벤트, 새로고침 후에도 남음 | I1 | D | P1 |
| B9 | 진행 중 세션에 새 턴 | 409 `SESSION_BUSY` | I1 | L | P1 |
| B10 | 오래된 `interrupt_id`로 재개 | 409 `STALE_INTERRUPT` | I1 | L | P1 |
| B11 | 필수 입력을 비우고 승인 | 422 `INVALID_ANSWER`, `details[].location`이 그 칸 | I1 | L | P1 |
| B12 | 공유 프로젝트에서 B가 A의 세션을 이어 실행 | 이어지는 executor 호출의 `X-User-Id`는 A(실행 소유자) | I1 I3 | D | P1 |
| B13 | 실행 중 세션 삭제 | 진행 중 executor 실행 취소 | I1 I3 | L | P1 |
| B14 | 분석 시나리오 묶음 `scripts/run_scenarios.py` | 점수표 JSON, 이전 기준선 이상 | I1 I3 | L D S | P1 |

### C. executor 연동·게이트웨이

| ID | 시나리오 | 기대 결과 | 경로 | 환경 | 우선 |
| --- | --- | --- | --- | --- | --- |
| C1 | 우리 tenant 키 + `X-User-Id`로 `GET /executor/executions` | 본인 실행만 | I2 I3 | L D | P0 |
| C2 | INLINE `print(1+1)` 제출(curl) | result에 `2`, PV `tenants/dtest-agent-service/users/<사번>/…`에 생성 | I2 I3 | L D | P0 |
| C3 | 외부 tenant(`it-ext`) 키로 실행 제출 | `tenants/it-ext/…`에 생성, 이벤트는 `executor.events.it-ext`, 우리 run 변화 없음 | I2 I3 | L D | P0 |
| C4 | 키로 runtime·maintenance·attempts 경로 | 404, executor로 가지 않음 | I2 | L | P0 |
| C5 | 결과물 `/artifacts/{id}`·`/view/artifacts/{id}` | 프로젝트 멤버만, 비멤버 거부, 외부 tenant 결과물은 안 보임 | I1 I3 | L D | P0 |
| C6 | 우리 tenant 키, `X-User-Id` 없이 GET / POST | GET은 우리 tenant 전체, POST는 400 | I2 I3 | L | P1 |
| C7 | 우리 tenant 키로 남의 프로젝트·세션 헤더 | 403 | I2 | L | P1 |
| C8 | 관리자 시스템 > 런타임·점검 탭 | 200. `EXECUTOR_ADMIN_API_KEY`를 비우면 그 탭만 503 | I1 I4 | L D | P1 |

### D. 배치 (pr-batch → executor → 리포트)

| ID | 시나리오 | 기대 결과 | 경로 | 환경 | 우선 |
| --- | --- | --- | --- | --- | --- |
| D1 | 분석 노트북으로 스크립트 등록(`from-notebook`) | pr-batch 스크립트 생성, owner = 사번 | I1 I3 I6 | L D | P0 |
| D2 | 일정 있는 배치 생성 | `can_enable: true`, tenant `dtest-agent-service` 저장 | I6 | L D | P0 |
| D3 | 지금 실행 | run `SUBMITTED → RUNNING → COLLECTING → COMPLETED`, executor `trigger BATCH` + `actor USER id=<사번>` | I6 I7 | L D S | P0 |
| D4 | 배치 리포트 | `/batch-reports` job `SUCCEEDED` + `artifact_id`, 노트북 마지막 셀에 리포트 | I3 I5 | L D S | P0 |
| D5 | 일정에 의한 실행(5분 뒤 1회) | 예정 시각 1분 안에 제출, D3·D4와 같은 결과 | I7 | D | P0 |
| D6 | 실패하는 스크립트 | run `FAILED`, 리포트 job 없음 | I7 | L D | P0 |
| D7 | 같은 배치 2회차 | 리포트가 1회차 요약을 참고(배치 메모리) | I5 | L D | P1 |
| D8 | 우리 워커를 내린 채 배치 성공 → 재기동 | 10분 안에 복구 스위프로 리포트 생성 | I3 | L | P1 |
| D9 | 일정 없는 배치 / 지난 일정만 있는 배치 | `enable_blocked_reason` `SCHEDULE_REQUIRED` / `NO_FUTURE_OCCURRENCE`, 켜기 409 / 422 | I6 | L | P1 |
| D10 | 외부 tenant 키로 배치 등록·실행 | tenant `it-ext`로 저장·제출, 우리 리포트는 만들어지지 않음 | I2 I6 I7 | L D | P1 |

### E. tenant 폐기·사용자 비활성화

| ID | 시나리오 | 기대 결과 | 경로 | 환경 | 우선 |
| --- | --- | --- | --- | --- | --- |
| E1 | 외부 tenant `it-ext` 일괄 폐기 (D10 배치가 켜진 상태) | 키 60초 안에 401, `disable-by-tenant`로 배치 꺼짐(`TENANT_REVOKED`), 응답 `batches_disabled` ≥ 1, 이미 제출된 실행은 끝까지 | I6 | L D | P0 |
| E2 | pr-batch를 내린 채 tenant 폐기 | `batches_disable_pending: true`, pr-batch 복구 후 5분 안에 재시도로 꺼짐 | I6 | L | P0 |
| E3 | 사용자 B 비활성화 | 30초 안에 SSO·키 모두 차단, `disable-by-owner`로 B의 배치 꺼짐, 수동 실행 409 `OWNER_DEACTIVATED` | I1 I6 | L D | P0 |
| E4 | tenant의 마지막 active 키를 개별 폐기 | E1과 같음 | I6 | L | P1 |
| E5 | 우리 tenant 키 폐기 | 그 키만 401, SSO 사용자의 배치는 켜진 채 | I2 | L | P1 |
| E6 | B 재활성화 | 로그인 가능, 배치는 꺼진 채 | I1 | L | P1 |
| E7 | pr-batch를 내린 채 사용자 비활성화 | `batches_disable_pending`, 5분 재시도로 꺼짐 | I6 | L | P1 |

### F. 관리자

| ID | 시나리오 | 기대 결과 | 경로 | 환경 | 우선 |
| --- | --- | --- | --- | --- | --- |
| F1 | 시스템 > API 키 발급·목록·폐기 | 원문은 발급 응답에만 1회, 목록에 원문 없음 | I1 | L D S | P0 |
| F2 | 일반 사용자의 관리자 화면·API 접근 | 메뉴 안 보임, API 403 | I1 | L D | P0 |
| F3 | 사용자 관리 화면에서 비활성화·재활성화 | E3·E6과 같은 결과를 화면에서 확인 | I1 | D | P0 |
| F4 | `/users/me` `permissions` | 관리자·일반 각각 `system`·`all_executions`·`execution_internals` 값이 화면과 일치 | I1 | L | P1 |
| F5 | 관리자 전체 실행 보기 + 사용자 필터 | 필터 사번이 `X-User-Id`로 전달되고 그 사람 실행만 | I1 I3 | L D | P1 |
| F6 | 워크플로 승격·삭제 | `recommendable`·`can_delete` 값대로 버튼 동작 | I1 | D | P1 |

### G. 장애·설정 오류·부하

| ID | 시나리오 | 기대 결과 | 경로 | 환경 | 우선 |
| --- | --- | --- | --- | --- | --- |
| G1 | executor를 내린 채 분석 요청, 이후 복구 | run이 오류 문구와 함께 끝나고 화면이 멈추지 않음. 복구 후 새 run 정상 | I3 | L | P0 |
| G2 | Redis 재시작 | 컨슈머 그룹 재생성, 놓친 이벤트 복구로 run 완료 | I5 | L | P0 |
| G3 | 키 해시 불일치(일부러 틀린 키) | 화면에는 표준 오류, 로그에 대상 서비스와 401 | I3 I6 | L | P0 |
| G4 | pr-batch를 내린 채 배치 화면 | 표준 오류 형식(code, message), 다른 화면은 정상 | I6 | L | P1 |
| G5 | 백그라운드 루프 정지 | `/healthz` 503 → Pod 재시작 (gaia는 `/api/v1/healthz`) | - | S | P1 |
| G6 | stg 설정에 `<...>` 자리 남김, 빈 `SSO_ALLOWED_ORIGINS` | 기동 실패 (Go/No-Go F3 반영 여부 확인 후) | - | S | P1 |
| G7 | 32MB에 가까운 요청, 이미지 한도 초과 | 우리 413/422가 화면에 표시, Ingress가 먼저 끊지 않음 | I1 | D S | P1 |
| G8 | 없는 모델, LLM 장애 | 422 `UNKNOWN_MODEL` / run `failed` + 오류 문구 | - | L D | P1 |
| G9 | 동시 사용자 부하(`scripts/loadtest.py`) | executor 런타임·PG 연결 고갈 없음, 커널 대기 1800초 설정 조정 근거 확보 | I3 | S | P1 |

### H. gaia (internal/gaia, 내부망 stg)

| ID | 시나리오 | 기대 결과 | 경로 | 환경 | 우선 |
| --- | --- | --- | --- | --- | --- |
| H1 | gaia completion 첫 호출 | 사용자·세션 매핑 생성, 답변 스트리밍, 표준 shape(answer, urls, docs, usage, trace_id) | I8 | S | P0 |
| H2 | 계획 승인 자동 응답 | 첫 후보 승인, reject_templates 안 보냄, executor 실행까지 | I8 I3 | S | P0 |
| H3 | question에서 멈춤 → 다음 gaia 메시지 | 같은 run 재개 | I8 | S | P0 |
| H4 | SSO와 gaia의 사번 대소문자 표기 | 같은 사용자로 매핑 (Go/No-Go F8) | I8 I9 | S | P0 |
| H5 | 같은 대화가 웹 콘솔 세션에 보임 | 제목 "gaia: …" 세션 | I8 I1 | S | P1 |
| H6 | 호출이 끊긴 뒤 재호출 | 새 run을 만들지 않고 기존 run을 이어서 기다림 | I8 | S | P1 |

## 환경 진행 순서

local에서 기능과 장애 케이스를 다 확인하고, dev에서 실제 SSO·Ingress·일정 실행을, stg에서 gaia·부하·운영 설정을 확인합니다. 장애를 일부러 내는 시나리오(G1~G4, E2, E7)는 서비스를 마음대로 내릴 수 있는 local에서만 합니다. stg는 내부망에서 internal/gaia 이미지로 도는 것으로 가정했습니다. 다르면 H 시나리오를 내부망 환경으로 옮깁니다.

| 환경 | 구성 | 주로 보는 것 | 들어가는 조건 | 나오는 조건 |
| --- | --- | --- | --- | --- |
| local | 맥 docker compose: executor(shared-infra → runtimes → executor) → pr-batch → 우리. dev SSO 어댑터, 실제 LLM 또는 `scripts/mock_llm.py` | A~G 기능, 장애·복구, 연동 헤더 | G0 + 로컬 차단 2건 해소(요약 참고) | L 표시 P0 전부 통과, 결함 목록 정리 |
| dev | 클러스터, idp SSO, 실제 LLM, dev 전용 키 | 실제 로그인·관리자 최초 로그인, Ingress SSE, 일정 실행, 화면 | local 종료 + dev의 G0(키·해시·리셋) 완료 | D 표시 P0 전부 통과 |
| stg | 내부망, internal/gaia, stg 전용 키 | gaia(H), 부하(G9), 설정 검사(G6), liveness(G5), prd와 같은 설정 | dev 종료 + stg의 G0 완료 | S 표시 P0 전부 통과, 부하 결과로 설정값 확정 |

**환경을 옮길 때마다** G0를 처음부터 다시 밟습니다. 키는 환경별로 따로 만들고 DB·Redis·PV도 환경별로 비웁니다.

**결함을 고친 뒤**에는 main과 internal/gaia 둘 다에 반영하고, 고친 시나리오와 핵심 스모크 4개(A1, B1, D3, D4)를 그 환경에서 다시 돌립니다. 다른 서비스가 고친 경우도 같습니다.

## 통과 기준과 증적

통과 판정은 화면만 보지 않고 세 서비스의 기록이 서로 맞는지까지 봅니다. 시나리오 하나의 통과는 아래 네 가지가 모두 맞는 것입니다.

1. 기대 결과(상태 코드, 상태 값, 오류 코드)가 표와 같음
2. 사용자 ID가 세 서비스에서 같은 소문자 사번: 우리 `users.id`, executor `context.user_id`·작업 공간 경로, pr-batch owner
3. tenant가 의도한 값: 우리 요청은 `dtest-agent-service`, 외부 키는 그 키의 tenant
4. 로그에 오류 레벨 기록이 없거나, 있으면 그 시나리오가 일부러 낸 것

| 단계 | 통과 기준 |
| --- | --- |
| 환경 종료 | 그 환경 P0 100%, P1 90% 이상. 남은 P1은 담당·수정 예정일이 있음 |
| 통합테스트 종료 | I1~I9 경로를 모두 한 번 이상 통과, stg P0 100%, 열린 결함에 막는 것(데이터 손상·권한 우회·배치 미중지) 없음 |
| 시간 기준 | 키 폐기 60초, 사용자 차단 30초, 배치 끄기 재시도 5분, 배치 리포트 복구 10분, 놓친 run 이벤트 복구 120초 |

**증적**(시나리오마다 한 줄 기록)

- 우리 `request_id`와 감사 로그 `api_client_request …`
- run ID, executor `execution_id`, pr-batch run ID
- executor `GET /executions/{id}`의 `trigger`·`context`, pr-batch 배치의 owner·tenant·`disabled_reason`
- 화면 스크린샷(브라우저 시나리오만), `run_scenarios.py` 결과 JSON

결과는 이 문서의 시나리오 ID로 묶어 환경별 결과표(ID · 환경 · 결과 · 증적 · 결함 번호)로 남깁니다.

## 설계 리뷰

네 저장소를 읽고 찾은 것입니다. R1·R2는 로컬 배치 시나리오(D, E)를 막고, R3은 dev·stg 자동화를 막습니다.

| # | 발견 | 영향 | 조치 | 담당 |
| --- | --- | --- | --- | --- |
| R1 | pr-batch `compose.yaml`에 `EXECUTOR_API_KEY` 항목이 없음. executor는 로컬에서도 키가 필수이고, pr-batch용 로컬 키 `exe_local_batch_…`는 executor compose에 이미 있음 | 로컬 배치 실행 전부 실패(D3~D10, E1·E2) | pr-batch compose에 기본값과 함께 추가 | pr-batch |
| R2 | 우리 `docker-compose.yml`의 `BATCH_API_KEY` 기본값이 빈 값 | 로컬 게이트웨이 호출 401 | 기본값을 pr-batch 로컬 키 `bat_local_agent_…`로. main·internal/gaia 모두 | 우리 |
| R3 | `smoke_e2e.py`·`run_scenarios.py`·`loadtest.py`가 dev SSO 로그인만 지원 | dev·stg(idp)에서 B14·G9 자동화 불가 | `X-Api-Key` + `X-User-Id` 모드 옵션 추가 | 우리 |
| R4 | 이전 리셋 요청에 Redis 스트림이 빠져 있음 | 옛 uuid 사용자의 이벤트가 남아 복구 로직이 다시 처리 | G0 6번에 포함(이 문서에 반영) | 인프라 |
| R5 | Go/No-Go F1(tenant 폐기 시 배치 끄기)과 F2(gaia liveness `/api/v1/healthz`)는 코드에서 반영 확인. F3(stg 설정 검사)과 F8(gaia 사번 대소문자)은 이번에 확인하지 못함 | 미반영이면 G6·H4 실패 | stg 전에 반영 여부 확인 | 우리 |
| R6 | pr-batch가 `can_enable`·`can_disable`·`enable_blocked_reason`을 직접 주기 시작(`4942492`). 우리 게이트웨이도 같은 값을 계산함 | 우리 계산이 pr-batch 값을 덮으면 D9에서 런타임·남은 회차 사유가 빠짐 | pr-batch 값을 그대로 넘기고 우리 계산 제거(백엔드 변경, 승인 후) | 우리 |
| R7 | local은 dev SSO 어댑터라 실제 idp를 거치지 않음 | A2·A10·H4는 dev 전에 검증 불가 | dev 첫날 A 영역부터 | 우리 |
| R8 | executor 10/21 점검의 E2·E3(handover 후 projection·완료 이벤트, 배치 대상 반환 뒤 리포트 저장) 현재 상태 모름 | D4 실패 시 1순위 원인 후보 | executor에 확인 요청 | executor |
| R9 | 맥 로컬 저장소 루트에 git에 없는 `인증가이드.md`가 있고, 예전 pr-auth 토큰 설계를 설명함 | 테스트 참여자 혼동 | 삭제하거나 "폐기됨" 표시 | 사용자 |

**정해야 할 것**

- [ ] 환경별 테스트 일정, 담당자, DB·Redis·PV 리셋을 누가 실행할지
- [ ] stg가 내부망 gaia 환경인지 (아니면 H 영역을 어디서 할지)
- [ ] R2·R3·R6 우리 코드 수정 진행 여부
- [ ] 외부 tenant 테스트 이름 `it-ext`를 쓸지, 실제 상위 에이전트 tenant로 할지

## 다른 팀 요청 (복사용)

아래는 그대로 전달할 수 있는 문구입니다. 11/01 요청(헤더 모드 삭제 후 키 설정, DB 리셋)에 통합테스트에 필요한 것을 더했습니다.

**executor 담당께**

1. 환경별(dev, stg) `scripts/generate_api_keys.py`로 `pr-agentic-service`·`pr-batch`·`ops` 키를 만들어 `AUTH_CLIENTS`의 0000… 해시를 교체하고, 키 원문은 우리와 pr-batch에 전달해 주세요. 로컬 compose의 로컬 키는 지금 값 그대로 유지해 주세요.
2. 환경마다 통합테스트 시작 전에 executor DB, 공유 PV `tenants/*/users/*`, Redis `executor.events.*` 스트림을 우리·pr-batch와 같은 시간에 비워 주세요.
3. 10/21 요청의 두 가지 현재 상태를 알려 주세요. handover가 일어난 SINGLE 실행에서도 노트북 projection `SUCCEEDED`와 `execution.completed`의 `execution{trigger, context}`가 나오는지, 배치 Jupyter 대상이 풀로 돌아간 뒤에도 `POST /executions/{id}/artifacts`(REPORT, `append_to_notebook`)가 되는지입니다.
4. 테스트 중 G1(executor 중지)과 G9(부하)를 할 때 런타임 수와 로그를 함께 봐 주세요.

**pr-batch 담당께**

1. (로컬 차단) `compose.yaml`의 `x-batch-env`에 `EXECUTOR_API_KEY: ${PR_BATCH_EXECUTOR_API_KEY:-exe_local_batch_0123456789abcdef0123456789ab}`를 넣어 주세요. executor가 로컬에서도 키를 요구해서, 지금은 로컬 배치 실행이 모두 실패합니다. 키 값은 executor `docker-compose.yml` 주석에 있는 것과 같습니다.
2. dev·stg `config.{env}.yml`의 `EXECUTOR_API_KEY: REPLACE_EXECUTOR_KEY`를 executor에서 받은 키로, `AUTH_CLIENTS`의 `pr-agentic-service` 해시를 우리 `BATCH_API_KEY`의 SHA-256으로 바꿔 주세요(`admin: true`, `allowed_tenants: ["*"]` 유지).
3. 환경마다 통합테스트 전에 pr-batch DB를 같은 시간에 비워 주세요.
4. E1·E2(tenant 폐기)와 E3(사용자 비활성화)에서 `disabled_reason`이 `TENANT_REVOKED`·`USER_DEACTIVATED`로 남는지 같이 봐 주세요. 추가 개발은 없습니다.

**인프라·SSO 담당께** (prj_re SSO 포함)

1. SSO 로그인 페이지 도메인(스킴 + 호스트, `SSO_ALLOWED_ORIGINS`용), 초기 관리자 사번 목록(SSO가 주는 표기 그대로), 내부망 idp 로그인·userinfo 주소와 응답 필드명을 알려 주세요.
2. 테스트 계정 사번 3개(관리자 1, 일반 2)를 준비해 주세요. 하나는 비활성화 테스트에 씁니다.
3. Ingress: 요청 본문 한도 32MB 이상, SSE 경로의 proxy read timeout 연장과 buffering off. PostgreSQL `max_connections`는 우리 Pod당 14 × 최대 4 = 56에 두 서비스를 더한 값 이상.
4. 리셋 때 Redis `executor.events.*` 스트림 삭제와 공유 PV 정리를 도와 주세요.

**gaia 담당께** (internal/gaia)

1. stg(내부망)에서 우리 workflow(`dtest.analyst`)를 부를 수 있는 gaia 화면 또는 API 경로와 테스트 시간을 정해 주세요.
2. gaia가 넘기는 `user_id`가 SSO 사번과 같은 표기(대소문자 포함)인지 알려 주세요. H4 결과가 여기에 달려 있습니다.

**우리(pr-agentic-service) 할 일**

- [ ] R2 compose `BATCH_API_KEY` 기본값 (main·internal/gaia)
- [ ] R3 테스트 스크립트 키 모드
- [ ] R5 F3·F8 반영 여부 확인, 빠졌으면 반영
- [ ] R6 배치 켜기 필드 pass-through (승인 후)
- [ ] 환경별 설정 채우기와 테스트 키 발급(G0 4·9번)

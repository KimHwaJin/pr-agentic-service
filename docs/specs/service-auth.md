# pr-agentic-service 인증 변경 스펙 (최종)

작성일 2026-10-29 · 최종 (pr-batch v5 최종, Executor 최종과 맞춤) · 관련: `pr-batch-auth-spec-final.md`, `executor-auth-spec-final.md`

## 1. 요약

- 호출자 인증은 **API key(`X-Api-Key`) + 신원 헤더**로 한다. 브라우저는 지금처럼 SSO 쿠키만 쓴다.
- **외부 진입점은 pr-agentic-service로 고정한다.** 다른 서비스·에이전트는 executor·pr-batch를 직접 부르지 않는다.
- 우리는 외부 호출자 key를 발급하고, 그 호출자의 tenant를 executor·pr-batch로 넘기는 **중계자**다.
- **하위호환은 두지 않는다.** 세 서비스를 같은 시점에 배포하고, JWT·본문 `context`·`tenant_id`는 바로 제거한다. Executor DB·공유 PV와 pr-batch DB는 초기화된다(9장).

우리가 갖는 key:

| key | 대상 | 우리 쪽 권한 |
| --- | --- | --- |
| `EXECUTOR_API_KEY` (`exe_live_…`) | executor | relay, 기본 tenant `pr-agentic-service` |
| `BATCH_API_KEY` (`bat_live_…`) | pr-batch | relay, admin (`disable-by-owner`) |

## 2. 공통 헤더 규칙 (세 서비스 동일)

| 헤더 | 규칙 |
| --- | --- |
| `X-Api-Key` | stg·prd 필수 |
| `X-User-Id` | 소문자로 바꾼 뒤 `^[a-z0-9][a-z0-9._-]{0,63}$`. 값은 우리 `users.id`(uuid4 소문자 문자열, 그대로 통과) |
| `X-Project-Id` | 선택. `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$`, `unscoped` 금지 |
| `X-Session-Id` | 선택. 있으면 `X-Project-Id` 필수. pr-batch는 무시 |
| `X-Tenant-Id` | relay key만, `allowed_tenants` 안의 값만 |

- 신원 헤더는 **항상 우리가 검증한 값으로 새로 만든다.** 브라우저나 외부 호출자가 보낸 `X-*` 헤더를 넘기지 않는다.
- 상태 코드: key 문제 401, 신원 헤더 문제 400 `INVALID_IDENTITY`, 허용되지 않은 tenant·권한 403, 남의 리소스·없는 리소스 404.

## 3. 받는 쪽 (외부 호출자 입구)

### 3.1 인증 순서 (`src/api_service/deps.py` `current_user`)

1. SSO 쿠키가 있으면 SSO 세션으로만 판정한다. 쿠키가 무효면 401이고 key 경로로 넘어가지 않는다. CSRF 검사는 이 경로에만 적용한다.
2. 쿠키가 없고 `X-Api-Key`가 있으면 등록된 호출자인지 확인한다. 모르거나 폐기된 key는 401.
3. `X-User-Id`를 2장 규칙으로 검사한다(없거나 형식 오류 400). 우리 DB에 없거나 비활성이면 403. 자동 생성하지 않는다.
4. 둘 다 없으면 401.

### 3.2 권한

- 관리자 API(`AdminDep`)는 key 경로로 부를 수 없다. 403.
- 프로젝트·세션은 경로 값이 기준이다. `X-Project-Id`·`X-Session-Id`가 오면 경로와 같은지만 보고, 다르면 400.
- 멤버십과 세션 소유는 지금처럼 우리 DB로 확인한다(멤버가 아니면 404, 남의 세션 404).
- executor·배치 게이트웨이(3.4)는 project 없이 부를 수 있다. 이때는 활성 사용자만 확인하고 남의 실행은 executor가 404로 막는다.
- SSE는 같은 헤더로 연결하고 연결 시점에만 확인한다. 최대 연결 시간 1시간.

### 3.3 외부 호출자 key 발급

- SSO admin 전용 API·화면. 테이블 `api_clients`: `id`, `name`, `tenant`, `key_prefix`, `key_sha256`, `status`(`pending`·`active`·`revoked`), `created_by`, `created_at`, `revoked_at`, `last_used_at`.
- key는 32바이트 이상 무작위 + 접두어 `pas_live_…`(dev `pas_dev_…`). 원문은 발급 응답에서 한 번만 보여 주고 SHA-256 해시만 저장. 비교는 `hmac.compare_digest`.
- `tenant`는 관리자가 정한다. executor `TENANT_ID_PATTERN`, 예약어 `dlq`·`work`. 비우면 `pr-agentic-service`.
- 새 외부 tenant는 **executor와 pr-batch의 `allowed_tenants`에 추가·재배포된 뒤** `active`로 바꾼다. 그 전에는 `pending`(이 상태의 key는 401).
- 폐기는 `revoked`로 즉시 반영(검증 캐시 최대 60초). key 경로 요청은 감사 로그에 client, user_id, 메서드, 경로, 결과 코드를 남긴다.

### 3.4 게이트웨이

| 경로 | 대상 | 규칙 |
| --- | --- | --- |
| `/api/v1/batch/{path}` (기존 `batch_gateway`) | pr-batch | `with_tenant`(본문 `tenant_id` 주입) 제거. pr-batch는 본문 `tenant_id`를 422로 거부함 |
| `/api/v1/executor/{path}` (신규, 필수) | executor | 3.5 참고 |

- 호출자의 tenant를 `X-Tenant-Id`로 붙인다. SSO 사용자는 `pr-agentic-service`.
- pr-batch에는 **배치 등록(`POST /batches`) 때만** `X-Tenant-Id`를 보낸다. pr-batch는 PATCH에서 명시된 tenant가 저장값과 다르면 403이므로, 다른 tenant로 등록된 배치를 우리 화면에서 고칠 때 막히지 않게 하기 위해서다.
- `X-Project-Id`는 배치 등록 때만 의미가 있다. pr-batch는 project를 바꿀 수 없으므로 우리 화면에서도 배치의 프로젝트 이동은 "새 배치 만들기"로 안내한다.

### 3.5 executor 게이트웨이 상세 (필수 범위)

외부 진입점을 우리로 고정했으므로, 외부 호출자가 executor를 쓰는 유일한 길이다. 이번 범위에 반드시 포함한다.

**호출 방식**

- 경로: `/api/v1/executor/{path}` → executor `/api/v1/{path}`로 그대로 전달한다. 메서드·쿼리·본문·응답(상태 코드, 본문, `Content-Type`, 스트리밍 응답)을 바꾸지 않는다.
- 인증: **key 경로만** 받는다. SSO 쿠키 요청은 403(우리 화면은 내부 `ExecutorClient`를 쓴다).
- 우리가 붙이는 헤더: `X-Api-Key: EXECUTOR_API_KEY`, `X-User-Id`(검증한 값), `X-Tenant-Id`(호출자 tenant). 호출자가 보낸 `X-Api-Key`·`X-Tenant-Id`·`Authorization`·`Cookie`는 버린다.
- `X-Project-Id`·`X-Session-Id`
  - 호출자 tenant가 `pr-agentic-service`이면 우리 프로젝트·세션이므로 멤버십·소유를 우리 DB로 확인한다(아니면 404).
  - 외부 tenant이면 **그 호출자가 정한 값**으로 보고 확인 없이 형식(2장)만 검사해 넘긴다. executor 작업 공간이 `tenants/{tenant}/…` 아래라 우리 프로젝트와 섞이지 않는다.
- 본문은 그대로 넘긴다. `context`·`tenant_id`가 들어 있으면 executor가 422로 거부한다. 멱등키(`idempotency_key`)도 호출자 값 그대로다.
- `X-User-Id` 없는 GET(시스템 조회)은 허용한다. executor가 호출자 tenant의 실행만 보여 준다. `X-User-Id` 없는 쓰기는 executor가 400으로 거부한다.
- 타임아웃은 `EXECUTOR_TIMEOUT`을 따르고, executor 연결 실패는 502, 타임아웃은 504로 돌려준다.

**허용 경로** (그 외는 우리가 404)

| 메서드 | executor 경로 |
| --- | --- |
| POST | `/executions` |
| GET | `/executions` |
| GET | `/executions/{id}`, `/executions/{id}/result` |
| POST | `/executions/{id}/operations`, `/finalize`, `/cancel`, `/retry` |
| GET | `/executions/{id}/operations`, `/operations/{op}`, `/operations/{op}/result`, `/operations/{op}/steps` |
| GET | `/executions/{id}/steps`, `/steps/{step}` |
| GET | `/executions/{id}/attempts`, `/attempts/{a}`, `/attempts/{a}/steps` |
| GET | `/executions/{id}/events` |
| GET | `/executions/{id}/notebook`, `/notebook/cells/{n}` |
| GET·POST | `/executions/{id}/artifacts` |
| GET | `/artifacts/{artifact_id}`, `/artifacts/{artifact_id}/content` |

**막는 경로**: `/runtime-pools`, `/runtime-targets*`, `/maintenance*`(admin 전용 운영 API), `/executions/{id}/diagnostics`(내부 진단 정보).

**이벤트**: 게이트웨이는 이벤트를 중계하지 않는다. 외부 호출자는 `executor.events.<tenant>`를 직접 읽거나 `GET /executions/{id}`·`/events`로 폴링한다.

**감사 로그**: 쓰기 요청마다 client, tenant, user_id, 메서드, executor 경로, `execution_id`, 결과 코드.

**테스트**

- 허용 경로는 executor 응답이 그대로 오고, 막는 경로·목록에 없는 경로는 404.
- 호출자가 보낸 `X-Tenant-Id`·`X-Api-Key`는 무시되고 호출자 tenant·우리 key로 바뀐다.
- 외부 tenant의 `X-Project-Id`는 확인 없이 전달, `pr-agentic-service` tenant의 남의 프로젝트는 404.
- SSO 쿠키 요청 403. 아티팩트 content 다운로드가 스트리밍으로 전달된다.

## 4. 호출하는 쪽

### 4.1 공통 헤더 모듈

pr-batch·executor 호출의 헤더를 한 곳(`src/core/service_headers.py` 가칭)에서 만든다.

```python
identity_headers(
    api_key, user_id=None, project_id=None, session_id=None, tenant_id=None
)
```

### 4.2 pr-batch 호출 (`src/api_service/routers/batch.py`)

- 제거: `_batch_token()`, `_private_key()`, `Authorization: Bearer`, `sets_tenant`/`with_tenant`, 설정 `BATCH_JWT_*`, `keys/`, Dockerfile `COPY keys`.
- 추가: `X-Api-Key: BATCH_API_KEY`, `X-User-Id`, (등록 때) `X-Project-Id`·`X-Tenant-Id`.
- `GET /runtimes`는 key만으로 부른다(pr-batch가 자기 설정 `BATCH_RUNTIMES`로 응답).

### 4.3 executor 호출 (`src/core/executor/client.py`)

- 모든 메서드가 신원(`Identity(user_id, project_id, session_id, tenant)` 또는 시스템 호출)을 받는다. 본문 `context`·`tenant_id`(제출)와 조회 파라미터 `user_id`·`tenant_id`를 **지운다**. executor는 이 필드를 422로 거부한다.
- 사용자 호출: 에이전트 도구(`agent/tools/analysis.py`, `agent/tools/batch.py`), `agent/reporter.py`, `api_service/services/access.py`, 누락 이벤트 복구(`worker/executor_events.py` `MissedEventRecovery`)는 run·세션의 사용자로 부른다.
- 시스템 호출(`X-User-Id` 없음, GET만, 실효 tenant 범위):
  - 배치 리포트 누락 복구 `worker/batch_reports.py` `_recover`: `executions(tenant_id=…)` 필터를 빼고 `trigger_type`·`status`만 보낸다. 범위는 key의 tenant가 정한다.
  - 배치 리포트 처리 시 실행 재조회(5장).

### 4.4 사용자 비활성화

관리자가 사용자를 비활성화하면 pr-batch를 부른다. 실패하면 재시도 큐에 넣는다(멱등).

```
POST /batches:disable-by-owner
X-Api-Key: BATCH_API_KEY
{"owner_id": "<users.id>", "reason": "USER_DEACTIVATED"}
```

다시 활성화해도 배치는 되살리지 않는다(owner가 직접 켬). 우리 화면은 `disabled_reason=USER_DEACTIVATED`를 표시하고, 그 배치의 수동 실행 409(`OWNER_DEACTIVATED`)를 안내 문구로 바꾼다.

## 5. 이벤트 소비

Redis ACL은 쓰지 않는다(운영 Redis에서 불가). 그래서 **이벤트는 위조될 수 있다고 보고 알림으로만 쓴다.**

- 우리 tenant 스트림 `executor.events.pr-agentic-service`만 읽는다. 공유 스트림 `executor.events`는 없어지므로 구독하지 않는다.
- 대화형 실행: `execution_id`로 우리 `runs`를 찾고, 없으면 경고 로그 후 버린다. 있으면 executor API로 상태·결과를 다시 읽어 재개 값으로 쓴다(payload를 재개 값으로 쓰지 않음).
- **배치 실행**: pr-batch가 제출한 실행이라 우리 DB에 없다. "DB에 없으면 버림" 규칙을 그대로 적용하면 리포트가 하나도 안 만들어지므로, 이 경우만 **executor 시스템 조회 `GET /executions/{id}`로 확인**한다. 우리 key의 tenant로 범위가 좁혀지므로 404가 아니면 우리 tenant의 실행이다. trigger가 `BATCH`이고 상태가 `SUCCEEDED`일 때만, 그 응답의 `context`로 owner를 정해 리포트 작업을 만든다.

## 6. 남는 위험과 우리 쪽 조치

| 위험 | 조치 |
| --- | --- |
| 우리 SSO 세션 위조. executor와 같은 Redis를 쓰는 사람은 우리 세션 키(`<namespace>:auth:*`)를 직접 쓸 수 있다 | **알고 가는 위험으로 둔다**(2026-10-29 결정). Redis는 지금처럼 하나의 `REDIS_URL`을 쓴다 |
| 이벤트 위조 | 5장대로 알림으로만 쓰고 executor API로 확정 |
| JupyterLab | 현행 유지(범위 밖). 노트북 링크(`notebook_links.py`)도 그대로 |
| key가 든 레포 = 권한 | 레포 접근 권한을 필요한 사람으로 좁힌다 |

## 7. 설정과 기동 검사

```yaml
AUTH_MODE: api_key          # api_key | header
BATCH_API_KEY: "bat_live_…"
EXECUTOR_API_KEY: "exe_live_…"
REDIS_URL: "redis://…"              # 지금과 같음 (세션·큐·executor 이벤트)
```

- `AUTH_MODE: header`는 `APP_ENV`가 명시적으로 `local`·`dev`일 때만. `APP_ENV`가 비었거나 stg·prd면 기동 거부.
- stg·prd에서 `BATCH_API_KEY`·`EXECUTOR_API_KEY`가 비면 기동 거부.
- 로그 마스킹: `X-Api-Key`, `pas_*`·`exe_*`·`bat_*` 패턴을 접근·오류·httpx 로그에서 지운다.

## 8. 테스트

- pr-batch·executor 호출에 key와 헤더가 붙고, 본문에 `context`·`tenant_id`가 없다. 조회에 `user_id`·`tenant_id` 파라미터가 없다.
- 브라우저·외부 호출자가 보낸 `X-*` 헤더가 그대로 전달되지 않는다.
- key 경로: 모르는 key 401, `pending`·`revoked` key 401, `X-User-Id` 없음·형식 오류 400, 미등록·비활성 사용자 403, 관리자 API 403, 경로와 다른 `X-Project-Id` 400, 멤버가 아닌 프로젝트 404.
- 쿠키 경로는 기존과 같고, 쿠키와 key가 함께 오면 쿠키로 판정한다.
- 게이트웨이: 외부 호출자는 그 tenant로, SSO 사용자는 `pr-agentic-service`로 넘어간다. pr-batch PATCH에는 `X-Tenant-Id`가 없다. executor 운영 경로는 404.
- 이벤트: DB에 없는 대화형 `execution_id`는 버린다. 배치 이벤트는 executor 재조회로 확인한 경우에만 리포트를 만들고, payload의 `context`를 위조해도 owner는 재조회 값이다.
- 사용자 비활성화 시 `disable-by-owner`가 호출되고, 실패하면 재시도한다.
- 기동: `APP_ENV` 비어 있음 + `AUTH_MODE: header`면 실패.

## 9. 배포

세 서비스를 같은 시점에 배포한다. 배포 사이의 호출 실패는 허용한다.

- 개발 단계라 하위호환·데이터 이관은 하지 않는다. Executor DB·공유 PV, pr-batch DB가 초기화되므로 우리 DB도 필요하면 같이 초기화한다(이전 실행을 가리키는 run·리포트·링크는 정리하지 않음).
- 배포 전 확인: 세 서비스 `AUTH_CLIENTS`에 서로의 key 해시, executor·pr-batch의 `allowed_tenants` 일치.

## 10. 작업량

| 작업 | 규모 |
| --- | --- |
| 공통 헤더, pr-batch 전환, JWT·`with_tenant` 제거, `disable-by-owner` | 1.5일 |
| ExecutorClient 신원 전달, 본문·파라미터 제거, 시스템 호출 | 1.5~2일 |
| 이벤트 소비(재조회, 배치 확인) | 0.5일 |
| key 입구, `api_clients`, 발급 API, 감사 로그 | 2일 |
| executor 게이트웨이 (필수, 3.5) | 2~3일 |
| 테스트·설정 | 1일 |
| **합계** | **약 8.5~10일** |

개발 단계라 하위호환·이관·데이터 정리 작업은 없다.

## 11. 구현 메모 (2026-10-29)

스펙과 다르게 또는 더 구체적으로 정한 부분입니다.

- **tenant 값**: 우리 tenant는 설정 `EXECUTOR_TENANT_ID`(기본 `pr-agentic`)입니다. 이 문서의 `pr-agentic-service`는 그 값을 가리킵니다.
- **executor 게이트웨이와 브라우저**: `/api/v1/executor/{path}`는 key 호출자의 입구이면서, 기존처럼 브라우저(SSO)의 조회 중계도 계속 맡습니다(실행 이력·시스템 화면). 쿠키 요청은 403이 아니라 기존 규칙(멤버십 확인 후 시스템 조회, 관리자 경로)으로 처리합니다. 쓰기와 `/artifacts/*`는 key 호출자만 씁니다.
- **runtime·maintenance**: executor의 admin 전용 API라 운영 key `EXECUTOR_ADMIN_API_KEY`로 부릅니다. `EXECUTOR_API_KEY`는 있는데 운영 key가 비어 있으면 시스템 화면의 그 탭은 503 `executor_admin_key_missing`입니다. 둘 다 비어 있으면(로컬 header 모드 executor) key 없이 부릅니다.
- **tenant 헤더**: 우리 executor 호출은 모두 `X-Tenant-Id: EXECUTOR_TENANT_ID`를 붙입니다(운영 API 제외). header 모드 executor는 key가 없으면 tenant를 `dev`로 잡기 때문입니다. 그래서 우리 relay key의 `allowed_tenants`에 우리 tenant가 있어야 합니다.
- **관리자 실행 목록의 사용자 필터**: executor가 `user_id` 파라미터를 받지 않으므로 그 값을 `X-User-Id`로 바꿔 보냅니다.
- **비활성화 재시도**: 사용자 비활성화 때 바로 `disable-by-owner`를 부르고, 실패하면 `users.batches_disable_pending`이 남아 워커가 5분마다 다시 부릅니다.
- **key 발급 상태**: 우리 tenant 키는 바로 `active`, 다른 tenant 키는 `pending`으로 만들어 관리자가 활성화합니다. 접두어는 `pas_live_`(stg·prd)·`pas_dev_`(local·dev).
- **이벤트 확인**: wake 이벤트(`operation_completed`, `completed`)는 executor 타임라인에서 같은 `event_id`를 찾아 그 값으로 씁니다. 못 찾으면 버립니다. 배치 리포트는 `GET /executions/{id}`(시스템 조회)로 상태·trigger·owner를 정합니다.

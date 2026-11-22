# 운영자 가이드

기준: internal/gaia 브랜치, 2026-11-22. 경로는 내부망 레포 기준(`src/dtest/...`)입니다.

"확인 필요"라고 적힌 곳은 저장소에 기록이 없어 실제 운영 환경 값을 채워야 하는 자리입니다.

## 1. 서비스 구성

### 1.1 무엇이 어디에 연결되나

pr-agentic-service는 사내 데이터 분석 Agent의 채팅 API이자 Agent 실행 서비스입니다. Pod 하나가 컨테이너 하나, 프로세스 하나(uvicorn worker 1개)이고, 그 안에서 API와 백그라운드 작업(worker)이 함께 돕니다.

| 연결 대상 | 방향 | 용도 | 끊기면 |
| --- | --- | --- | --- |
| 브라우저(프론트) | 들어옴 | 채팅 API, SSE 실시간 이벤트 | |
| 다른 서비스, 에이전트 | 들어옴 | API 키로 executor·배치 게이트웨이 호출 | |
| gaia 채팅 화면 | 들어옴 | gaia workflow `dtest.analyst` | |
| SSO(IdP) | 나감 | 로그인 확인 | 새 로그인 불가. 이미 로그인한 사용자는 계속 사용 |
| PostgreSQL | 나감 | 앱 데이터, LangGraph 체크포인트 | 모든 요청 실패. run 실행 중단 |
| Redis | 나감 | 로그인 세션, 실시간 이벤트, executor 이벤트 수신 | 로그인 확인 실패로 모든 요청 실패 |
| LLM 게이트웨이 | 나감 | 모델 호출 | run이 `failed`로 끝남. 그 외 화면은 정상 |
| 임베딩 게이트웨이 | 나감 | 워크플로우 검색 | 워크플로우 추천만 안 됨 |
| executor | 나감 | 분석 코드 실행, 노트북, 결과물 | 분석 요청 실패, 결과물 조회 502. 일반 대화는 정상 |
| pr-batch | 나감 | 배치 등록과 조회 중계 | 배치 화면만 502 |
| 공유 저장소(PV) | 마운트 | executor와 코드·결과 파일 주고받기 | 분석 코드 제출과 결과 읽기 실패 |
| Phoenix | 나감 | 실행 추적(선택) | 영향 없음 |

### 1.2 환경

| 환경 | `APP_ENV` | 설정 파일 | Redis | SSO |
| --- | --- | --- | --- | --- |
| 로컬 | 비움 | `config.yml` + 환경변수 | standalone | dev 어댑터(가짜 로그인) 가능 |
| dev | `dev` | `config.yml` + `config.dev.yml` | standalone | idp |
| stg | `stg` | `config.yml` + `config.stg.yml` | standalone | idp |
| prd | `prd` | `config.yml` + `config.prd.yml` | sentinel | idp |

확인 필요: 환경별 클러스터, 네임스페이스, 접속 주소, 실제 Pod 수, 연결된 executor·pr-batch·DB·Redis 주소. 사외 검증용으로는 frodo 클러스터의 `mcp-server` 네임스페이스에 배포한 적이 있습니다(2026-11-08, `APP_ENV` 없이 로컬 모드).

### 1.3 Pod 사양 (`deploy/kubernetes/deployment.yml`)

| 항목 | 값 |
| --- | --- |
| 레플리카 | 2 (HPA: CPU 60% 기준, 최소 2, 최대 4) |
| 자원 | 요청 CPU 0.5, 메모리 1Gi. 한도 CPU 2, 메모리 2Gi |
| 포트 | 8080 (Service는 80 → 8080) |
| readiness | `GET /api/admin/appReady` (gaia 제공, 5초 간격) |
| liveness | `GET /api/v1/healthz` (15초 간격, 4번 실패 시 재시작) |
| 종료 | preStop `sleep 5`, `terminationGracePeriodSeconds` 60 |
| 실행 계정 | UID 1000, GID 1000 (executor 이미지와 같아야 공유 저장소를 같이 읽고 씀) |
| 볼륨 | `executor-shared-pvc`를 `/mnt/data`에 마운트 (RWX) |
| 실행 명령 | `python app.py` (gaia 템플릿이 uvicorn worker 1개를 띄움) |

## 2. 배포

### 2.1 설정 읽는 순서

우선순위는 환경변수 > `.env` > `config.{APP_ENV}.yml` > `config.yml`입니다.

- `config.yml`: 모든 환경 공통값. 모든 설정 키가 기본값과 함께 적혀 있습니다.
- `config.{APP_ENV}.yml`: 환경마다 다른 값만 있습니다. `DATABASE_URL`, `REDIS_*`, `PUBLIC_API_ORIGIN`, `FRONTEND_ORIGIN`, `CORS_ORIGINS`, `COOKIE_SECURE`, `ADMIN_EMPLOYEE_IDS`, `LLM_API_KEY`, `MODELS`, `EXECUTOR_BASE_URL`, `BATCH_BASE_URL`, 서비스 키.
- `config.example.yml`: 서비스가 읽지 않는 설명용 파일. 모든 키의 의미와 예시가 주석으로 있습니다. 설정 키의 뜻을 찾을 때 이 파일을 봅니다.
- 네 파일은 모두 이미지에 들어가고(`COPY config*.yml`), Deployment의 `env`에 있는 `APP_ENV` 값이 어느 파일을 쓸지 정합니다.
- 내부망은 ConfigMap과 Secret을 쓸 수 없어 키 값도 `config.{APP_ENV}.yml`에 적는 것이 사내 가이드입니다. 한 값만 바꿀 때는 Deployment `env`에 같은 이름으로 넣으면 파일보다 우선합니다.

확인 필요: 운영 키 값을 실제로 어디에 두는지(설정 파일, Deployment env, 그 밖의 방법).

### 2.2 이미지 빌드

```
docker build --build-arg BASE_IMAGE=<사내 uv + Python 3.11 이미지> --build-arg APP_ENV=prd .
```

- 내부망 이미지는 Python 3.11입니다. 3.12 전용 문법이 들어가면 빌드는 되지만 실행에서 깨집니다.
- `pyproject.toml`에는 HCP 라이브러리와 gaia 기본 의존성이 들어 있어야 합니다. FastAPI는 0.137 미만으로 묶여 있습니다. 0.137부터는 gaia의 prometheus 계측기가 요청마다 `AttributeError`를 냅니다.
- `langgraph-checkpoint-postgres`는 3.1.3으로 고정되어 있습니다. 올리면 체크포인트 저장이 한 줄로 서는 문제가 돌아올 수 있고, 그때는 `tests/test_checkpoint_saver.py`가 실패합니다.

### 2.3 배포 순서

1. 테스트를 돌립니다. `uv run pytest`
2. 새 마이그레이션이 있으면 먼저 적용합니다. 운영은 `AUTO_MIGRATE: false`로 두고, 같은 이미지와 같은 설정으로 `python scripts/migrate.py`를 한 번 실행합니다. 실패하면 0이 아닌 코드로 끝나고 기존 Pod는 그대로 서비스합니다.
3. Pod를 롤아웃합니다.
4. 기동 로그와 헬스체크를 확인합니다(2.5절).

dev와 stg는 `AUTO_MIGRATE: true`로 두어도 됩니다. 이때는 Pod가 시작하면서 마이그레이션을 실행하고, 여러 Pod가 동시에 떠도 한 Pod만 실행합니다.

확인 필요: 실제 배포 파이프라인 도구, 이미지 레지스트리, 내부망 반입 절차.

### 2.4 기동을 거부하는 조건

설정이 잘못되면 Pod가 시작하지 않고 로그에 `ValueError`와 이유를 남깁니다. 일부러 넣은 검사입니다.

| 조건 | 메시지 요지 |
| --- | --- |
| `APP_ENV`가 있는데 `config.{APP_ENV}.yml`이 없음 | `APP_ENV=... needs ...` |
| k8s Pod인데 `APP_ENV`가 비어 있음 | `APP_ENV is not set for this pod` |
| dev·stg·prd에서 `SSO_ADAPTER=dev` | `SSO_ADAPTER=dev is only allowed locally` |
| stg·prd에서 `COOKIE_SECURE`가 false | `COOKIE_SECURE must be true` |
| dev·stg·prd에서 `EXECUTOR_API_KEY`나 `BATCH_API_KEY`가 비어 있음 | `EXECUTOR_API_KEY and BATCH_API_KEY are required` |
| 설정 어디든 `<...>` 모양의 템플릿 값이 남아 있음 | `config values still hold a template placeholder: 키 이름` |
| `SSO_ADAPTER=idp`인데 `SSO_ALLOWED_ORIGINS`가 비어 있음 | `SSO_ALLOWED_ORIGINS is empty` |
| `REDIS_MODE=sentinel`인데 Sentinel 값이 비어 있음 | `REDIS_MODE=sentinel needs ...` |
| `REDIS_MODE=sentinel`인데 사내 `hcp` 라이브러리가 없음 | 비밀번호 복호화 실패 |
| stg·prd에서 `EXECUTOR_IO_MODE=api` | `EXECUTOR_IO_MODE=api is for test environments` |
| `MODELS`에 `default: true`가 정확히 하나가 아님, 이름 중복 | `models: ...` |
| `EMBEDDING_PROVIDER=openai`인데 주소나 모델이 비어 있음 | `EMBEDDING_PROVIDER=openai needs ...` |

`ADMIN_EMPLOYEE_IDS`가 비어 있으면 기동은 되지만 `admin_employee_ids_empty` 경고가 남고, 첫 로그인으로 관리자가 되는 사람이 없습니다.

### 2.5 배포 후 확인

1. `GET /api/admin/appReady`가 200인지. 우리 쪽 준비(DB, Redis, worker 시작)가 끝나야 포트가 열리므로, 응답이 온다는 것은 시작이 끝났다는 뜻입니다.
2. `GET /api/v1/healthz`가 `{"status": "ok"}`인지.
3. 기동 로그에 `gaia_auth_skipped_on_own_paths`가 있는지. 없으면 우리 경로에 gaia 접근 키 검사가 걸려 브라우저 요청이 401 `Access key is required`로 막힙니다.
4. 브라우저로 로그인해 `GET /api/v1/users/me`가 200인지.
5. 간단한 대화 한 턴과 분석 한 건을 실행해 답과 리포트가 오는지.

### 2.6 롤백

이전 이미지로 되돌리면 됩니다. 마이그레이션은 이전 버전 코드가 계속 동작하도록(컬럼과 인덱스 추가만) 작성하므로 스키마는 되돌리지 않습니다.

### 2.7 종료 동작

Pod가 내려갈 때 순서는 다음과 같고 합계 45~50초입니다. 그래서 `terminationGracePeriodSeconds`는 60입니다.

1. preStop 5초. Service가 이 Pod로 요청을 그만 보낼 시간입니다.
2. uvicorn이 열린 연결을 최대 20초 기다립니다. SSE 연결이 있으면 끝까지 기다립니다.
3. worker가 새 run을 받지 않고, 진행 중인 턴과 메모리 작업을 최대 20초 동안 마무리합니다.
4. 끝나지 않은 run은 lease를 반납해 `queued`로 돌리고, 다른 Pod가 체크포인트에서 이어 갑니다.

진행 중이던 턴은 잃지 않습니다. 다만 이어 가는 Pod가 마지막 체크포인트 이후의 LLM 호출을 다시 하므로 그만큼 시간이 더 걸립니다.

## 3. 일상 운영

### 3.1 관리자 지정과 역할 변경

- 첫 관리자는 `ADMIN_EMPLOYEE_IDS`에 사번을 넣어 둡니다. 그 사번이 처음 로그인할 때 `admin`이 됩니다. 이 설정은 첫 로그인 때만 쓰이므로 나중에 바꾼 역할을 덮어쓰지 않습니다.
- 평소에는 관리자 화면 또는 `PATCH /api/v1/admin/users/{user_id}`에 `{"role": "admin"}` 또는 `{"role": "user"}`로 바꿉니다.
- 관리자가 아무도 없으면 스크립트를 씁니다.

```
python scripts/set_user_role.py --env prd --list                 # 관리자 목록
python scripts/set_user_role.py --env prd A10054 admin --dry-run # 확인만
python scripts/set_user_role.py --env prd A10054 admin           # 승격 (강등은 user)
```

스크립트는 접속할 DB를 먼저 출력합니다. 대상은 사번 또는 `users.id`이고 정확히 한 명일 때만 바꿉니다. 마지막 활성 관리자는 강등하지 않습니다. psql로 직접 하려면 `scripts/set_user_role.sql`을 씁니다. `role` 컬럼에는 DB 제약이 없으므로 `user`, `admin` 외의 값을 넣지 않습니다.

### 3.2 사용자 비활성화

관리자 화면에서 비활성화하면 그 사용자의 진행 중인 턴과 executor 커널이 바로 취소되고, 그 사용자의 배치는 pr-batch에서 꺼집니다. pr-batch가 응답하지 않으면 성공할 때까지 worker가 다시 시도합니다(`batch_disable_failed` 경고).

### 3.3 API 키

다른 서비스와 에이전트는 우리가 발급한 `X-Api-Key`와 `X-User-Id` 헤더로 호출합니다. executor와 pr-batch는 우리 서비스를 거쳐서만 부를 수 있습니다(`/api/v1/executor/...`, `/api/v1/batch/...`).

| 구분 | 값 | 뜻 |
| --- | --- | --- |
| tenant | 우리 tenant + `own_tenant: true` | 우리 사용자로 executor·배치를 부름. 우리 팀이 운영하는 서버 간 연동에만 발급 |
| tenant | 다른 tenant 이름 | 그 tenant 범위만 읽고 씀. 다른 팀 서비스용 |
| kind | `standard` (기본) | 조회가 `X-User-Id` 사용자 것만 |
| kind | `master` | 조회가 tenant 전체. 사실상 관리자 읽기 권한 |

| 작업 | 방법 |
| --- | --- |
| 발급 | 시스템 화면 "API 키" 또는 `POST /api/v1/admin/api-clients`. 발급 즉시 사용 가능 |
| 목록 | `GET /api/v1/admin/api-clients` |
| 재발급 | `POST /api/v1/admin/api-clients/{id}/reissue`. 이전 키는 그 순간 끊김 |
| 폐기 | `/revoke` |
| tenant 전체 폐기 | `POST /api/v1/admin/api-clients/tenants/{tenant}/revoke` |

지킬 것은 다음과 같습니다.

- 키 원문은 발급 응답에서 한 번만 보입니다. DB에는 SHA-256만 남아 다시 보여 줄 수 없습니다. 잃어버리면 재발급합니다.
- 마스터키는 `description`에 용도와 담당자를 적고, 분기마다 목록을 보고 쓰지 않는 키를 폐기합니다. `last_used_at`으로 마지막 사용 시각을 봅니다.
- 다른 tenant에 키를 줄 때는 `X-User-Id`로 SSO 사번을 보내기로 약속받습니다. 시스템 호출은 `svc-`로 시작하는 값을 씁니다. 사번 형식이 정해지면 `EMPLOYEE_ID_PATTERN`에 넣어 강제합니다.
- 새 tenant를 위해 executor나 pr-batch 설정을 바꿀 필요는 없습니다. 두 서비스는 우리 키에 모든 tenant를 허용합니다.

### 3.4 우리가 쓰는 키 교체 (`EXECUTOR_API_KEY`, `BATCH_API_KEY`)

이 두 키는 executor와 pr-batch에서 모든 tenant로 행세할 수 있는 키입니다. 교체는 끊김이 없도록 아래 순서로 합니다.

1. 상대 서비스(executor 또는 pr-batch)의 `key_sha256` 목록에 새 키의 해시를 추가해 배포합니다.
2. 우리 설정의 키를 새 값으로 바꿔 배포합니다.
3. 상대 서비스에서 옛 해시를 지웁니다.

`EXECUTOR_ADMIN_API_KEY`는 시스템 화면의 런타임·유지보수 기능에만 쓰는 운영 키입니다. 비워 두면 그 화면만 503이 됩니다.

### 3.5 모델 목록 변경

`config.{APP_ENV}.yml`의 `MODELS`를 고쳐 배포합니다. 목록에 적힌 모델만 쓸 수 있고 `default: true`는 정확히 하나여야 합니다. 목록에서 뺀 모델로 기다리던 run은 이어 갈 때 기본 모델로 바뀌어 끝납니다(`run_model_replaced` 경고).

### 3.6 skill, tool, 프롬프트 반영

`src/dtest/assets/`의 skill(`.md`), tool(`.py`), knowledge(`.md`)와 `src/dtest/agent/prompts/`는 이미지에 들어 있습니다. 바꾸려면 이미지를 다시 빌드해 배포합니다. 실행 중에는 5초 간격으로 파일 변경을 확인하므로, 볼륨으로 마운트한 환경에서는 파일만 바꿔도 다음 run부터 반영됩니다. 깨진 tool 파일은 그 파일만 건너뛰고 `tool_load_failed` 경고를 남깁니다.

### 3.7 API 문서

`/docs`, `/redoc`, `/openapi.json`은 내부망 규정에 따라 모든 서버 환경에서 꺼 둡니다(`DOCS_ENABLED: false`). 이 값이 false이면 gaia 템플릿의 문서 경로도 함께 내려갑니다.

## 4. 운영 시 주의할 점

한 항목씩 "무엇이 문제인가, 어떻게 드러나는가, 어떻게 피하는가" 순서입니다. 앞쪽일수록 실제로 겪었거나 영향이 큰 것입니다.

### 4.1 Redis는 executor와 같은 서버, 같은 DB 번호여야 한다

- 문제: executor는 실행 이벤트를 Redis 스트림(`executor.events.{tenant}`)에 씁니다. 우리가 다른 Redis나 다른 DB 번호를 보면 이벤트가 하나도 오지 않습니다.
- 증상: 오류가 전혀 없습니다. 분석이 executor에서는 끝났는데 화면은 계속 실행 중으로 보이고, 2분 뒤에야 복구 절차가 결과를 가져와 진행됩니다. 모든 분석이 단계마다 2분씩 느려집니다. 로그에 `executor_event_recovered`가 계속 찍힙니다.
- 예방: `REDIS_URL`(또는 `REDIS_SENTINEL_*`)을 executor의 같은 이름 설정과 똑같이 맞춥니다. Sentinel 모드는 DB 0번을 씁니다.

### 4.2 Sentinel 구성의 노드를 `REDIS_URL`로 직접 가리키지 않는다

- 문제: 우리가 Redis에 보내는 명령(세션 저장, 이벤트 읽기, ACK)은 모두 쓰기입니다. 직접 가리킨 노드가 장애 전환으로 레플리카가 되면 `READONLY` 오류로 멈춥니다.
- 예방: Sentinel이 있는 환경은 반드시 `REDIS_MODE: sentinel`로 둡니다. 이 모드는 새 연결마다 Sentinel에 현재 마스터를 물으므로 장애 전환 때 재시작이 필요 없습니다.
- 참고: `REDIS_SENTINEL_AUTH`는 사내 가이드대로 AES로 암호화한 비밀번호이고 `hcp` 라이브러리로 복호화합니다. 접속 확인은 `scripts/check_redis_sentinel.py`로 합니다.

### 4.3 두 환경이 같은 DB나 같은 Redis를 가리키면 섞인다

- 문제: run은 PostgreSQL 테이블을 큐로 씁니다. dev와 prd가 같은 데이터베이스를 가리키면 dev Pod의 worker가 prd 사용자의 run을 가져가 dev의 코드와 설정으로 실행합니다. 마이그레이션도 한쪽이 올리면 양쪽 스키마가 바뀝니다. Redis도 같습니다. `REDIS_NAMESPACE`(기본 `agentic`)가 같으면 로그인 세션과 실시간 이벤트가 섞이고, executor 이벤트를 두 환경이 나눠 가져갑니다.
- 증상: 한 환경에서 고친 동작이 가끔만 적용됨, 한쪽에서 배포한 뒤 다른 쪽이 컬럼 오류를 냄, 이벤트가 간헐적으로 누락됨.
- 예방: 환경마다 데이터베이스(`DATABASE_URL`의 DB 이름)를 따로 둡니다. Redis를 같이 써야 한다면 `REDIS_NAMESPACE`와 DB 번호를 환경마다 다르게 두되, 그 환경의 executor도 같은 DB 번호를 써야 합니다(4.1절). PostgreSQL 서버만 같이 쓰는 것은 연결 수만 관리하면 됩니다(4.5절).
- 확인 필요: 현재 dev와 prd의 DB·Redis가 실제로 어떻게 나뉘어 있는지.

### 4.4 마이그레이션이 실패하면 모든 Pod가 뜨지 못한다

- 문제: `AUTO_MIGRATE: true`이면 Pod가 시작할 때 마이그레이션을 실행합니다. 실패하면 모든 새 Pod가 CrashLoop에 빠집니다. 롤링 업데이트로 옛 Pod가 이미 내려갔다면 서비스가 멈춥니다.
- 예방: 운영은 `AUTO_MIGRATE: false`로 두고 배포 전에 `python scripts/migrate.py`를 따로 실행합니다(2.3절).

### 4.5 PostgreSQL 연결 수에는 예산이 있다

- 문제: executor, pr-batch와 같은 PostgreSQL 서버를 씁니다. 서버의 `max_connections`는 100이고 세 서비스가 최대로 늘면 84를 씁니다. 우리 Pod 하나는 최대 14(앱 풀 6 + 그래프 풀 8)입니다.
- 증상: 넘으면 `too many connections` 오류가 세 서비스 모두에서 납니다.
- 예방: HPA 최대 Pod 수, `DB_POOL_SIZE`, `CHECKPOINT_POOL_SIZE` 중 하나라도 올리기 전에 합계를 다시 계산합니다. 계산식은 `Pod 수 × (DB_POOL_SIZE × 2 + CHECKPOINT_POOL_SIZE)`입니다. 더 필요하면 `max_connections`를 올리거나 PgBouncer(transaction 모드)를 앞에 둡니다.

### 4.6 Pod와 DB 사이 장비가 조용한 연결을 끊는다

- 문제: 방화벽, LB, NAT 같은 장비가 일정 시간 조용한 TCP 연결을 양쪽에 알리지 않고 끊습니다. 풀에 쉬고 있던 연결이 끊기면 다음 턴이 "server closed the connection unexpectedly"로 실패했습니다.
- 대응(구현됨): 풀이 연결을 빌려줄 때마다 살아 있는지 확인하고, TCP keepalive를 `DB_KEEPALIVE_IDLE_SECONDS`(60초) 간격으로 보냅니다.
- 예방: 이 값을 그 장비의 idle 제한 시간보다 짧게 둡니다. 새 환경으로 옮기면 한참 쉬었다가 첫 요청이 실패하지 않는지 확인합니다.

### 4.7 Pod당 프로세스는 1개로 둔다

- 문제: uvicorn worker를 늘리면 백그라운드 루프와 DB 풀이 그 수만큼 곱해집니다. 연결 예산이 깨지고 run 동시 실행 수도 곱해집니다.
- 예방: 처리량이 필요하면 프로세스가 아니라 Pod 수를 늘립니다. 실행 명령(`python app.py`)과 gaia 템플릿의 worker 수를 바꾸지 않습니다.

### 4.8 앞단(Ingress, Istio)의 요청 크기와 SSE 설정

서비스는 이미지(base64)를 담은 요청을 32MB(`REQUEST_MAX_BYTES`)까지 받고, 실시간 이벤트는 SSE로 길게 열어 둡니다. 앞단이 아래를 만족해야 합니다.

| 필요한 것 | 이유 | nginx ingress 예 |
| --- | --- | --- |
| 요청 본문 32MB 허용 | 기본값(1MB)이면 큰 이미지 요청이 서비스에 닿기 전에 413 | `proxy-body-size: "32m"` |
| 응답 버퍼링 끔 | 켜져 있으면 이벤트가 모였다가 한꺼번에 도착 | `proxy-buffering: "off"` |
| 읽기 제한 시간을 길게 | 짧으면 SSE가 주기적으로 끊김 | `proxy-read-timeout: "3600"` |

- SSE는 15초 동안 이벤트가 없으면 유지 신호를 보내므로 idle 제한이 15초보다 길면 조용해서 끊기지는 않습니다. 전체 요청 시간 제한이 걸려 있으면 그 시간마다 끊기고, 브라우저가 마지막 이벤트 id로 다시 붙어 빠진 이벤트를 받습니다. 끊겨도 데이터는 잃지 않지만 화면이 잠깐씩 멈춥니다.
- 확인 필요: 운영 환경의 Istio VirtualService 설정. 경로(`/api/v1/`, `/view/`, gaia 경로)가 모두 이 서비스로 가는지, 경로별 timeout 값, 요청 크기 제한, 재시도 설정을 확인합니다. 특히 재시도가 POST에 걸려 있으면 같은 요청이 두 번 들어올 수 있습니다. run 생성은 `Idempotency-Key`를 보내면 한 번만 만들어집니다.

### 4.9 사용자와 키 변경은 다른 Pod에 조금 늦게 반영된다

| 변경 | 요청을 받은 Pod | 다른 Pod | 설정 |
| --- | --- | --- | --- |
| 사용자 비활성화, 역할 변경 | 즉시 | 최대 30초 | 코드 상수 `USER_CACHE_SECONDS` |
| API 키 폐기, 재발급 | 즉시 | 최대 60초 | `API_CLIENT_CACHE_SECONDS` |

유출된 키처럼 바로 막아야 하면 폐기한 뒤 60초를 기다리거나 Pod를 재시작합니다.

### 4.10 임베딩 모델이나 차원을 바꾸면 워크플로우 검색이 비어 보인다

- 문제: 벡터는 `모델이름:차원`으로 구분됩니다. `EMBEDDING_MODEL`이나 `EMBEDDING_DIMS`를 바꾸면 기존 벡터는 검색에서 빠집니다.
- 예방: 바꾼 뒤 기존 워크플로우를 `POST /api/v1/workflows/{id}/reindex`로 다시 색인합니다. `EMBEDDING_DIMS`는 모델의 실제 출력 차원과 같아야 하고 2,000 이하여야 합니다. `EMBEDDING_SEND_DIMENSIONS`는 차원을 요청으로 지정할 수 있는 모델에서만 true입니다. 게이트웨이 확인은 `scripts/check_embedding.sh`로 합니다.

### 4.11 공유 저장소의 경로와 계정

- 문제: 코드 파일과 결과 파일을 executor와 공유 저장소로 주고받습니다. 마운트 경로나 UID가 다르면 파일을 못 읽습니다.
- 예방: `STORAGE_ROOT`(우리가 쓰는 폴더), `STORAGE_EXECUTOR_PATH`(executor가 보는 상대 경로), `EXECUTOR_RESULT_ROOT`(결과 경로의 기준 루트, 공통 `/mnt/data/dtest`)를 executor 설정과 맞춥니다. 컨테이너는 UID 1000으로 실행합니다.

### 4.12 로그에 키가 찍혀도 가려지지만, 설정 파일은 그렇지 않다

로그에서는 `pas_`, `exe_`, `bat_`으로 시작하는 키와 `X-Api-Key` 값이 `***`로 가려집니다. 설정 파일(`config.prd.yml`)에는 키가 그대로 있으므로 레포와 이미지의 접근 권한을 관리합니다.

### 4.13 main과 internal/gaia를 같이 고친다

모든 변경은 두 브랜치에 함께 반영합니다. 한쪽에만 마이그레이션 번호를 쓰면 번호가 충돌합니다. main에서 새 파일을 만들면 병합 뒤 `src/dtest/` 아래로 옮기고 import를 `src.dtest.`로 고쳐야 하며, 빠진 곳은 `tests/test_entry.py`가 알려 줍니다.

### 4.14 로컬에서 브랜치를 바꾸면 실행 중인 컨테이너가 깨질 수 있다

docker compose로 띄운 앱은 레포의 `web`, `assets`, `catalogs` 폴더를 마운트합니다. main과 internal/gaia는 이 폴더들의 위치가 달라, 컨테이너를 띄운 채 브랜치를 바꾸면 마운트가 비어 `/dev/`가 404가 됩니다(2026-11-22 사례). 브랜치를 바꾼 뒤에는 컨테이너를 다시 만들고 `/dev/`가 열리는지 확인합니다.

## 5. 부하를 받는 포인트

### 5.1 한눈에 보기

| # | 구간 | 한계(측정값) | 포화 신호 | 조정 |
| --- | --- | --- | --- | --- |
| 1 | 앱 프로세스 CPU (Pod당 1코어) | 읽기 API 초당 약 1,000건, 단순 대화 초당 14~24턴 (로컬, mock LLM) | Pod CPU 100%, 응답 지연 증가 | Pod 수 증가(HPA) |
| 2 | LLM 게이트웨이 동시 호출 | Pod 수 × (`RUN_CONCURRENCY` 16 + `BATCH_REPORT_CONCURRENCY` 4) | LLM 응답 지연, 429·5xx, run 실패 | 두 설정을 낮춤 |
| 3 | run 큐 | Pod당 동시 16턴 | `queued` run이 계속 쌓임 | `RUN_CONCURRENCY` 또는 Pod 수 증가 |
| 4 | executor 실행 제출 | 초당 3~7건, 동시 20건부터 응답 수 초 (로컬) | 분석 시작이 느려짐, 제출 시간 초과 | executor 쪽 조치 필요 |
| 5 | executor 조회 게이트웨이 | 초당 약 310건 (로컬, 우리 앱과 executor 각 1코어 포화) | 조회 지연 | 우리 Pod와 executor 모두 증설 |
| 6 | DB 앱 풀 | Pod당 6 | 로그에 `QueuePool limit` | `DB_POOL_SIZE` 증가 (4.5절 예산 확인) |
| 7 | DB 그래프 풀 | Pod당 8, 대기 30초 | 턴이 풀 대기 시간 초과로 실패 | `CHECKPOINT_POOL_SIZE` 증가 (예산 확인) |
| 8 | 배치 리포트 | Pod당 동시 4건 | `QUEUED` 리포트 작업이 쌓임 | `BATCH_REPORT_CONCURRENCY` 증가 |
| 9 | 이벤트 테이블 | 턴당 수십 행 | run_events 크기 증가, 보존 정리 지연 | 보존 기간 단축 |

### 5.2 앱 프로세스 CPU

Pod 하나는 프로세스 하나, 사실상 CPU 1코어를 씁니다. 로컬에서 LLM을 즉시 응답하는 mock으로 바꿔 서비스 자체 처리량을 잰 값입니다.

| 조건 | 처리량 | 턴 지연 p50 / p95 | 읽기 API |
| --- | --- | --- | --- |
| 프로세스 1개, 사용자 50명 | 초당 14.4턴 | 2.08초 / 3.17초 | 초당 1,147건 |
| 프로세스 1개, 사용자 100명 | 초당 24.2턴 | 3.65초 / 5.10초 | 초당 982건 |
| 프로세스 2개, 사용자 100명 | 초당 28.1턴 | 1.10초 / 2.42초 | 초당 1,123건 |

- 단순 대화 한 턴의 CPU 비용은 약 40ms입니다(LLM 대기 제외).
- 실제 LLM은 호출당 수 초가 걸리므로 운영에서는 CPU보다 LLM 대기가 지배합니다. 사용자 약 200명 규모에는 Pod 2개로 여유가 있다는 것이 설계 판단입니다.
- HPA는 CPU 기준입니다. LLM 대기 중에는 CPU를 거의 쓰지 않으므로 큐가 밀려도 Pod가 늘지 않습니다. 그래서 최소 2개를 유지하고, 큐 적체는 `RUN_CONCURRENCY`로 흡수합니다.

### 5.3 LLM 게이트웨이

서비스에서 가장 느리고 가장 자주 한계에 닿는 곳입니다.

- 분석 한 턴은 모델을 5~10회 부릅니다. 한 턴의 상한은 40회(`AGENT_MODEL_CALL_LIMIT`)입니다.
- 동시에 나가는 LLM 요청은 Pod당 최대 `RUN_CONCURRENCY + BATCH_REPORT_CONCURRENCY`(기본 20)입니다. Pod 4개면 80입니다. 게이트웨이의 동시 처리 한도를 넘지 않게 맞춥니다.
- 한 사용자가 동시에 돌릴 수 있는 턴은 4개(`RUN_USER_CONCURRENCY`)입니다. 한 사람이 세션을 여러 개 열어 슬롯을 독차지하지 못하게 합니다.
- LLM 호출 시간 제한은 120초(`LLM_TIMEOUT_SECONDS`)입니다.
- 확인 필요: 운영 LLM 게이트웨이의 동시 처리 한도와 모델별 처리량.

### 5.4 run 큐와 대기

- run은 PostgreSQL 테이블을 큐로 씁니다. 모든 Pod가 같은 큐에서 `FOR UPDATE SKIP LOCKED`로 나눠 가져갑니다.
- 사용자 확인이나 executor를 기다리는 run(`waiting_input`, `waiting_executor`)은 슬롯을 반납하므로 며칠 쌓여도 부하가 아닙니다. 부하는 `queued`와 `running`만 봅니다.
- `queued`가 줄지 않으면 슬롯이 모자란 것입니다. 6.9절의 SQL로 봅니다.

### 5.5 executor

2026-11-22 로컬 부하 테스트(Locust, 게이트웨이 경유) 결과입니다.

| 호출 | 가상 사용자 | 초당 처리 | p50 | p95 |
| --- | --- | --- | --- | --- |
| 조회 | 50 | 311 | 151ms | 250ms |
| 조회 | 150 | 316 | 471ms | 611ms |
| 제출 후 취소 | 10 | 12.1 | 1.4초 | 2.3초 |
| 제출 후 취소 | 20 | 5.7 | 4.2초 | 7.0초 |
| 제출 후 취소 | 60 | 4.0 | 13.6초 | 17.0초 |

- 조회는 초당 약 310건에서 우리 앱과 executor가 각각 CPU 1코어를 다 써 더 늘지 않습니다.
- 제출은 CPU가 한가한데도 초당 3~7건에 머뭅니다. executor에 직접 보내도 같아서 병목은 executor의 `POST /executions` 안쪽입니다. executor 로그에는 `Executor Worker full max_active=20`이 남았습니다. 우리 쪽에서 조정할 수 있는 것이 없어 executor 담당에게 확인을 요청한 상태입니다.
- 같은 테스트에서 executor의 실행 목록 조회가 간헐적으로 500(`KeyError`)을 냈고, 메모리 한도로 런타임 배정이 12~13초씩 멈추는 일이 있었습니다. 역시 executor 쪽 사안입니다.
- 분석 한 건이 executor에 보내는 요청은 쓰기 4~5번, 조회 7~8번입니다.
- 우리 쪽 executor 호출 시간 제한은 30초(`EXECUTOR_TIMEOUT_SECONDS`)입니다. 제출이 몰려 이 시간을 넘으면 분석 시작이 실패합니다.

### 5.6 DB 연결 풀

- 앱 풀은 턴이 도는 동안에는 거의 쓰이지 않고, 많은 턴이 한꺼번에 시작될 때만 몰립니다. 32턴을 동시에 시작한 측정에서 꽉 찬 것은 첫 1초뿐이었습니다.
- 그래프 풀은 실행 중인 턴이 그래프 단계마다 체크포인트를 쓰는 데 씁니다. 32턴 동시 실행에서 동시 사용 최대가 9였습니다. `RUN_CONCURRENCY`의 절반 이상으로 둡니다.

### 5.7 SSE와 Redis

- SSE 연결 수와 Redis 연결 수는 무관합니다. 프로세스마다 Redis 패턴 구독 하나로 받아 메모리 큐로 나눠 줍니다. Redis 연결은 프로세스당 고정(약 16개)입니다.
- 토큰 스트리밍은 run별로 50ms 단위로 묶어 보내고 저장하지 않습니다.
- 열린 SSE 연결은 Pod 메모리와 파일 핸들을 씁니다. 사용자당 열어 둔 탭 수만큼 생깁니다.

### 5.8 배치가 한꺼번에 끝날 때

배치 실행이 성공하면 리포트 작업이 하나씩 생기고, 리포트 한 건은 LLM을 최대 20번(`BATCH_REPORT_MODEL_CALL_LIMIT`) 차례로 부릅니다. 같은 시각에 예약된 배치가 많으면 리포트가 밀리고 LLM 호출이 채팅과 경쟁합니다. 밀리면 `BATCH_REPORT_CONCURRENCY`를 올리고, LLM 한도에 가까우면 내립니다.

### 5.9 조정 설정 요약

| 설정 | 기본 | 올릴 때 | 올리기 전에 볼 것 |
| --- | --- | --- | --- |
| `RUN_CONCURRENCY` | 16 | `queued` run이 계속 쌓일 때 | LLM 동시 한도, `CHECKPOINT_POOL_SIZE` |
| `RUN_USER_CONCURRENCY` | 4 | 한 사용자의 동시 턴을 더 허용할 때. 0이면 제한 없음 | |
| `DB_POOL_SIZE` | 3 | 로그에 `QueuePool limit`이 보일 때 | DB 연결 예산 |
| `CHECKPOINT_POOL_SIZE` | 8 | 턴이 풀 대기로 실패할 때 | DB 연결 예산 |
| `BATCH_REPORT_CONCURRENCY` | 4 | 리포트 작업이 밀릴 때 | LLM 동시 한도 |
| HPA 최대 Pod | 4 | CPU가 계속 높을 때 | DB 연결 예산 (Pod당 14) |

### 5.10 부하 테스트 방법

- 로컬, mock LLM으로 서비스 자체 처리량: `uv run python scripts/loadtest.py --users 100 --turns 3`
- dev·prd, API 키 호출: `locust/` 폴더. `locust/README.md`에 실행 방법이 있고, 조회와 제출 비중은 `LOAD_ME_WEIGHT`, `LOAD_GATEWAY_READ_WEIGHT`, `LOAD_GATEWAY_SUBMIT_WEIGHT`로, 동시에 살려 둘 실행 수는 `LOAD_EXECUTOR_MAX_ACTIVE`로 정합니다.
- 제출 부하는 executor 런타임을 실제로 쓰므로 운영에서는 시간대와 규모를 executor 담당과 맞춥니다.

## 6. 장애 대응: 어디서 무엇을 보나

### 6.1 먼저 보는 순서

1. Pod 상태: 떠 있는지, 재시작 횟수가 늘었는지. 통합테스트 계획에는 내부망에서 kubectl을 쓸 수 없다고 적혀 있습니다. Pod 상태와 로그를 보는 수단(배포 포털 등)은 확인 필요입니다.
2. `GET /api/v1/healthz`: `{"status": "down", "stopped": [...]}`이면 백그라운드 루프가 죽은 것입니다. `stopped`에 죽은 루프 이름이 나옵니다.
3. 앱 로그: 아래 표의 키워드로 찾습니다.
4. DB: run 상태 분포(6.9절), 연결 수.
5. 연결된 서비스: executor, pr-batch, LLM 게이트웨이, Redis가 살아 있는지.

### 6.2 요청 하나를 추적하는 방법

- 모든 응답에 `X-Request-ID` 헤더가 붙습니다. 같은 값이 로그의 `[...]` 칸과 executor로 보내는 호출 헤더에 남습니다. 사용자가 헤더 값을 주면 그 값으로 우리 로그와 executor 로그를 함께 찾습니다.
- 사용자 화면의 오류 메시지에는 8자리 오류 ID가 있습니다. 그 ID로 로그를 검색하면 같은 줄이 나옵니다.
- 키 호출은 요청마다 감사 로그 한 줄(경로, 상태 코드, tenant)이 남습니다.
- Agent가 어떤 프롬프트로 어떤 도구를 불렀는지는 Phoenix에서 봅니다(7.3절).

### 6.3 증상별 대응표

| 증상 | 먼저 볼 곳 | 흔한 원인 | 조치 |
| --- | --- | --- | --- |
| Pod가 뜨지 않음 (CrashLoop) | 기동 로그의 `ValueError`, `dtest_startup_failed` | 설정 검사 실패(2.4절), 마이그레이션 실패, DB·Redis 접속 불가, Sentinel 복호화 실패 | 메시지에 나온 설정 키를 고침. 마이그레이션이면 이전 이미지로 되돌리고 원인 확인 |
| 모든 요청이 401 `Access key is required` | 기동 로그에 `gaia_auth_skipped_on_own_paths`가 있는지 | gaia 접근 키 검사가 우리 경로에 걸림 | gaia 템플릿 버전과 `attach` 호출 위치 확인 |
| 로그인이 안 됨 | `sso_` 로 시작하는 로그 (6.4절) | SSO 주소, 허용 origin, 쿠키 도메인, Redis | 6.4절 표 |
| 로그인은 되는데 곧 풀림 | Redis 상태, 세션 설정 | Redis 재시작·장애 전환, `SESSION_TTL_SECONDS`(30분 무활동), `SESSION_MAX_SECONDS`(12시간) | Redis 확인. 정상 만료면 조치 없음 |
| 메시지를 보냈는데 답이 시작되지 않음 | run 상태 SQL, `run_claim_failed`, `/healthz` | 슬롯 부족(`queued` 적체), 스케줄러 루프 죽음, DB 오류 | 6.5절 |
| 답이 중간에 멈춤 | 그 run의 `status`, `error`, 로그의 `run_lease_lost`, `run_heartbeat_failed` | Pod 재시작(다른 Pod가 이어 감), LLM 지연, DB 일시 장애 | 6.5절 |
| run이 `failed` | `runs.error`, 화면의 오류 ID로 로그 검색 | LLM 장애·한도·컨텍스트 초과, executor 장애, 재시도 5회 초과 | 원인 서비스 확인. 사용자는 다시 보내면 됨 |
| 분석이 끝나지 않음 (계속 실행 중) | run이 `waiting_executor`인지, `executor_event_*` 로그, executor의 실행 상태 | executor 이벤트 미수신(Redis 불일치), executor에서 실제로 오래 걸림, executor 장애 | 6.6절 |
| 화면이 실시간으로 갱신되지 않음, 새로 고치면 보임 | 앞단 설정, `event_fanout_reconnect` 로그 | 앞단 버퍼링·시간 제한(4.8절), Redis 구독 끊김 | 앞단 설정 확인. Redis 구독은 자동으로 다시 붙음 |
| 413 | 요청 크기 | 32MB 초과, 또는 앞단이 먼저 끊음(응답 형식이 우리 것이 아니면 앞단) | 앞단 본문 크기 제한 확인 |
| 429 | 로그인 경로인지 | SSO 로그인 요청이 분당 30회(`SSO_RATE_LIMIT_PER_MINUTE`) 초과 | 반복 로그인 원인 확인. `Retry-After` 뒤 재시도 |
| 502 `bad_gateway` | 로그의 `upstream_unreachable path=...` | executor 또는 pr-batch가 응답하지 않음 | 경로로 어느 서비스인지 보고 그 서비스 확인 |
| 503 (시스템 화면) | `EXECUTOR_ADMIN_API_KEY` 설정 | 운영 키가 비어 있음 | 키 설정 |
| 키 호출이 401·403 | 감사 로그, 키 상태 | 키 폐기·재발급, `X-User-Id` 누락(400), 일반키로 다른 사용자 조회(403) | 키 목록에서 상태 확인. 6.7절 |
| DB 연결 오류 | `QueuePool limit`, `too many connections`, 풀 대기 시간 초과 | 연결 예산 초과, 풀 부족, 중간 장비가 연결을 끊음 | 6.8절 |
| 배치 리포트가 안 만들어짐 | `batch_report_jobs`의 `state`, `failed_stage`, `error`. 로그의 `batch_report_*` | 노트북 대기 시간 초과(30분), LLM 장애, 배치 소유자 없음(`batch_report_without_owner`) | 놓친 실행은 10분마다 복구 작업이 최근 14일분을 다시 확인해 작업을 만듦 |
| 워크플로우 추천이 안 나옴 | `workflows.index_state` | 임베딩 게이트웨이 장애(`failed`), 임베딩 미설정(`not_indexed`), 모델·차원 변경 | 4.10절 |
| `/healthz`가 503 | 응답의 `stopped`, 로그의 `worker_loops_stopped` | 백그라운드 루프가 예외로 끝남 | liveness가 Pod를 재시작함. 반복되면 그 루프의 직전 예외 로그 확인 |
| 프로젝트 메모리가 자동으로 정리되지 않음 | `memory_extraction_state`의 `last_error`, 로그의 `memory_extract_failed` | LLM 장애, `MEMORY_WORKER_ENABLED: false` | 원인 해소 후 자동 재시도 |

### 6.4 로그인(SSO) 문제

브라우저로 `{PUBLIC_API_ORIGIN}/api/v1/auth/login/sso?return_to=/`를 열어 단계별로 봅니다. 로그 이름은 `src.dtest.api_service.auth`입니다.

| 단계 | 정상 | 로그 |
| --- | --- | --- |
| 1. 처음 요청 | SSO 로그인 페이지로 302 | `sso_verify result=no_cookie`, `sso_login_redirect to=<SSO 호스트>` |
| 2. SSO 로그인 후 | `.../auth/login/sso/callback/<flow_id>`로 돌아옴 | `sso_verify result=ok`, `sso_login_ok from_callback=True` |
| 3. 화면 복귀 | `FRONTEND_ORIGIN + return_to`, `agentic_session` 쿠키 생김 | |
| 4. `GET /api/v1/users/me` | 200, 사번과 이름이 맞음 | |

| 증상 | 뜻 | 먼저 볼 것 |
| --- | --- | --- |
| `sso_userinfo result=http_404` | userinfo 주소가 틀림 | 로그인된 브라우저에서 그 주소를 직접 열어 JSON이 나오는지(대소문자 포함) |
| `sso_userinfo bad_fields` 또는 `no_employee` | 응답 JSON의 키 이름이 `idp_login.py`의 `FIELDS`와 다름 | 로그의 `keys=[...]`에 나온 이름으로 `FIELDS` 오른쪽을 고침 |
| 502 `invalid login URL` | 로그인 주소의 origin이 허용 목록에 없음 | `sso_login_url_rejected origin=...`의 값을 `SSO_ALLOWED_ORIGINS`에 추가 |
| 503 `SSO is unavailable` | SSO 확인 호출이 예외 | `sso_verify_failed error_type=...` |
| 콜백에서 401 `could not verify` | SSO에서 돌아왔지만 SSO 쿠키가 오지 않음 | `sso_verify result=rejected cookies=...`. SSO 쿠키가 없으면 도메인 문제(우리 주소가 IdP 도메인 아래가 아님) |
| 콜백에서 400 `Login flow expired` | 5분이 지났거나 같은 콜백을 다시 엶 | 처음부터 다시 로그인 |
| SSO와 우리 사이를 계속 왕복 | 복귀 주소를 잃어버림 | `sso_login_redirect`가 몇 번 찍히는지 |
| 로그인 후 403 `disabled` | 비활성 사용자 | `users.is_active` |

문제를 다른 사람에게 전달할 때 쿠키 값, 로그인 URL 전체, 사번은 보내지 않습니다. 상태 코드, 멈춘 주소의 경로, 위 로그 줄이면 충분합니다.

SSO 쿠키는 IdP 도메인 아래 주소에만 오고 그 도메인은 https만 허용합니다. 서비스 주소가 그 도메인 아래가 아니거나 http이면 콜백에서 쿠키가 없어 401이 납니다.

### 6.5 run이 시작되지 않거나 멈출 때

run 한 건의 상태를 봅니다.

```sql
SELECT id, status, attempts, lease_owner, lease_expires_at,
       cancel_requested, error, waiting, created_at, updated_at
FROM runs WHERE id = '<run id>';
```

| 보이는 상태 | 뜻 | 조치 |
| --- | --- | --- |
| `queued`가 오래 유지 | 가져갈 슬롯이 없거나 스케줄러가 멈춤 | 전체 분포(6.9절)에서 `running` 수가 Pod 수 × 16에 닿았는지, 같은 사용자의 `running`이 4개인지 확인. `/healthz` 확인 |
| `running`인데 `lease_expires_at`이 과거 | 실행하던 Pod가 죽음 | 조치 없음. 다른 Pod가 5초 안에 가져가 이어 감 |
| `running`이 오래 유지되고 lease는 갱신됨 | LLM 응답을 기다리는 중 | LLM 게이트웨이 상태 확인. 턴당 모델 호출 40회, 호출당 120초가 상한 |
| `waiting_input` | 사용자의 확인을 기다림 | 정상. 화면에 질문이 떠 있음 |
| `waiting_executor` | executor 실행을 기다림 | 6.6절 |
| `failed` | `error`에 이유 | 원인 서비스 확인 |

- 한 run은 멈춤 없이 연속 5번(`RUN_MAX_ATTEMPTS`) 가져갔는데도 결과가 없으면 `failed`로 끝납니다. 같은 run이 Pod를 계속 죽이는 것을 막기 위한 것입니다.
- 실행 권한(lease)은 60초이고 20초마다 갱신합니다. DB 장애로 40초 동안 갱신하지 못하면 그 Pod는 턴을 스스로 멈춥니다(`run_lease_unrenewed`). 두 Pod가 같은 턴을 동시에 돌리지 않기 위해서입니다.
- 세션에 진행 중인 run이 남아 새 메시지를 못 보내는 경우 `sessions.active_run_id`와 그 run의 상태를 함께 봅니다.

### 6.6 분석이 끝나지 않을 때 (executor 대기)

1. run의 `waiting`에서 `execution_id`를 확인합니다.
2. executor에서 그 실행의 상태를 봅니다. 시스템 화면 또는 `GET /api/v1/executor/executions/{execution_id}`.
3. executor에서는 끝났는데 우리 run이 그대로면 이벤트가 오지 않은 것입니다.

```sql
SELECT event_type, event_sequence, received_at
FROM executor_inbox WHERE execution_id = '<execution id>'
ORDER BY event_sequence;
```

| 상황 | 원인 | 조치 |
| --- | --- | --- |
| inbox에 완료 이벤트가 없고, 로그에 `executor_event_recovered`가 자주 보임 | Redis가 executor와 다름(4.1절), 또는 이벤트 소비 루프 문제 | Redis 설정 대조. `executor_event_consumer_error` 로그 확인 |
| 로그에 `executor_event_group_lost` | Redis가 비워졌거나 스트림이 지워짐 | 자동으로 소비자 그룹을 다시 만듦. 그 사이 이벤트는 복구 절차가 채움 |
| 로그에 `missed_event_lookup_failed status=...` | 복구 절차가 executor에 물었지만 실패 | executor 상태와 `EXECUTOR_API_KEY` 확인 |
| executor에서도 실행 중 | 실제로 오래 걸리는 분석 | 기다리거나 사용자가 취소 |
| executor에 그 실행이 없음 | executor 데이터가 지워졌거나 다른 executor를 가리킴 | 사용자가 취소하고 다시 요청 |

놓친 이벤트 복구는 기다리기 시작한 지 120초(`EXECUTOR_EVENT_RECOVERY_SECONDS`)가 지난 run을 대상으로 합니다. 첫 1시간은 2분마다, 첫 하루는 10분마다, 그 뒤는 1시간마다 executor에 직접 물어 빠진 이벤트를 가져옵니다. Redis가 완전히 죽어도 분석은 결국 끝나지만 단계마다 2분 이상 늦어집니다.

### 6.7 키 호출 문제

| 응답 | 뜻 |
| --- | --- |
| 401 | 키가 없거나, 틀렸거나, 폐기됨 |
| 400 | `X-User-Id` 헤더가 없음. 2026-11-08부터 게이트웨이의 모든 호출에 필수 |
| 403 `FORBIDDEN` | 일반키로 `X-User-Id`와 다른 사용자의 것을 조회함. tenant 전체 조회가 필요하면 마스터키 |
| 502 | executor 또는 pr-batch가 응답하지 않음 |

우리가 executor나 pr-batch를 부를 때 401이 나면 우리 `EXECUTOR_API_KEY` 또는 `BATCH_API_KEY`가 상대 서비스에 등록된 해시와 맞지 않는 것입니다. 상대 서비스 설정에는 키 원문이 아니라 SHA-256 해시를 넣고, 우리 설정에는 원문을 넣습니다. 반대로 넣는 실수가 통합테스트에서 있었습니다.

### 6.8 DB 문제

| 로그 | 뜻 | 조치 |
| --- | --- | --- |
| `QueuePool limit of size ... reached` | 앱 풀이 모자람 | 일시적이면 무시. 반복되면 `DB_POOL_SIZE` 증가 |
| 그래프 풀 대기 시간 초과로 턴 실패 | 그래프 풀이 모자라거나 DB가 느림 | DB 응답 시간 확인. `CHECKPOINT_POOL_SIZE` 증가 |
| `too many connections` | 서버 연결 한도 초과 | 아래 SQL로 누가 쓰는지 확인. 예산(4.5절) 재계산 |
| `server closed the connection unexpectedly` | 중간 장비가 조용한 연결을 끊음 | `DB_KEEPALIVE_IDLE_SECONDS`를 낮춤(4.6절) |
| `run_claim_failed attempt=N` | run을 가져오는 쿼리 실패 | DB 상태 확인. 최대 30초 간격으로 계속 재시도하므로 DB가 돌아오면 자동 복구 |

```sql
-- 우리 서비스의 풀별 연결 수
SELECT application_name, state, count(*)
FROM pg_stat_activity
WHERE application_name LIKE 'pr-agentic-%'
GROUP BY 1, 2 ORDER BY 1, 2;

-- 서버 전체에서 누가 연결을 쓰는지
SELECT datname, usename, application_name, count(*)
FROM pg_stat_activity GROUP BY 1, 2, 3 ORDER BY 4 DESC;
```

DB가 잠깐 끊겼다 돌아오면 재시작 없이 복구됩니다. 그동안 들어온 요청은 실패하고, 실행 중이던 턴은 lease를 갱신하지 못해 멈춘 뒤 다시 큐로 돌아갑니다.

### 6.9 자주 쓰는 SQL

```sql
-- run 상태 분포 (부하와 적체 확인)
SELECT status, count(*) FROM runs
WHERE created_at > now() - interval '1 day'
GROUP BY 1 ORDER BY 2 DESC;

-- 지금 Pod별로 돌고 있는 run
SELECT lease_owner, count(*) FROM runs
WHERE status = 'running' AND lease_expires_at > now()
GROUP BY 1;

-- 오래 대기 중인 queued run
SELECT id, user_id, created_at FROM runs
WHERE status = 'queued' ORDER BY created_at LIMIT 20;

-- 최근 실패한 run과 이유
SELECT id, user_id, finished_at, left(error, 200) FROM runs
WHERE status = 'failed' ORDER BY finished_at DESC LIMIT 20;

-- executor를 오래 기다리는 run
SELECT id, waiting ->> 'execution_id' AS execution_id, updated_at
FROM runs WHERE status = 'waiting_executor'
ORDER BY updated_at LIMIT 20;

-- 배치 리포트 작업 상태
SELECT state, failed_stage, count(*) FROM batch_report_jobs
WHERE created_at > now() - interval '7 days'
GROUP BY 1, 2 ORDER BY 3 DESC;
```

### 6.10 Redis 문제

| 상황 | 동작 |
| --- | --- |
| Redis 재시작 | 로그인 세션이 사라지면 사용자가 다시 로그인. 이벤트 소비자 그룹은 자동으로 다시 만듦. worker 재시작 불필요 |
| Sentinel 장애 전환, 마스터 프로세스가 죽음 | 쓰기 재개 5~9초, 이벤트 수신 재개 6~10초, SSE 구독 재개 약 7초 |
| Sentinel 장애 전환, 마스터가 응답 없이 멈춤 | 쓰기 재개 약 16초, 이벤트 수신 약 17초, SSE 구독 약 31초 |

위 시간은 로컬 Sentinel 구성(마스터 1, 레플리카 2, Sentinel 3, `down-after-milliseconds` 3초)에서 잰 값입니다.

- 전환 중에는 요청이 실패할 수 있습니다(로그인 확인 포함). SSE는 끊겼다가 브라우저가 마지막 이벤트 id로 다시 받습니다.
- Redis 복제가 비동기라 전환 직전 몇 초의 로그인 세션과 executor 이벤트는 새 마스터에 없을 수 있습니다. 사용자는 다시 로그인하고, 빠진 이벤트는 복구 절차가 채웁니다.
- 응답 없는 서버는 오류를 내지 않으므로, 명령은 15초 안에 답이 없으면 끊고 다시 연결합니다. 구독은 15초 동안 조용하면 PING을 보내고 15초 안에 답이 없으면 다시 연결합니다.
- 관련 로그: `event_fanout_reconnect`, `run_wake_listener_reconnect`, `executor_event_consumer_error`.

### 6.11 로그 키워드 사전

오류 수준(바로 볼 것)

| 키워드 | 뜻 |
| --- | --- |
| `dtest_startup_failed` | 기동 실패. 바로 위 예외가 원인 |
| `worker_loops_stopped loops=...` | 백그라운드 루프가 죽음. `/healthz`가 503이 되고 Pod가 재시작됨 |
| `run_task_crashed` | 턴 실행이 실패 기록도 못 남기고 끝남(대개 DB 장애). lease 만료 뒤 다시 시도됨 |
| `run_lease_unrenewed` | lease를 40초 동안 갱신하지 못해 턴을 멈춤 |
| `run_claim_failed` | run 가져오기 실패 |
| `executor_event_consumer_error`, `executor_event_failed` | executor 이벤트 처리 실패 |
| `missed_event_recovery_error` | 놓친 이벤트 복구 루프 오류 |
| `batch_report_worker_error`, `batch_report_recovery_error` | 배치 리포트 처리 오류 |
| `retention_sweep_failed` | 보존 정리 실패. 다음 주기에 재시도 |
| `memory_extract_failed`, `memory_claim_failed` | 프로젝트 메모리 정리 실패 |

경고 수준(반복되면 볼 것)

| 키워드 | 뜻 |
| --- | --- |
| `upstream_unreachable path=...` | executor 또는 pr-batch가 응답하지 않아 502를 돌려줌 |
| `executor_event_recovered` | 이벤트를 스트림으로 못 받아 복구 절차로 받음. 자주 보이면 Redis 설정 문제 |
| `executor_event_group_lost` | Redis 소비자 그룹이 사라져 다시 만듦 |
| `executor_event_malformed` | 형식이 틀린 이벤트를 버림 |
| `missed_event_lookup_failed` | 복구 절차의 executor 조회 실패 |
| `run_heartbeat_failed`, `run_lease_lost` | lease 갱신 실패, 다른 Pod가 run을 가져감 |
| `run_model_replaced` | 목록에서 빠진 모델 대신 기본 모델로 이어 감 |
| `batch_disable_failed` | pr-batch에 배치 끄기 요청 실패. 재시도함 |
| `batch_report_lease_lost`, `batch_report_without_owner` | 리포트 작업 권한을 잃음, 배치 소유자를 찾지 못함 |
| `tool_load_failed` | 깨진 tool 파일을 건너뜀 |
| `sso_...` | 로그인 관련(6.4절) |
| `admin_employee_ids_empty` | 관리자 사번 설정이 비어 있음 |
| `phoenix_tracing_skipped` | 다른 쪽이 먼저 계측을 켜서 건너뜀 |

정상 동작 확인용

| 키워드 | 뜻 |
| --- | --- |
| `gaia_auth_skipped_on_own_paths` | 우리 경로에서 gaia 접근 키 검사를 건너뛰도록 적용됨 |
| `phoenix_tracing_on endpoint=... project=...` | Phoenix 추적 켜짐 |
| `checkpoints_pruned sessions=N`, `code_sources_purged files=N` | 보존 정리가 동작함 |
| `project_memory_migrated entries=N` | 예전 메모리 항목을 옮김(최초 1회) |

## 7. 모니터링과 로그

### 7.1 로그

- 내부망에서는 gaia와 HCP 라이브러리가 로깅을 맡고 사내 `logger.yml`을 읽습니다. 로그 레벨도 그 파일에서 바꿉니다.
- 각 줄에 요청 ID가 들어갑니다. 백그라운드 작업의 줄에는 run id나 작업 id가 `키=값` 형태로 들어갑니다.
- 키 호출은 요청마다 감사 로그가 남습니다.
- 확인 필요: 운영에서 로그를 조회하는 도구와 보관 기간.

### 7.2 볼 지표와 경보 기준(제안)

저장소에는 경보 설정이 없습니다. 아래는 이 문서에서 제안하는 기준입니다.

| 지표 | 보는 방법 | 경보 제안 |
| --- | --- | --- |
| Pod 재시작 횟수 | k8s | 10분 안에 2회 이상 |
| `/api/v1/healthz` | k8s liveness, 외부 점검 | 503 |
| Pod CPU | k8s | 80% 이상이 10분 지속, HPA가 최대에 도달 |
| Pod 메모리 | k8s | 한도 2Gi의 85% |
| `queued` run 수 | 6.9절 SQL | 5분 넘게 줄지 않음 |
| 1시간 내 `failed` run 비율 | 6.9절 SQL | 평소의 2배 |
| PostgreSQL 연결 수 | `pg_stat_activity` | 서버 전체 85 이상 |
| run_events 가장 오래된 행 | `SELECT min(created_at)` | 35일보다 오래됨(보존 정리 멈춤) |
| 오류 수준 로그 | 로그 도구 | 6.11절 오류 수준 키워드 발생 |
| `executor_event_recovered` 빈도 | 로그 도구 | 시간당 여러 건(Redis 불일치 의심) |

gaia 템플릿은 prometheus 계측기를 붙이므로 HTTP 요청 지표는 gaia가 제공하는 경로에서 볼 수 있습니다. 확인 필요: 운영의 지표 수집과 대시보드 구성.

### 7.3 Phoenix 추적

Agent의 모델 호출, 도구 호출, middleware 단계를 Phoenix로 보냅니다. 턴마다 어떤 프롬프트가 들어가고 어떤 도구가 어떤 인자로 불렸는지 볼 수 있어, "왜 이런 답을 했나"를 볼 때 씁니다.

| 설정 | 내용 |
| --- | --- |
| `PHOENIX_ENDPOINT` | Phoenix 주소. 비어 있으면 꺼짐(기본) |
| `PHOENIX_API_KEY` | Phoenix API 키 |
| `SERVICE_ID` | Phoenix 프로젝트 이름. 기본 `pr-agentic-service` |

- 켜지면 기동 로그에 `phoenix_tracing_on`이 나옵니다.
- 추적의 `session.id`가 우리 세션 id라 Phoenix의 Sessions 화면에서 대화 단위로 묶여 보입니다.
- 전송은 백그라운드 배치라 요청 처리 시간에 영향이 없습니다. Phoenix가 죽어도 서비스는 정상입니다.
- gaia는 자기 workflow만 추적하므로 우리 run은 우리가 같은 설정 이름으로 직접 등록합니다.

## 8. 정기 점검

| 주기 | 항목 | 방법 |
| --- | --- | --- |
| 매일 | 오류 수준 로그, Pod 재시작 | 로그 도구, k8s |
| 매주 | run 실패 비율, `queued` 적체 여부 | 6.9절 SQL |
| 매주 | PostgreSQL 연결 수 | `pg_stat_activity` |
| 매월 | 테이블 크기와 autovacuum | DB 물리 설계서 7장의 SQL |
| 매월 | 보존 정리 동작 | run_events, executor_inbox의 가장 오래된 행 |
| 매월 | 공유 저장소 사용량 | `STORAGE_ROOT` 아래 크기 |
| 분기 | 쓰지 않는 API 키 폐기, 마스터키 점검 | 키 목록의 `last_used_at` |
| 분기 | 관리자 목록 | `scripts/set_user_role.py --list` |
| 의존성 변경 시 | 고정 버전 확인 | `langgraph-checkpoint-postgres` 3.1.3, FastAPI 0.137 미만 |

## 9. 부록

### 9.1 주요 설정 키

전체 목록과 설명은 `config.example.yml`에 있습니다. 운영에서 자주 보는 것만 추렸습니다.

| 분류 | 키 | 기본값 | 뜻 |
| --- | --- | --- | --- |
| 실행 | `APP_ENV` | (없음) | `dev`, `stg`, `prd`. 설정 파일 선택 |
| 실행 | `RUN_MODE` | `all` | `all`, `api`, `worker`. API와 worker를 나눠 띄울 때 |
| DB | `DATABASE_URL` | | PostgreSQL 주소 |
| DB | `DB_POOL_SIZE` | 3 | 앱 풀 크기(같은 수만큼 overflow) |
| DB | `CHECKPOINT_POOL_SIZE` | 8 | 그래프 풀 크기 |
| DB | `CHECKPOINT_POOL_TIMEOUT_SECONDS` | 30 | 그래프 풀 대기 한도 |
| DB | `DB_KEEPALIVE_IDLE_SECONDS` | 60 | TCP keepalive 시작 시간 |
| DB | `AUTO_MIGRATE` | true | 기동 시 마이그레이션 실행 |
| Redis | `REDIS_MODE` | `standalone` | `standalone`, `sentinel` |
| Redis | `REDIS_URL` | | standalone 주소 |
| Redis | `REDIS_SENTINEL_HOST`, `_PORT`, `_MASTER_NAME`, `_USERNAME`, `_AUTH` | | Sentinel 접속 |
| Redis | `REDIS_NAMESPACE` | `agentic` | 키와 채널 접두어 |
| 인증 | `SSO_ADAPTER` | `idp` | `idp`, `dev`(로컬 전용) |
| 인증 | `PUBLIC_API_ORIGIN`, `FRONTEND_ORIGIN` | | 브라우저가 보는 API 주소, 프론트 주소 |
| 인증 | `SSO_ALLOWED_ORIGINS` | | SSO 로그인 페이지 origin 허용 목록 |
| 인증 | `CORS_ORIGINS` | | 다른 도메인의 프론트가 부를 때 |
| 인증 | `COOKIE_SECURE` | | https면 true (stg·prd 필수) |
| 인증 | `SESSION_TTL_SECONDS` | 1800 | 무활동 로그아웃 시간 |
| 인증 | `SESSION_MAX_SECONDS` | 43200 | 로그인 최대 유지 시간 |
| 인증 | `ADMIN_EMPLOYEE_IDS` | | 첫 로그인 때 관리자가 될 사번 |
| 인증 | `API_CLIENT_CACHE_SECONDS` | 60 | API 키 검증 캐시 |
| LLM | `LLM_BASE_URL`, `LLM_API_KEY` | | LLM 게이트웨이 |
| LLM | `MODELS` | | 사용자에게 보일 모델 목록 |
| LLM | `LLM_TIMEOUT_SECONDS` | 120 | 호출 시간 제한 |
| LLM | `AGENT_MODEL_CALL_LIMIT` | 40 | 턴당 모델 호출 상한 |
| executor | `EXECUTOR_BASE_URL`, `EXECUTOR_API_KEY` | | executor 주소와 우리 키 |
| executor | `EXECUTOR_ADMIN_API_KEY` | | 시스템 화면용 운영 키 |
| executor | `EXECUTOR_TENANT_ID` | `dtest-agent-service` | 우리 tenant |
| executor | `EXECUTOR_TIMEOUT_SECONDS` | 30 | executor 호출 시간 제한 |
| executor | `EXECUTOR_OPERATION_WAIT_SECONDS` | 1800 | 실행 단계 대기 한도 |
| executor | `EXECUTOR_EVENT_RECOVERY_SECONDS` | 120 | 놓친 이벤트 복구 시작 시간 |
| executor | `STORAGE_ROOT`, `STORAGE_EXECUTOR_PATH`, `EXECUTOR_RESULT_ROOT` | | 공유 저장소 경로 |
| pr-batch | `BATCH_BASE_URL`, `BATCH_API_KEY` | | pr-batch 주소와 우리 키 |
| 부하 | `RUN_CONCURRENCY` | 16 | Pod당 동시 턴 |
| 부하 | `RUN_USER_CONCURRENCY` | 4 | 사용자당 동시 턴 |
| 부하 | `RUN_LEASE_SECONDS` | 60 | 실행 권한 유지 시간 |
| 부하 | `RUN_MAX_ATTEMPTS` | 5 | 결과 없이 반복 실행되는 run의 상한 |
| 부하 | `BATCH_REPORT_CONCURRENCY` | 4 | Pod당 동시 리포트 |
| 요청 | `REQUEST_MAX_BYTES` | 33554432 | 요청 본문 한도(32MB) |
| 요청 | `IMAGE_MAX_BYTES`, `IMAGE_MAX_TOTAL_BYTES` | 10MB, 20MB | 이미지 한 장, 요청 전체 한도 |
| 보존 | `RUN_EVENT_RETENTION_DAYS` | 30 | 이벤트 보존 |
| 보존 | `EXECUTOR_INBOX_RETENTION_DAYS` | 7 | executor 이벤트 보존 |
| 기타 | `DOCS_ENABLED` | false | API 문서 노출 |
| 기타 | `PHOENIX_ENDPOINT` | (없음) | Phoenix 추적 |

### 9.2 운영 스크립트 (`scripts/`)

| 스크립트 | 용도 |
| --- | --- |
| `migrate.py` | 마이그레이션을 따로 실행 (`AUTO_MIGRATE: false`일 때) |
| `set_user_role.py`, `set_user_role.sql` | 관리자 지정과 역할 변경 |
| `check_redis_sentinel.py` | Redis Sentinel 접속 확인 |
| `check_embedding.sh`, `check_embedding.ps1` | 임베딩 게이트웨이 확인 |
| `check_executor_mcp.sh` | executor MCP 확인 |
| `migrate_project_memory.py` | 예전 항목형 프로젝트 메모리를 주제형으로 옮김 (`AUTO_MIGRATE: false`일 때) |
| `smoke_e2e.py` | 로그인부터 분석까지 종단 점검 |
| `run_scenarios.py` | 분석 시나리오 일괄 실행(품질 회귀 점검) |
| `loadtest.py` | 로컬 부하 측정 |
| `mock_llm.py` | LLM 게이트웨이 대역(로컬 테스트용) |
| `seed_test_workflows.py` | 테스트용 워크플로우 등록 |
| `run_local_https.ps1`, `run_app_tls.py`, `make_local_cert.py` | 개발 PC에서 https로 띄워 SSO 확인 |
| `gateway_docs.py` | 게이트웨이 문서 생성 |

### 9.3 백그라운드 루프

`/healthz`의 `stopped`와 로그에 나오는 이름입니다.

| 이름 | 하는 일 | 주기 |
| --- | --- | --- |
| `run-scheduler` | run을 가져와 Agent 실행 | Redis 신호 즉시, 5초 폴링 보조 |
| `executor-events` | executor 이벤트 스트림 소비 | 상시 |
| `missed-executor-events` | 놓친 executor 이벤트 복구 | 60초 |
| `batch-reports-0`~`3` | 배치 리포트 작성 | 상시 |
| `batch-report-recovery` | 리포트 작업이 빠진 배치 실행 찾기 | 10분 |
| `retention` | 보존 기간 지난 데이터 정리 | 1시간 |
| `batch-disable-retry` | 비활성 사용자·폐기 tenant의 배치 끄기 재시도 | 주기적 |
| `executor-cancel-retry` | executor 실행 취소 재시도 | 주기적 |
| `memory-worker` | 프로젝트 메모리 정리 | 대화가 3분 조용하거나 5턴 쌓이면 |

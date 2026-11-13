# 운영 메모

배포·운영할 때 알고 있어야 하는 동작과 설정입니다. 부하 관련 수치는 [load-design.md](load-design.md)를 봅니다.

## 1. API 키 발급 기준

`POST /api/v1/admin/api-clients`로 만드는 키는 tenant 기준으로 두 가지이고, 종류(`kind`)로 다시 일반키와 마스터키로 나뉩니다. 어떤 tenant가 executor·pr-batch를 쓸 수 있는지는 이 발급으로만 정합니다(2026-11-01). 두 서비스는 우리 key에 모든 tenant를 허용하므로(`allowed_tenants: ["*"]`), 새 tenant를 위해 두 서비스 설정을 바꾸거나 다시 배포할 일이 없습니다. 발급한 키는 바로 사용 중이 됩니다.

| 종류 | 권한 | 발급 대상 |
|---|---|---|
| 우리 tenant 키 (`tenant`에 우리 tenant + `own_tenant: true`) | 우리 사용자로 executor·배치 중계를 부릅니다. 마스터키로 발급하면 조회가 **우리 tenant 전체 사용자**의 실행·아티팩트·배치를 봅니다. | 우리 팀이 운영하는 서버 간 연동(배치 서버, 모니터링 등)만. 개인·다른 팀에는 발급하지 않습니다. |
| 다른 tenant 키 (`tenant` 지정) | 그 tenant 범위만 읽고 씁니다. | 다른 팀 서비스 |

종류(`kind`, 2026-11-08). 두 종류 모두 executor·배치 게이트웨이의 모든 호출에 `X-User-Id`가 필수입니다("누가 호출했나"를 남기는 값). 쓰기(제출·취소 등)는 두 종류가 같고 `X-User-Id` 사용자로 만들어집니다.

| kind | 게이트웨이 조회 범위 | 쿼리 `user_id` |
|---|---|---|
| `standard` (일반키, 기본값) | `X-User-Id` 사용자 것만 | 안 넣어도 됩니다. `X-User-Id`와 다른 값은 403 `FORBIDDEN` |
| `master` (마스터키) | tenant 전체 | 넣으면 그 사용자 것으로 거릅니다 |

- 2026-11-08 이전에 발급한 키는 모두 일반키입니다. 예전처럼 `X-User-Id` 없이 tenant 전체를 읽던 연동은 마스터키를 새로 발급받아 바꿔야 합니다(그 전에는 `X-User-Id` 없는 요청이 400입니다).

- 마스터키(특히 우리 tenant 마스터키)는 사실상 관리자 읽기 권한이므로, 발급 시 `description`에 용도와 담당자를 적고 분기마다 `GET /api/v1/admin/api-clients`로 쓰지 않는 키를 `/revoke`합니다.
- 다른 tenant 키를 발급할 때 그 호출자에게 `X-User-Id`로 **SSO 사번**을 보내기로 약속받습니다(시스템 호출은 `svc-…`). 사번 규칙이 정해지면 `EMPLOYEE_ID_PATTERN`에 넣어 형식을 강제합니다.
- key를 잃어버렸으면 화면의 "재발급"(`POST /api/v1/admin/api-clients/{id}/reissue`)으로 새 key를 받습니다. 원문은 저장하지 않아 다시 보여 줄 수 없습니다. 이전 key는 그 순간 끊기므로(다른 서버도 최대 1분 안에) 호출 서비스의 key를 곧바로 바꿉니다.
- tenant 하나를 끊을 때는 `POST /api/v1/admin/api-clients/tenants/{tenant}/revoke`로 그 tenant의 키를 모두 폐기합니다(화면의 "tenant 전체 폐기").
- 우리 쪽 `EXECUTOR_API_KEY`·`BATCH_API_KEY`는 executor·pr-batch에서 **모든 tenant**로 행세할 수 있는 키입니다. stg·prd에서는 레포 설정 파일이 아니라 배포 Secret으로만 주입하고, 교체는 상대 서비스 `key_sha256`에 새 해시를 먼저 추가해 배포한 뒤 우리 key를 바꾸고 옛 해시를 지우는 순서로 합니다.
- 키 원문은 발급 응답에서 한 번만 보입니다. DB에는 SHA-256만 남습니다.
- 키가 로그에 찍혀도 `pas_/exe_/bat_` 접두어 키와 `X-Api-Key` 값은 `***`로 가려집니다.

## 2. 비활성화·키 폐기가 반영되는 시간

각 Pod가 사용자와 API 키 검증 결과를 잠깐 캐시하므로, 다른 Pod에서는 아래 시간까지 이전 상태로 동작할 수 있습니다.

| 변경 | 요청을 받은 Pod | 다른 Pod | 설정 |
|---|---|---|---|
| 사용자 비활성화, 역할 변경 | 즉시 | 최대 30초 | 코드 상수 `USER_CACHE_SECONDS` (`src/dtest/api_service/deps.py`) |
| API 키 폐기·비활성화 | 즉시 | 최대 60초 | `API_CLIENT_CACHE_SECONDS` (config) |

- 비활성화하면 그 사용자의 진행 중인 턴과 executor 커널은 바로 취소됩니다. 캐시 시간 동안 남는 것은 "새 요청이 받아들여질 수 있다"는 것뿐입니다.
- 유출된 키처럼 바로 막아야 하면 폐기 후 `API_CLIENT_CACHE_SECONDS`만큼 기다리거나, Pod를 재시작합니다. 값을 줄이면 반영은 빨라지고 DB 조회는 늘어납니다.

### 역할(권한)을 DB에서 직접 바꾸기

평소에는 관리자 화면의 `PATCH /api/v1/admin/users/{user_id}` `{"role": "admin" | "user"}`로 바꿉니다(받은 Pod의 캐시도 바로 비웁니다). 관리자가 아무도 없거나 DB에서 직접 고쳐야 하면 서비스와 같은 config로 아래 스크립트를 씁니다.

```
python scripts/set_user_role.py --env prd --list                 # 관리자 목록
python scripts/set_user_role.py --env prd A10054 admin --dry-run # 확인만, 롤백
python scripts/set_user_role.py --env prd A10054 admin           # 승격 (강등은 user)
```

- 대상은 사번(대소문자 무시) 또는 `users.id`이고, 정확히 한 명일 때만 바꿉니다. 마지막 활성 관리자는 강등하지 않습니다.
- `--env prd`는 `config.prd.yml`(없으면 `config.yml`)의 `DATABASE_URL`만 씁니다. `--env` 없이 실행하면 서비스와 같은 순서(환경변수, `.env`, `config.{APP_ENV}.yml`, `config.yml`)로 찾고, `--dsn`은 언제나 가장 우선입니다. 접속할 DB를 먼저 출력합니다(비밀번호는 가림).
- psql로 직접 하려면 `scripts/set_user_role.sql`을 씁니다. `role`에는 DB 제약이 없으니 `user`, `admin` 외의 값을 넣지 않도록 주의합니다.
- 재로그인은 필요 없고 모든 Pod에 최대 30초 안에 반영됩니다(위 표). `ADMIN_EMPLOYEE_IDS`는 최초 로그인 때만 쓰이므로 이후 로그인이 바꾼 역할을 덮어쓰지 않습니다.

## 3. DB 마이그레이션 (`AUTO_MIGRATE`)

`AUTO_MIGRATE: true`(기본)이면 Pod가 시작할 때 마이그레이션을 실행합니다. 여러 Pod가 동시에 떠도 advisory lock으로 한 Pod만 실행합니다. 다만 마이그레이션이 실패하면 **모든 Pod가 시작에 실패해 CrashLoop**에 빠지고, 이전 버전 Pod도 롤링 업데이트로 내려간 뒤라면 서비스가 멈춥니다.

운영(prd)은 배포 단계에서 따로 실행하는 것을 권장합니다.

1. `config.prd.yml`에 `AUTO_MIGRATE: false`.
2. 배포 파이프라인에서 Pod 롤아웃 전에 같은 이미지·같은 config로 한 번 실행합니다.
   ```
   python scripts/migrate.py
   ```
   실패하면 0이 아닌 코드로 끝나므로 파이프라인이 멈추고, 기존 Pod는 그대로 서비스합니다.
3. 성공하면 Pod를 롤아웃합니다.

dev·stg는 `AUTO_MIGRATE: true`로 두어도 됩니다. 마이그레이션은 이전 버전 코드가 계속 동작하도록(컬럼 추가, 인덱스 추가) 작성하므로 롤아웃 전에 먼저 실행해도 안전합니다.

## 4. Ingress 요청 크기

이미지(base64)를 담은 요청은 서비스 기준 최대 32MB(`REQUEST_MAX_BYTES`)까지 받습니다. nginx ingress 기본값은 1MB라서 그대로 두면 큰 이미지 요청이 서비스에 닿기 전에 413으로 끊깁니다.

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "32m"
```

SSE(`/events`)가 끊기지 않도록 아래도 함께 둡니다.

```yaml
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
```

## 5. 종료와 헬스체크

- 종료 시 uvicorn `--timeout-graceful-shutdown 20`으로 요청을 마무리하고, 워커는 진행 중인 턴을 병렬로 정리합니다. Pod `terminationGracePeriodSeconds`는 30초 이상으로 둡니다(`deploy/kubernetes/deployment.yml`은 60초).
- liveness는 `/healthz`(워커 루프가 살아 있는지 포함), readiness는 `/readyz`를 씁니다.

## 6. 요청 추적

모든 응답에 `X-Request-ID`가 붙고, 같은 값이 로그의 `[...]` 칸과 executor 호출 헤더에 남습니다. 사용자 오류 메시지의 8자리 오류 ID는 서버 로그의 같은 줄을 찾는 데 씁니다.

## 7. API 문서 (`DOCS_ENABLED`)

`/docs`(Swagger), `/redoc`, `/openapi.json`은 내부망 규정에 따라 개발계를 포함해 모든 서버 환경에서 꺼 둡니다. 설정은 `DOCS_ENABLED`이고 기본값과 `config.yml` 값은 `false`입니다. docker compose 로컬 실행만 `true`입니다. internal/gaia에서는 템플릿이 만든 앱의 문서 경로도 같이 내립니다.

## 8. DB 연결 구분

executor, pr-batch와 같은 PostgreSQL을 쓰므로 연결에 이름을 붙입니다. `pg_stat_activity.application_name`이 앱 테이블 풀은 `pr-agentic-app`, LangGraph checkpoint/store 풀은 `pr-agentic-graph`입니다. 풀별 사용량은 아래로 봅니다.

```sql
SELECT application_name, state, count(*)
FROM pg_stat_activity
WHERE application_name LIKE 'pr-agentic-%'
GROUP BY 1, 2 ORDER BY 1, 2;
```

서비스별 연결 예산은 [load-design.md](load-design.md)의 표를 따릅니다.

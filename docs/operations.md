# 운영 메모

배포·운영할 때 알고 있어야 하는 동작과 설정입니다. 부하 관련 수치는 [load-design.md](load-design.md)를 봅니다.

## 1. API 키 발급 기준

`POST /api/v1/admin/api-clients`로 만드는 키는 두 종류입니다.

| 종류 | 권한 | 발급 대상 |
|---|---|---|
| 우리 tenant 키 (`tenant` 비움) | `X-User-Id` 없이 executor·배치 중계를 GET하면 **우리 tenant 전체 사용자**의 실행·아티팩트·배치를 읽습니다(시스템 조회). `X-User-Id`를 붙이면 그 사용자로 동작합니다. | 우리 팀이 운영하는 서버 간 연동(배치 서버, 모니터링 등)만. 개인·다른 팀에는 발급하지 않습니다. |
| 다른 tenant 키 (`tenant` 지정) | 그 tenant 범위만 읽고 씁니다. executor·pr-batch의 `allowed_tenants`에 들어간 뒤에 활성화합니다. | 다른 팀 서비스 |

- 우리 tenant 키는 사실상 관리자 읽기 권한이므로, 발급 시 `description`에 용도와 담당자를 적고 분기마다 `GET /api/v1/admin/api-clients`로 쓰지 않는 키를 `/revoke`합니다.
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

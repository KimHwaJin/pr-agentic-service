# 00. 게이트웨이 공통 규칙

executor 게이트웨이(`/api/v1/executor/…`)와 배치 게이트웨이(`/api/v1/batch/…`)에 똑같이 적용되는 규칙입니다. 경로별 문서는 이 내용을 반복하지 않습니다.

## 1. 구조

- 호출자는 pr-agentic-service에만 접속합니다. executor와 pr-batch의 주소와 key는 호출자에게 주지 않습니다.
- `/api/v1/executor/{path}`는 executor `/api/v1/{path}`로, `/api/v1/batch/{path}`는 pr-batch `/api/v1/{path}`로 중계됩니다. 메서드, 쿼리, 본문은 그대로 넘어가고, 응답의 상태 코드와 본문도 그대로 돌아옵니다(배치는 오류 본문만 공통 형식으로 맞춥니다, 6장).
- **문서에 있는 경로만 쓸 수 있습니다.** 그 밖의 경로와 메서드는 404 `NOT_FOUND`(`Not available through this service.`)입니다. 목록은 각 게이트웨이 문서의 "엔드포인트 한눈에 보기"에 있습니다.
- 게이트웨이는 호출자의 key와 사용자를 확인하고(3장, 4장), key 종류에 따라 조회 범위를 정합니다(4장). 호출자가 보낸 `X-Tenant-Id`, `Authorization`, `Cookie` 같은 헤더는 쓰지 않습니다(5장).

## 2. 주소

pr-agentic-service는 쿠버네티스 클러스터에 배포되어 있고, 호출자는 배포된 서비스의 주소로 부릅니다.

| 호출 위치 | Base URL | 비고 |
| --- | --- | --- |
| 클러스터 밖 (다른 서비스·사내망) | 환경(dev·stg·prd)별 공개 주소 `https://<api-host>` | 담당자에게 받습니다 |
| 같은 클러스터 안 | `http://pr-agentic-service.<namespace>.svc.cluster.local` (Service 포트 80) | 네임스페이스는 담당자에게 받습니다 |

- 이 문서의 경로는 모두 Base URL 뒤에 붙습니다. 예: `https://<api-host>/api/v1/executor/executions`.
- Base URL은 코드에 넣지 않고 설정(예: `AGENTIC_BASE_URL`)에서 읽어, 환경마다 바꿔 끼웁니다.
- 배포된 서비스의 Swagger(`/docs`)와 `/openapi.json`은 꺼져 있습니다(내부망 규정). 경로별 스키마는 이 폴더의 [openapi/](openapi/) 파일을 씁니다.

## 3. API key

key는 이 서비스 관리자에게 요청해 발급받습니다. 원문은 발급할 때 한 번만 보이므로 바로 안전한 곳에 저장합니다. 잃어버리면 관리자가 재발급합니다(같은 tenant·종류로 새 key). 이전 key는 그때 바로 끊기므로 새 key로 곧바로 바꿉니다.

| 항목 | 값 |
| --- | --- |
| 형식 | stg·prd는 `pas_live_…`, dev는 `pas_dev_…` |
| 보내는 법 | 모든 요청에 `X-Api-Key: <key>` |
| tenant | key마다 하나. 발급할 때 정하고 바꿀 수 없습니다. 호출자가 만드는 실행·배치는 모두 이 tenant에 속합니다 |
| 종류 (`kind`) | `standard`(일반키, 기본값) 또는 `master`(마스터키). **조회 범위만** 다릅니다(4장) |
| 폐기 | 관리자가 key 하나 또는 tenant 전체를 폐기합니다. 60초 안에 반영되고, 그 뒤로는 401입니다 |

- tenant가 다르면 서로의 실행·배치·아티팩트가 보이지 않습니다(404).
- key는 설정이나 환경 변수에서 읽고, 코드에 넣거나 로그에 남기지 않습니다.
- 쿠키를 함께 보내지 않습니다. 쿠키가 있으면 key 대신 쿠키로 판정합니다.

## 4. 사용자(`X-User-Id`)와 조회 범위

### 4.1 `X-User-Id`는 언제나 필수입니다

두 key 종류 모두, 두 게이트웨이의 **모든 호출(조회 포함)** 에 `X-User-Id`를 보냅니다. "누가 호출했나"를 남기는 값이고, 없거나 형식이 틀리면 400 `INVALID_IDENTITY`입니다.

| key의 tenant | `X-User-Id`에 넣는 값 | 확인 |
| --- | --- | --- |
| 이 서비스 tenant | 이 서비스 사용자의 사번 | 활성 사용자여야 합니다. 모르거나 비활성이면 403 `FORBIDDEN` |
| 다른 tenant | 사번 (시스템 계정은 `svc-…`) | 형식 `^[a-z0-9][a-z0-9._-]{0,63}$`(소문자로 바꾼 뒤)만 봅니다. 이 서비스에서 비활성화된 사번이면 403 |

- 대문자로 보내도 됩니다. 소문자로 바꿔서 씁니다(`E12345`와 `e12345`는 같은 사용자).
- 상위 호출자나 브라우저가 보낸 값을 확인 없이 넘기지 않습니다. 호출 서비스가 직접 인증한 사용자로 만듭니다.

### 4.2 조회 범위는 key 종류가 정합니다

| | 일반키 (`standard`) | 마스터키 (`master`) |
| --- | --- | --- |
| 조회(GET)가 보는 것 | `X-User-Id` 사용자 것만 | tenant 전체 |
| 쿼리 `user_id` | 넣지 않아도 됩니다. 넣으면 `X-User-Id`와 같아야 하고, 다르면 403 `FORBIDDEN` | 넣으면 그 사용자 것으로 거릅니다 |
| 쓰기 (제출·취소·등록·수정·삭제) | `X-User-Id` 사용자로 만들어집니다 | 같습니다 |

- 일반키는 "필터를 안 넣으면 검색 불가"가 아니라 **"항상 자기 것만 검색"** 입니다.
- 남의 자원을 상세 조회하면 일반키는 404입니다. 존재 여부를 알려 주지 않습니다.
- 쓰기 요청의 쿼리 `user_id`는 무시합니다. 쿼리 `tenant_id`는 언제나 무시합니다. tenant는 key가 정합니다.
- `user_id`의 형식이 틀리면 400 `INVALID_IDENTITY`입니다.

### 4.3 프로젝트와 세션 (`X-Project-Id`, `X-Session-Id`)

선택 헤더입니다. 형식은 `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$`이고 `unscoped`는 쓸 수 없습니다.

- 이 서비스 tenant key: 이 서비스의 프로젝트·세션이어야 합니다. `X-User-Id` 사용자가 그 프로젝트의 멤버가 아니거나 세션이 그 프로젝트 것이 아니면 404입니다.
- 다른 tenant key: 호출자가 정한 값으로 보고 형식만 확인합니다.
- `X-Session-Id`는 `X-Project-Id`가 있어야 합니다(없으면 400).
- executor는 두 값을 실행 제출(`POST /executions`) 때만 실행의 `context`로 저장합니다. 다른 경로에서는 형식만 검사하고 쓰지 않으므로, 조회·취소 때는 보내지 않아도 됩니다. pr-batch는 배치 등록(`POST /batches`) 때의 `X-Project-Id`만 저장합니다.

## 5. 넘어가는 헤더와 넘어가지 않는 헤더

### 5.1 요청 헤더

| 헤더 | executor 게이트웨이 | 배치 게이트웨이 |
| --- | --- | --- |
| `X-Api-Key` | 필수 | 필수 |
| `X-User-Id` | 필수 (4장) | 필수 (4장) |
| `X-Project-Id`, `X-Session-Id` | 선택 (4.3) | `X-Project-Id`만, 배치 등록 때만 |
| `Content-Type` | 씀 | 씀 |
| `Idempotency-Key`, `If-Match`, `Accept` | **쓰지 않음** (멱등키는 본문 `idempotency_key`) | 씀 |
| `Range` | **쓰지 않음** (파일은 항상 전체 200) | 해당 없음 |
| `X-Tenant-Id`, `Authorization`, `Cookie`, 그 밖 | 무시 | 무시 |

### 5.2 응답 헤더

| 헤더 | executor 게이트웨이 | 배치 게이트웨이 |
| --- | --- | --- |
| `Content-Type` | 그대로 | 그대로 |
| `ETag` | 그대로 | 그대로 (`If-Match`에 씀) |
| `Location` | 그대로. **executor 기준 경로**(`/api/v1/executions/{id}`)입니다 | 그대로. **pr-batch 기준 경로**(`/api/v1/batches/{id}`)입니다 |
| `Content-Disposition` | 그대로 (아티팩트 파일 이름) | 없음 |
| `Content-Length` | 없음 | 없음 |
| `X-Request-ID` | 요청 ID (문의할 때 전달) | 요청 ID (문의할 때 전달) |

`Location`을 따라갈 때는 앞의 `/api/v1/`을 `/api/v1/executor/` 또는 `/api/v1/batch/`로 바꿉니다. 예: `/api/v1/executions/abc` → `/api/v1/executor/executions/abc`.

## 6. 응답과 오류 형식

성공 응답은 executor·pr-batch의 본문을 그대로 돌려줍니다. 모든 오류는 한 가지 모양입니다. 게이트웨이가 낸 오류와 executor·pr-batch가 낸 오류가 같은 모양입니다.

```json
{"error": {
  "code": "EXECUTION_VERSION_CONFLICT",
  "message": "사람이 읽는 설명 (바뀔 수 있음)",
  "details": [{"location": ["body", "expected_version"], "type": "version_conflict",
               "message": "...", "context": {"expected": 3, "current": 4}}],
  "context": {}
}}
```

- 분기는 **`error.code`** 로 합니다. `message`는 문구가 바뀔 수 있습니다.
- `details`는 항상 있습니다(없으면 `[]`). 잘못된 값마다 하나씩, `location`(첫 원소는 `body`·`header`·`query`·`path`), `type`(바뀌지 않는 snake_case 사유), `context`(한도와 실제 값)가 들어갑니다.
- `context`는 특정 값에 묶이지 않는 정보이고, 없으면 빠집니다.

### 6.1 게이트웨이가 내는 오류

| HTTP | code | 언제 | 재시도 |
| --- | --- | --- | --- |
| 400 | `INVALID_IDENTITY` | `X-User-Id` 없음·형식 오류, `X-Project-Id`·`X-Session-Id` 형식 오류, `X-Session-Id`만 있음, 쿼리 `user_id` 형식 오류 | 아니오 |
| 401 | `LOGIN_REQUIRED` | `X-Api-Key` 없음 | 아니오 |
| 401 | `INVALID_API_KEY` | 모르는 key, 폐기된 key | 아니오 |
| 403 | `FORBIDDEN` | 모르거나 비활성인 사용자, 일반키가 남의 `user_id`로 조회 | 아니오 |
| 404 | `NOT_FOUND` | 문서에 없는 경로·메서드, (이 서비스 tenant) 멤버가 아닌 프로젝트·남의 세션 | 아니오 |
| 413 | `TOO_LARGE` | 요청 본문이 32MB 초과 | 아니오 |
| 502 | `EXECUTOR_UNAVAILABLE` / `BAD_GATEWAY` | executor / pr-batch가 응답하지 않음 | 예, 잠시 뒤 (쓰기는 같은 멱등키로) |
| 504 | `EXECUTOR_TIMEOUT` / `ERROR` | executor(30초) / pr-batch(60초)가 시간 안에 답하지 않음 | 예, 잠시 뒤 (쓰기는 같은 멱등키로) |

### 6.2 executor·pr-batch가 내는 오류

같은 모양으로 그대로 옵니다. 코드 목록은 [executor-gateway.md 7장](executor-gateway.md#7-오류-코드), [batch-gateway.md 7장](batch-gateway.md#7-오류-코드)에 있습니다. 공통으로 알아 둘 것은 이렇습니다.

- 404는 "없음"과 "다른 tenant·다른 사용자 것"을 구분하지 않습니다.
- 409는 요청은 맞지만 지금 상태에서 할 수 없다는 뜻입니다(버전 충돌, 이미 끝남, 멱등키에 다른 본문). 최신 상태를 다시 읽고 판단합니다.
- 422는 요청 값을 고쳐야 통과합니다. 본문의 모르는 필드도 422입니다(`tenant_id`, `context`, `actor` 등을 본문에 넣지 않습니다).
- 503은 일시 장애입니다. 같은 요청(같은 멱등키)으로 잠시 뒤 다시 보냅니다.

## 7. 멱등성과 재시도

- 모든 쓰기에는 멱등키가 있습니다. executor는 본문 `idempotency_key`, pr-batch는 `Idempotency-Key` 헤더입니다. 둘 다 1~255자입니다.
- 작업 하나에 키 하나를 **처음 보내기 전에** 만들고(UUID 권장), 타임아웃·연결 오류·502·503·504 뒤에는 **같은 키, 같은 본문**으로 다시 보냅니다. 처음 결과를 그대로 돌려받습니다.
- 같은 키에 다른 본문을 보내면 409 `IDEMPOTENCY_CONFLICT`입니다.
- 4xx(위 409 제외)는 다시 보내도 같은 결과입니다. 값을 고칩니다.

## 8. 목록과 페이지

- 목록은 `limit`과 `cursor`를 받고 `{"items": [...], "next_cursor": "..." | null}`을 돌려줍니다.
- 다음 페이지는 받은 `next_cursor`를 그대로 `cursor`에 넣습니다. 해석하거나 만들어 보내지 않습니다.
- `next_cursor`가 `null`이면 마지막 페이지입니다. `limit` 범위는 경로마다 다릅니다(레퍼런스 표).

## 9. 크기와 시간 제한

| 항목 | 값 | 넘으면 |
| --- | --- | --- |
| 요청 본문 (게이트웨이) | 32MB | 413 `TOO_LARGE` |
| 요청 본문 (executor) | 30MB | 413 `REQUEST_BODY_TOO_LARGE` |
| 업로드 파일 (pr-batch) | 10MiB | 413 `UPLOAD_TOO_LARGE` |
| executor 응답 대기 | 30초 | 504 `EXECUTOR_TIMEOUT` |
| pr-batch 응답 대기 | 60초 | 504 |

실행 자체는 비동기라 응답 대기 시간과 관계없습니다. 제출하면 바로 202가 오고, 상태는 조회로 확인합니다.

## 10. 문의

- 문의할 때는 응답의 `X-Request-ID`, 실행 ID, 배치·run ID를 함께 알려 주세요.
- 사용자 비활성화는 30초, key 폐기는 60초 안에 반영됩니다.

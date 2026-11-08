# 게이트웨이 API 문서 (executor · 배치)

다른 서비스와 에이전트는 executor와 pr-batch를 직접 부르지 않습니다. **pr-agentic-service가 두 시스템의 유일한 입구(게이트웨이)** 이고, 이 문서는 그 입구로 부를 수 있는 API 전체를 설명합니다. 경로마다 호출 방법(API key, 헤더), 요청 본문, 응답, 오류를 이 문서만 보고 쓸 수 있게 적었습니다.

```
호출자 (서비스·에이전트)
  │  X-Api-Key: pas_live_…   X-User-Id: <사번>
  ▼
pr-agentic-service  /api/v1/executor/{path}  ──▶ executor  /api/v1/{path}
                    /api/v1/batch/{path}     ──▶ pr-batch  /api/v1/{path}
                    /api/v1/batch-reports…   (이 서비스가 직접 처리)
```

## 문서 목록

| 문서 | 읽는 사람 | 내용 |
| --- | --- | --- |
| [00-common.md](00-common.md) | 모두 | 주소, API key(일반키·마스터키), 헤더, 조회 범위, 응답과 오류 형식, 전달되는 헤더, 크기·시간 제한. **두 게이트웨이 공통이라 먼저 읽습니다** |
| [executor-gateway.md](executor-gateway.md) | 사람 | executor 게이트웨이 21개 경로: 개념, 흐름, 경로별 상세 설명, 경로·스키마 레퍼런스 |
| [batch-gateway.md](batch-gateway.md) | 사람 | 배치 게이트웨이 22개 경로와 이 서비스의 배치 API 6개: 개념, 흐름, 경로별 상세 설명, 레퍼런스 |
| [executor-for-agents.md](executor-for-agents.md) | 코딩 에이전트 | executor 게이트웨이 클라이언트를 만들 때 넣는 단일 파일. 규칙(MUST/MUST NOT), 흐름, 예제 코드, 타입 정의 |
| [batch-for-agents.md](batch-for-agents.md) | 코딩 에이전트 | 배치 게이트웨이용 단일 파일 |
| [openapi/executor-gateway.openapi.json](openapi/executor-gateway.openapi.json) | 도구·코딩 에이전트 | executor 게이트웨이의 OpenAPI 3.1 (우리 경로·헤더·오류로 바꾼 것) |
| [openapi/batch-gateway.openapi.json](openapi/batch-gateway.openapi.json) | 도구·코딩 에이전트 | 배치 게이트웨이의 OpenAPI 3.1 |

바이브코딩으로 클라이언트를 만들 때는 `*-for-agents.md`와 같은 이름의 `openapi/*.openapi.json`을 함께 코딩 에이전트에게 줍니다.

## 엔드포인트 현황

| 구분 | 경로 수 | 비고 |
| --- | --- | --- |
| executor 게이트웨이 (`/api/v1/executor/…`) | 21 | API key로 부를 수 있는 경로. 이 밖의 경로는 404 |
| 배치 게이트웨이 (`/api/v1/batch/…`, pr-batch 중계) | 22 | 같음 |
| 이 서비스의 배치 API | 6 | `POST /api/v1/batch/scripts/from-notebook`, `/api/v1/batch-reports` 5개. 우리 tenant 사용자만 |
| 관리자 화면 전용 (SSO 로그인만) | executor 운영 20 + 배치 2 | API key로는 부를 수 없습니다. [executor-gateway.md 8장](executor-gateway.md#8-api-key로-부를-수-없는-경로) |

## 기준과 다시 만들기

- 기준 코드: pr-agentic-service `main`, executor `main`, pr-batch `main` (2026-11-08). 경로 허용 목록은 `src/dtest/api_service/routers/executor.py`, `src/dtest/api_service/routers/batch.py`의 `_ALLOWED`입니다.
- 각 문서의 "레퍼런스"와 "스키마" 절, 그리고 `openapi/*.json`은 `scripts/gateway_docs.py`가 executor·pr-batch의 OpenAPI에서 만듭니다. 손으로 고치지 말고, 두 시스템의 API나 허용 목록이 바뀌면 스크립트를 다시 돌립니다(사용법은 스크립트 첫머리).
- 요청·응답 본문은 executor·pr-batch 것을 그대로 중계합니다. 필드의 뜻은 이 문서에 옮겨 적었고, 두 시스템의 원문 문서는 executor `dev_docs/`, pr-batch `docs/api/`에 있습니다.

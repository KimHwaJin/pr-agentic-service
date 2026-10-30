# pr-agentic-service

사내 데이터 분석 Agent 서비스. User / Project / Session 계층의 채팅 API이자 Agent 실행 진입점입니다. Agent는 LangGraph·LangChain으로 구현했고, 분석 코드는 executor 서비스에서 실행합니다.

- 설계: [docs/design/00-design-draft.md](docs/design/00-design-draft.md)
- 프론트 연동: [docs/api-guide.md](docs/api-guide.md)
- 부하 설계·측정: [docs/load-design.md](docs/load-design.md)
- Workflow 표준: [docs/specs/workflow-1.0](docs/specs/workflow-1.0/workflow_spec_1.0.md)

## 구조

```text
src/
  main.py        진입점. RUN_MODE=all(기본) | api | worker
  api_service/   FastAPI 라우터, SSO(로그인·세션·CSRF), 요청/응답 스키마. agent를 import하지 않음
  agent/         LangGraph 그래프, persona middleware, 도구, 코드 조립, 리포트 작성
    prompts/     Agent 프롬프트(.md) — main, analyst, reporter
  worker/        run 스케줄러(lease·재개), executor 이벤트 consumer, 배치 리포트 작업, 프로젝트 메모리 정리
  core/          설정, DB 모델, 이벤트 버스, executor 클라이언트, 메모리·Workflow 서비스, skill/tool 카탈로그
assets/          skills/(분석 skill .md) tools/(분석 함수 .py) knowledge/(도메인 지식 .md) — 현재 mock
migrations/      Alembic
web/dev/         테스트 콘솔(로컬·dev에서 /dev/)
scripts/         mock_llm.py(게이트웨이 대역), smoke_e2e.py(종단 점검)
```

의존 방향: `api_service → core`, `worker → agent → core`.

## 동작 요약

- 컨테이너 하나에 API와 worker가 함께 돕니다. run은 PostgreSQL 큐에서 lease로 가져가 실행하고, 사용자 확인(HITL)이나 executor 결과를 기다리는 동안에는 Pod를 점유하지 않습니다. Pod가 죽으면 다른 Pod가 LangGraph 체크포인트에서 이어 갑니다.
- 메인 Agent가 대화하다가 필요하면 분석 담당(analyst)으로 넘깁니다. analyst는 skill을 읽고 Workflow 1.0 형식으로 계획 후보를 만들어 승인을 받은 뒤, tool 함수(docstring 제거) + 호출 코드를 executor MULTI 실행에 Step으로 보냅니다. 조건부 tool은 앞 결과를 보고 판단해 같은 커널에 이어 실행합니다.
- 분석이 끝나면 노트북을 확정(finalize)하고 리포트를 executor Artifact로 저장합니다.
- 배치(pr-batch) 실행이 성공하면 worker가 배치 리포트 Agent로 결과를 분석해 리포트를 저장합니다. 같은 배치의 이전 실행 요약을 기억해 비교합니다(`/api/v1/batch-reports`).
- 프로젝트 공유 메모리는 네 섹션(Overview, Preferences, Core Interests, Key Events)의 짧은 Markdown으로, 모든 대화의 프롬프트에 들어갑니다. 사용자가 "기억해줘"라고 하면 Agent가 바로 저장하고, 대화가 잠잠해지면(기본 3분, 또는 5턴) worker가 사용자가 말한 지속적인 사실·선호를 한 번의 LLM 호출로 정리해 넣습니다. 화면·API에서 섹션을 고치고 이력에서 되돌릴 수 있습니다([docs/api-guide.md](docs/api-guide.md) 6장).

## Docker Compose로 실행

shared-infra(postgres, redis)와 executor compose가 떠 있는 상태에서:

```bash
docker compose up -d --build
```

- http://localhost:8080/dev/ 테스트 콘솔, http://localhost:8080/docs API 문서
- 서비스 DB(`agentic`)는 `db-init`이 공용 Postgres에 없으면 만듭니다.
- executor 공유 볼륨은 `../executor/shared_dir`(`EXECUTOR_SHARED_DIR`로 변경), LLM은 `model.frodo.com` 게이트웨이를 씁니다.
- `assets/`와 `src/agent/prompts/`는 마운트되어 있어 수정하면 재빌드 없이 다음 요청부터 반영됩니다.
- 게이트웨이 대신 mock LLM: `.env`에 `LLM_BASE_URL=http://mock-llm:8001/v1`을 넣고 `docker compose --profile mock up -d`
- 로컬 설정은 `APP_ENV`를 비운 채 공통 `config.yml` 위에 `docker-compose.yml`의 `environment:` 값(DB·executor 주소, dev SSO, 모델 목록 등)이 덮습니다. compose 옆 `.env`는 `APP_PORT`, `PG_PASSWORD`, `LLM_API_KEY` 같은 값만 채웁니다.

## 로컬 실행

필요: PostgreSQL(pgvector), Redis, executor 스택(`../executor`), LLM 게이트웨이 또는 mock.

```bash
cp .env.example .env   # DATABASE_URL, EXECUTOR_* 경로 등 수정
uv sync
uv run uvicorn mock_llm:app --app-dir scripts --port 8001   # 게이트웨이 대신 (선택)
uv run uvicorn main:app --app-dir src --port 8080
```

- executor PV를 마운트할 수 없을 때(executor는 원격 k8s, 서비스는 로컬): `cp .env.testmode.example .env`. `EXECUTOR_IO_MODE=api` 테스트 모드로 코드는 INLINE으로 보내고 결과는 executor 노트북 API로 읽습니다(채팅 이미지 출력은 보이지 않음, 운영 미사용).
- 테스트 콘솔: http://localhost:8080/dev/ (`SSO_ALLOWED_RETURN_ROOTS=["/", "/dev"]`, `SSO_ADAPTER=dev`)
- 종단 점검: `uv run python scripts/smoke_e2e.py`
- 단위 테스트: `uv run pytest`
- 정적 검사: `uv run ruff format`, `uv run ruff check`, `uv run ty check` (줄 길이 79, 설정은 `pyproject.toml`)
- 부하 측정: `uv run python scripts/loadtest.py --users 100 --turns 3`

기동 시 Alembic, LangGraph checkpointer/store 테이블, Workflow 벡터 인덱스가 advisory lock 아래 한 번 적용됩니다(`AUTO_MIGRATE=false`로 끌 수 있음).

## 운영 연결 지점

- **사내 SSO**: `SSO_ADAPTER=company`, `SSO_ADAPTER_FACTORY=company_sso:create_sdk`. 초안 `src/company_sso.py`의 SDK import만 폐쇄망에서 실제 경로로 바꿉니다. 연결 확인 순서와 실패 시 볼 로그는 [docs/specs/sso-check.md](docs/specs/sso-check.md).
- **LLM**: `llm_base_url`, `llm_api_key`, `llm_enable_thinking`, 그리고 사용자에게 보여 줄 모델 목록 `models`(게이트웨이 모델 이름, 표시 이름, `default: true` 하나, 이미지 입력 가능 여부, 모델별 요청 파라미터 `params` 예: `reasoning_effort`). 목록에 적힌 모델만 씁니다.
- **임베딩**(워크플로우 검색용): `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMS`(HNSW 인덱스는 2,000차원 이하).
- **프로젝트 메모리**: 프로젝트마다 주제(최대 6개, 콘솔에서 편집) 한도 합계 `MEMORY_TOTAL_MAX_CHARS`(기본 2200, 주제별 한도는 주제에 저장), 백그라운드 정리 `MEMORY_WORKER_ENABLED`, `MEMORY_WORKER_QUIET_SECONDS`, `MEMORY_WORKER_MAX_TURNS`, `MEMORY_WORKER_MAX_INPUT_TOKENS`, `MEMORY_WORKER_CONCURRENCY`. 예전 항목형 메모리는 기동 시(`AUTO_MIGRATE`) 기본 주제로 옮겨지며, 끈 환경에서는 `uv run python scripts/migrate_project_memory.py`.
- **skill/tool**: `SKILLS_ROOT`, `TOOLS_ROOT`, `KNOWLEDGE_ROOT`(기본은 레포의 `assets/`). 파일이 바뀌면 다음 run부터 반영됩니다.
- **executor**: `EXECUTOR_BASE_URL`, 우리 key `EXECUTOR_API_KEY`(stg·prd 필수), 시스템 화면의 runtime·maintenance용 운영 key `EXECUTOR_ADMIN_API_KEY`(key 모드에서 비우면 그 화면은 503), 결과 PVC 마운트 경로 `EXECUTOR_RESULT_ROOT`(executor의 SHARED_STORAGE_ROOT).
- **서비스 간 인증**: 브라우저는 SSO 쿠키, 다른 서비스·에이전트는 우리가 발급한 `X-Api-Key` + `X-User-Id`(시스템 화면 "API 키"에서 발급). executor·pr-batch는 우리 서비스를 거쳐서만 부릅니다(`/api/v1/executor/...`, `/api/v1/batch/...`). `AUTH_MODE=header`(local·dev 전용)는 key 없이 `X-User-Id`를 믿습니다. 자세한 규칙은 [docs/specs/service-auth.md](docs/specs/service-auth.md).
- **설정 파일**: 배포는 `APP_ENV`(dev, stg, prd)로 `config.{APP_ENV}.yml`을 고릅니다(이미지에 포함). `config.yml`은 모든 환경의 공통값(이미지에 포함)이고, 로컬은 `APP_ENV`를 비워 두고 `config.yml` 위에 compose 환경변수나 `.env`로 로컬 값을 덮습니다. 우선순위는 환경변수 > `.env` > `config.{APP_ENV}.yml` > `config.yml`입니다. 환경마다 다른 값(DB·Redis·executor·pr-batch 주소, 프론트 주소와 CORS, `COOKIE_SECURE`, 관리자 ID, LLM 키, 모델 목록)만 `config.{APP_ENV}.yml`에 있고, 나머지 설정 키는 모두 `config.yml`에 기본값과 함께 적혀 있습니다. 상대 경로(`SKILLS_ROOT` 등)는 레포 루트 기준입니다. 자세한 규칙은 [docs/design/03-config.md](docs/design/03-config.md).
- **JupyterLab 링크**: `NOTEBOOK_LAB_BASE_URL`(Lab 서버 주소), Lab 루트가 Jupyter 공유 저장소 루트와 다르면 `NOTEBOOK_LAB_PATH_PREFIX`.
- **pr-batch**: `BATCH_BASE_URL`, 우리 key `BATCH_API_KEY`(stg·prd 필수, relay + admin). 배치 리포트는 `BATCH_REPORT_MODEL`(비우면 기본 모델), `BATCH_REPORT_COLLECT_TIMEOUT_SECONDS`, `BATCH_REPORT_MEMORY_RUNS`.
- **로깅**: 사내 HCP 라이브러리가 설치돼 있으면 `hcp.framework.logger.init_logger()`가 맡고(사내 `logger.yml`을 스스로 읽음), 없으면 루트의 `logger.yml`을 표준 `logging.dictConfig`로 적용합니다(`src/core/logging_setup.py`, pr-batch와 같은 구조). 사내로 옮길 때는 HCP 의존성과 사내용 `logger.yml`만 바꾸면 됩니다. 로그 레벨도 `logger.yml`에서 바꿉니다.
- 배포 예시: [deploy/kubernetes/deployment.yml](deploy/kubernetes/deployment.yml)

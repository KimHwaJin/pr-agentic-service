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
  worker/        run 스케줄러(lease·재개), executor 이벤트 consumer, 배치 리포트 작업
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

## 로컬 실행

필요: PostgreSQL(pgvector), Redis, executor 스택(`../executor`), LLM 게이트웨이 또는 mock.

```bash
cp .env.example .env   # DATABASE_URL, EXECUTOR_* 경로 등 수정
uv sync
uv run uvicorn mock_llm:app --app-dir scripts --port 8001   # 게이트웨이 대신 (선택)
uv run uvicorn main:app --app-dir src --port 8080
```

- 테스트 콘솔: http://localhost:8080/dev/ (`SSO_ALLOWED_RETURN_ROOTS=["/", "/dev"]`, `SSO_ADAPTER=dev`)
- 종단 점검: `uv run python scripts/smoke_e2e.py`
- 단위 테스트: `uv run pytest`
- 부하 측정: `uv run python scripts/loadtest.py --users 100 --turns 3`

기동 시 Alembic, LangGraph checkpointer/store 테이블, Workflow 벡터 인덱스가 advisory lock 아래 한 번 적용됩니다(`AUTO_MIGRATE=false`로 끌 수 있음).

## 운영 연결 지점

- **사내 SSO**: `SSO_ADAPTER=company`, `SSO_ADAPTER_FACTORY=company_sso:create_sdk`. 폐쇄망에서 `src/company_sso.py`를 아래처럼 추가합니다.
  ```python
  from your_private_module import SSO

  def create_sdk(request, callback_url):
      return SSO(request)  # request는 Flask 호환 뷰(args, cookies, environ, url)
  ```
- **LLM**: `LLM_BASE_URL`, `LLM_MODELS`(별칭 → 모델명), `LLM_ENABLE_THINKING`.
- **임베딩**: `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMS`(HNSW 인덱스는 2,000차원 이하).
- **skill/tool**: `SKILLS_ROOT`, `TOOLS_ROOT`, `KNOWLEDGE_ROOT`(기본은 레포의 `assets/`). 파일이 바뀌면 다음 run부터 반영됩니다.
- **executor**: `EXECUTOR_BASE_URL`, 공유 PVC 마운트 경로 `EXECUTOR_INPUT_ROOT`(executor의 INPUT_STORAGE_ROOT), `EXECUTOR_RESULT_ROOT`(SHARED_STORAGE_ROOT).
- **pr-batch**: `BATCH_BASE_URL`, `BATCH_JWT_SECRET`(pr-batch의 BATCH_AUTH_SECRET), `BATCH_REPORT_JWT_SECRET`.
- 배포 예시: [deploy/kubernetes/deployment.yaml](deploy/kubernetes/deployment.yaml)

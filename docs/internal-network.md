# 내부망(gaia 템플릿) 반영

내부망은 사내 코드 템플릿(gaia) 구조를 따라야 합니다. 이 브랜치(`internal/gaia`)는 그 구조에 맞춘 버전이고, `main`은 기존 구조를 유지합니다. 두 버전을 나란히 작업합니다.

## 템플릿과 만나는 곳

| 템플릿 파일 | 이 서비스가 하는 일 |
| --- | --- |
| `app.py` | `GaiaService()` 다음, `main()` 전에 `attach(gaia_service.app)` 한 줄. 레포의 `app.py`가 그 형태 그대로입니다 |
| `src/router.py` | `users` 예제 include만 지웁니다. 우리 라우터는 `attach`가 붙입니다 |
| `src/server.py`, `src/config.py`, `src/gaia/`, `src/common/`, `src/lib/`, `src/workflows/`, `src/routers/` | 손대지 않음 |
| `config.yml`, `config.{dev,stg,prd}.yml`, `logger.yml` | 우리 설정 그대로. 템플릿 고정값 `PORT`, `PROJECT_NAME`, `SERVICE_NAME`만 추가 |

서비스 코드는 전부 `src/dtest/`에 있습니다. 내부망 레포에는 `src/dtest/`, `app.py`(또는 템플릿 `app.py`에 위 한 줄), `tests/`, `scripts/`, `deploy/`, `docs/`, `keys/`, `Dockerfile`, `pyproject.toml`, `uv.lock`, 설정 yml을 가져갑니다.

## 시작과 종료

`GaiaService.main()`은 앱의 lifespan을 자기 것으로 바꾸므로 lifespan이나 startup 훅은 쓸 수 없습니다. `attach`는 ASGI 미들웨어 `DtestLifespan`을 붙여, uvicorn의 lifespan 메시지를 먼저 받아 DB/Redis 연결과 worker를 띄우고(종료 때는 반대로) 메시지를 gaia 쪽으로 넘깁니다(`src/dtest/entry.py`).

- uvicorn은 startup이 끝나야 포트를 열기 때문에 `/api/admin/appReady`(gaia 제공)는 우리 준비가 끝난 뒤에야 응답합니다. k8s readiness/liveness probe는 이 경로를 씁니다.
- 우리 startup이 실패하면 `lifespan.startup.failed`를 보내 프로세스가 종료됩니다(재시작은 k8s가 함). 그냥 예외를 던지면 uvicorn이 "lifespan 미지원"으로 보고 서비스 없이 떠 버리기 때문입니다.
- `RUN_MODE=all | api | worker`는 그대로입니다.

## 앱을 함께 쓰는 부분

- 경로: 우리는 `/api/v1/...`, `/view/artifacts/{id}`, `/dev`(local/dev만). gaia는 `/workflows`, `/{workflow}/gaia/completion`, `/{workflow}/api/completion`, `/api/common/...`, `/api/admin/appReady`. 겹치지 않습니다.
- 에러 응답: 우리 형식(`{"detail", "code"}`)은 우리 경로에만 적용되고, 다른 경로는 원래 핸들러(gaia가 등록한 것 또는 FastAPI 기본)를 씁니다(`src/dtest/api_service/errors.py`).
- CORS: gaia가 회사 도메인을 허용하므로 내부망 `config.{env}.yml`의 `CORS_ORIGINS`는 비워 둡니다(비면 우리 CORS 미들웨어를 붙이지 않음).
- 로깅: gaia/HCP가 맡습니다. `attach`는 로깅 설정을 하지 않습니다.
- Phoenix: gaia가 `PHOENIX_ENDPOINT`, `PHOENIX_API_KEY`로 등록합니다. 우리는 에이전트 단계 계측만 켜고 `PHOENIX_COLLECTOR_ENDPOINT`는 쓰지 않습니다([phoenix-tracing.md](phoenix-tracing.md)).

## 사용자가 채울 것

- `pyproject.toml`: HCP 라이브러리와 gaia 기본 requirements를 dependencies에 추가하고 `uv lock`. fastapi, pydantic, uvicorn 버전이 부딪치면 우리 쪽 하한을 낮춥니다. FastAPI는 0.137 미만으로 묶여 있습니다: 0.137부터 include한 라우터가 `.path` 없는 `_IncludedRouter`가 되어 gaia의 Instrumentor(prometheus-fastapi-instrumentator)가 요청마다 `AttributeError`를 냅니다.
- `config.yml`: `PORT`(8080, Dockerfile EXPOSE와 deployment의 containerPort와 같게), `PROJECT_NAME`, `SERVICE_NAME`.
- 이미지 빌드: `docker build --build-arg BASE_IMAGE=<사내 uv + Python 3.11 이미지> --build-arg APP_ENV=prd .`
- 사내 SSO: `src/dtest/company_sso.py`의 `create_sdk` (README 참고).

## 실행

- 내부망(Windows 개발 PC 포함): 레포 루트에서 `uv run python app.py`
- 사외: `uv run python -m src.dtest.local`(레포 루트에서, 포트 8080 또는 `PORT`) 또는 `docker compose up -d --build`. gaia 없이 일반 FastAPI에 같은 `attach`를 붙이고 `/api/admin/appReady`도 흉내 냅니다.
- Windows 이벤트 루프: psycopg async는 Windows 기본 루프(Proactor)에서 안 돌고, uvicorn 0.36+는 Windows에서 스스로 Proactor를 고릅니다. gaia가 `uvicorn.run()`을 `loop` 인자 없이 부르므로 `attach`가 그 전에 uvicorn의 루프 선택을 Selector로 바꿉니다(`src/dtest/winloop.py`, 다른 OS에서는 아무것도 안 함). uvicorn CLI로 직접 띄울 때는 앱을 읽기 전에 루프가 정해지므로 `--loop asyncio:SelectorEventLoop`을 붙여야 합니다.

## 두 브랜치 같이 가기

- 기능 작업은 어느 쪽에서 해도 됩니다. `main`의 변경은 `git merge main`으로 이 브랜치에 가져옵니다. 파일을 `git mv`로 옮겨 두어 git이 이동을 따라가므로, 대부분 충돌 없이 `src/dtest/` 아래로 들어옵니다.
- 새 파일을 `main`에 만들면 merge 뒤 `src/dtest/` 아래로 옮기고 import를 `src.dtest.`로 고쳐야 합니다. `tests/test_entry.py`의 import 검사가 빠진 곳을 알려 줍니다.
- Python은 이 브랜치만 3.11입니다(내부망 이미지). `main`에서 3.12 전용 문법(`def f[T]()` 같은)을 쓰면 merge 때 고쳐야 합니다.

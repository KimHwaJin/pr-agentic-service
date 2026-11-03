# Phoenix 트레이스 (선택 기능, 언제든 제거 가능)

에이전트의 LangChain/LangGraph 실행(모델 호출, 도구 호출, 미들웨어 단계)을 OpenTelemetry로 Phoenix에 보냅니다. 화면에서 턴마다 어떤 프롬프트가 들어가고 어떤 도구가 어떤 인자로 불렸는지 볼 수 있습니다.

## 켜기

다른 설정과 똑같이 읽습니다(환경변수 > `.env` > `config.{APP_ENV}.yml` > `config.yml`). 이름은 gaia 템플릿과 같습니다.

| 키 | 내용 |
| --- | --- |
| `PHOENIX_ENDPOINT` | Phoenix 주소. 비어 있으면 아무것도 하지 않습니다(기본 꺼짐). |
| `PHOENIX_API_KEY` | Phoenix API 키(비밀이라 `.env`나 Deployment env에). |
| `SERVICE_ID` | Phoenix 프로젝트 이름. 기본값 `pr-agentic-service`. |

로컬 예시(`.env`, 커밋되지 않음):

```
PHOENIX_ENDPOINT=http://phoenix.frodo.com
PHOENIX_API_KEY=<Phoenix API key>
SERVICE_ID=pr-agentic-service-local
```

- `uv run`/`uv sync`가 `phoenix` 그룹을 기본으로 설치합니다(`pyproject.toml`의 `default-groups`). 시작 로그에 `phoenix_tracing_on endpoint=... project=...`가 나오면 켜진 것입니다.
- 사외 로컬에서 `phoenix.frodo.com`은 compose의 `extra_hosts`로 `10.250.110.100`에 연결됩니다. Docker 없이(`scripts/run_local_https.ps1` 등) 띄우면 hosts 파일에 `10.250.110.100  phoenix.frodo.com`을 넣습니다.
- OTLP HTTP(`<endpoint>/v1/traces`)로 보냅니다. gRPC(4317)는 쓰지 않습니다. 보내기는 백그라운드 배치라 요청 처리 시간에 영향이 없습니다.
- 트레이스의 `session.id`가 우리 세션 ID라 Phoenix의 Sessions 화면에서 대화 단위로 묶여 보입니다. 세션 제목 생성 같은 그래프 밖 호출은 세션 없이 따로 보입니다.

## gaia 템플릿과의 관계

gaia는 자기 워크플로우 파일 안에서 Phoenix를 등록하고, 그 워크플로우가 실행될 때만 트레이스됩니다. 우리 run은 API와 워커가 실행하므로 거기에 잡히지 않습니다. 그래서 같은 키로 우리가 직접 provider를 만들어 등록합니다(전역 provider는 건드리지 않음). LangChain 계측기는 프로세스에 하나라서, 누가 먼저 켰으면 나중 쪽은 건너뜁니다(`phoenix_tracing_skipped` 경고).

## 구성 요소 (제거할 때 이것만 지우면 됨)

| 위치 | 내용 |
| --- | --- |
| `src/tracing_phoenix.py` | 계측 코드 전부 (`setup()`) |
| `src/main.py` | `import tracing_phoenix` 한 줄, `tracing_phoenix.setup(settings)` 한 줄 |
| `src/core/config.py` | `phoenix_endpoint`, `phoenix_api_key`, `service_id` 세 필드 (`config.example.yml` 15절) |
| `pyproject.toml` | `[dependency-groups]`의 `phoenix = [...]`, `[tool.uv]`의 `default-groups`, 이후 `uv lock` |
| `Dockerfile` | `uv sync`의 `--group phoenix` 두 군데 |
| `docker-compose.yml` | `PHOENIX_ENDPOINT`, `PHOENIX_API_KEY`, `SERVICE_ID` 세 줄, `phoenix.frodo.com` extra_hosts 한 줄 |
| `.env` | 위 세 줄 (로컬에만 있음) |
| `tests/test_tracing_phoenix.py` | 테스트 |
| 이 문서 | `docs/phoenix-tracing.md` |

다른 코드는 Phoenix를 모릅니다.

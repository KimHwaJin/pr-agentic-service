# Phoenix 트레이스 (선택 기능, 언제든 제거 가능)

에이전트의 LangChain/LangGraph 실행(모델 호출, 도구 호출, 미들웨어 단계)을 OpenTelemetry로 Phoenix에 보냅니다. 화면에서 턴마다 어떤 프롬프트가 들어가고 어떤 도구가 어떤 인자로 불렸는지 볼 수 있습니다.

## 켜기 (로컬)

레포 루트 `.env`(커밋되지 않음)에 넣고 `docker compose up -d --build app`:

```
PHOENIX_COLLECTOR_ENDPOINT=http://phoenix.frodo.com
PHOENIX_API_KEY=<Phoenix API key>
PHOENIX_PROJECT_NAME=pr-agentic-service-local
```

- `phoenix.frodo.com`은 compose의 `extra_hosts`로 `10.250.110.100`에 연결됩니다.
- `PHOENIX_COLLECTOR_ENDPOINT`가 비어 있으면 아무것도 하지 않습니다(기본 꺼짐).
- OTLP HTTP(`<endpoint>/v1/traces`)로 보냅니다. gRPC(4317)는 쓰지 않습니다. 보내기는 백그라운드 배치라 요청 처리 시간에 영향이 없습니다.
- 트레이스의 `session.id`가 우리 세션 ID라 Phoenix의 Sessions 화면에서 대화 단위로 묶여 보입니다. 세션 제목 생성 같은 그래프 밖 호출은 세션 없이 따로 보입니다.

## 내부망 (gaia 템플릿)

gaia 템플릿이 `PHOENIX_ENDPOINT`, `PHOENIX_API_KEY`로 Phoenix를 직접 등록합니다. 그래서 내부망에서는 `PHOENIX_COLLECTOR_ENDPOINT`를 넣지 않습니다(넣으면 우리 provider가 따로 생겨 이중 등록).

`PHOENIX_ENDPOINT`가 있으면 `setup()`은 등록은 하지 않고 LangChain/LangGraph 계측만, 아직 아무도 안 켰을 때 전역 provider에 켭니다. gaia가 먼저 켰으면 건너뛰고, 우리가 먼저 켜면 gaia 쪽이 건너뜁니다(instrumentor가 싱글턴). gaia가 provider를 나중에 등록해도 span이 그쪽으로 갑니다.

## 구성 요소 (제거할 때 이것만 지우면 됨)

| 위치 | 내용 |
| --- | --- |
| `src/dtest/tracing_phoenix.py` | 계측 코드 전부 (`setup()`) |
| `src/dtest/entry.py` | `tracing_phoenix` import 한 줄, `tracing_phoenix.setup()` 한 줄 |
| `pyproject.toml` | `[dependency-groups]`의 `phoenix = [...]` (arize-phoenix-otel, openinference-instrumentation-langchain), 이후 `uv lock` |
| `Dockerfile` | `uv sync`의 `--group phoenix` 두 군데 |
| `docker-compose.yml` | `PHOENIX_*` 환경변수 세 줄, `phoenix.frodo.com` extra_hosts 한 줄 |
| `.env` | `PHOENIX_*` 세 줄 (로컬에만 있음) |
| 이 문서 | `docs/phoenix-tracing.md` |

다른 코드는 Phoenix를 모릅니다. 위를 지우고 `uv lock`만 다시 하면 원래대로 돌아갑니다.

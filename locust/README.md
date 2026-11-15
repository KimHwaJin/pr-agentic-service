# 부하 테스트 (Locust)

통합 테스트 OPS-08 "동시 사용자 부하"를 수행하는 도구입니다. 서비스 코드와 따로 떨어져 있고 이미지에 들어가지 않습니다. 부하를 거는 PC에서 실행하고, 대상 서비스에는 키 호출(`X-Api-Key` + `X-User-Id`)로 들어가므로 SSO 로그인이 필요 없습니다.

## 무엇을 하는가

가상 사용자 한 명이 사번 하나로 아래 동작을 1~5초 간격으로 되풀이합니다. 괄호는 기본 비율이고, 0인 동작은 하지 않습니다.

| 동작 | 내용 |
| --- | --- |
| 가벼운 조회 (6) | 내 정보, 세션 목록 조회 |
| 대화 턴 (3) | 새 세션에 대화 한 줄을 보내고 run이 끝날 때까지 2초마다 상태를 조회 |
| 분석 턴 (1) | 새 세션에 분석 요청을 보내고, 계획 승인과 코드 승인 질문에 스스로 "승인"으로 답하며 끝까지 진행. executor에서 코드가 실제로 실행됨 |
| executor 실행 (0) | LLM 없이 코드 실행 하나를 executor에 바로 제출(`POST /executor/executions`)하고 끝날 때까지 상태 조회. executor만 따로 재는 용도 |
| 배치 실행 (0) | LLM 없이 그 사번의 배치 중 이름이 `load-`로 시작하는 것을 "지금 실행"하고 실행이 끝날 때까지 상태 조회. pr-batch와 executor를 재는 용도 |

executor와 배치가 주 대상이면 아래처럼 비율만 바꿔 돌립니다.

```powershell
# executor만
$env:LOAD_READ_WEIGHT=0; $env:LOAD_CHAT_WEIGHT=0; $env:LOAD_ANALYSIS_WEIGHT=0; $env:LOAD_EXECUTOR_WEIGHT=1; $env:LOAD_BATCH_WEIGHT=0
# 순수 코드 실행만, 쉬지 않고 빠르게: 한 사용자가 "제출 1건 + 상태 조회 여러 건"을 계속 되풀이
$env:LOAD_EXECUTOR_CODE="print(1 + 1)"; $env:LOAD_WAIT_MIN_SECONDS=0; $env:LOAD_WAIT_MAX_SECONDS=0; $env:LOAD_POLL_SECONDS=0.5
# 배치만
$env:LOAD_READ_WEIGHT=0; $env:LOAD_CHAT_WEIGHT=0; $env:LOAD_ANALYSIS_WEIGHT=0; $env:LOAD_EXECUTOR_WEIGHT=0; $env:LOAD_BATCH_WEIGHT=1
```

턴이 끝나면 만든 세션을 지웁니다. 답할 수 없는 질문(입력 칸이 여러 개인 질문)이 나오거나 제한 시간(기본 900초)을 넘기면 그 run을 취소하고 실패로 셉니다.

## 준비

1. Python 3.10 이상이 있는 PC에서 설치합니다.
   ```powershell
   pip install -r locust\requirements.txt
   ```
2. `locust\users.example.csv`를 `locust\users.csv`로 복사하고 테스트용 사번을 한 줄에 하나씩 적습니다. **우리 서비스에 한 번 이상 로그인한 사번만** 됩니다(아니면 403). 가상 사용자 수가 사번 수보다 많으면 사번을 돌려 씁니다.
3. 우리 테넌트 표준 키를 환경 변수로 넣습니다. 키는 파일에 적거나 커밋하지 않습니다.
   ```powershell
   $env:LOAD_API_KEY = "<우리 테넌트 표준 키 원문>"
   ```

4. 분석 턴에서 계획이 값을 넣으라고 하는 입력 칸이 있으면 그 값을 미리 정해 줍니다. 이름은 파라미터 이름(또는 `<단계>.<tool>.<파라미터>` 키)입니다. 값을 주지 않은 필수 칸이 나오면 그 턴은 취소되고, 실패 사유에 `plan needs LOAD_PLAN_INPUTS for <키> (<타입>)`으로 필요한 칸이 나오므로 한 명으로 먼저 돌려 이름을 확인합니다.
   ```powershell
   $env:LOAD_PLAN_INPUTS = '{"column": "nce", "start_date": "2026-01-01"}'
   ```
5. 배치 실행을 쓰려면 테스트 사번마다 이름이 `load-`로 시작하는 배치를 하나 이상 미리 등록해 둡니다(화면의 **배치**에서 BAT-02 방법대로, 예약은 꺼 둬도 됨). 그런 배치가 없는 사번은 배치 실행을 건너뜁니다.

## 설정 파일로 실행하기

환경 변수를 하나씩 넣는 대신 설정 파일 하나로 실행할 수 있습니다.

1. `locust\config.example.yml`을 `locust\config.yml`로 복사해 값을 고칩니다. 대상 주소(`LOAD_HOST`), 사용자 수, 시간, 비율까지 모두 들어 있습니다. `config.yml`은 커밋되지 않습니다.
2. 실행합니다. 주소와 사용자 수를 파일에서 읽으므로 `--host`, `-u`, `-r`, `-t`가 필요 없습니다.
   ```powershell
   locust -f locust\locustfile.py --headless --html report.html --csv result
   ```
3. 상황별 파일을 여러 개 두고 골라 쓸 수 있습니다(이름이 `config`로 시작하는 `.yml`은 커밋되지 않음).
   ```powershell
   $env:LOAD_CONFIG = "locust\config.executor.yml"
   ```

값을 읽는 순서는 환경 변수, 설정 파일, 기본값입니다. 키는 파일에 적어도 되고, 파일에는 비워 두고 `$env:LOAD_API_KEY`로만 줘도 됩니다. 파일에 모르는 이름이 있으면 시작할 때 알려 주고 멈춥니다. `LOAD_USERS`나 `LOAD_STEP_USERS`를 주면 사용자 수는 파일이 정하므로 `-u`, `-r`과 화면에서 넣는 수는 쓰이지 않습니다.

## 실행

저장소 루트에서 실행합니다.

화면으로 보면서 실행:
```powershell
locust -f locust\locustfile.py --host https://<host>
```
브라우저에서 `http://localhost:8089`를 열어 사용자 수와 초당 증가 수를 넣고 시작합니다.

화면 없이 실행하고 보고서 남기기(예: 30명, 초당 2명씩 증가, 10분):
```powershell
locust -f locust\locustfile.py --host https://<host> --headless -u 30 -r 2 -t 10m --html report.html --csv result
```

처음에는 `-u 1 -t 2m`으로 한 명만 돌려 실패가 0인지 확인한 뒤 수를 올립니다.

**어느 수준까지 버티는지 찾기(계단식)**: 사용자 수를 일정 시간마다 올려 가며, 실패가 생기거나 시간이 급히 늘어나는 단계를 찾습니다. `-u`, `-r`, `-t` 없이 실행합니다.
```powershell
$env:LOAD_STEP_USERS = 10      # 한 단계에 늘릴 사용자 수
$env:LOAD_STEP_SECONDS = 300   # 한 단계의 길이(초)
$env:LOAD_MAX_USERS = 150      # 여기까지 올리고 한 단계 더 유지한 뒤 끝냄
locust -f locust\locustfile.py --host https://<host> --headless --html report.html --csv result --csv-full-history
```
`result_stats_history.csv`에 시각별 사용자 수와 응답 시간, 실패 수가 남으므로 어느 단계에서 꺾였는지 볼 수 있습니다.

## 설정 (환경 변수)

| 이름 | 기본값 | 뜻 |
| --- | --- | --- |
| `LOAD_CONFIG` | `locust/config.yml`(있으면) | 읽을 설정 파일. 환경 변수로만 줌 |
| `LOAD_HOST` | (비움) | 대상 주소. 명령의 `--host`가 있으면 그쪽이 우선 |
| `LOAD_USERS` / `LOAD_SPAWN_RATE` / `LOAD_RUN_SECONDS` | 0 / 1 / 0 | 고정 부하: 사용자 수, 초당 증가 수, 수행 시간(초, 0이면 멈출 때까지). `LOAD_USERS`가 0이면 `-u`, `-r`, `-t`를 따름 |
| `LOAD_API_KEY` | (필수) | 우리 테넌트 표준 키 원문 |
| `LOAD_USERS_FILE` | `locust/users.csv` | 사번 목록 파일 |
| `LOAD_API_PREFIX` | `/api/v1` | API 경로 앞부분 |
| `LOAD_MODEL` | (비움) | 쓸 모델 이름. 비우면 서비스 기본 모델 |
| `LOAD_CHAT_PROMPT` | 안녕, 오늘 할 수 있는 분석을 알려줘 | 대화 턴에 보낼 문장 |
| `LOAD_ANALYSIS_PROMPT` | nce 데이터 불러와서 기술통계 보여줘 | 분석 턴에 보낼 문장 |
| `LOAD_QUESTION_ANSWER` | 기본값으로 진행해줘 | 선택지 없는 질문에 보낼 답 |
| `LOAD_READ_WEIGHT` / `LOAD_CHAT_WEIGHT` / `LOAD_ANALYSIS_WEIGHT` | 6 / 3 / 1 | 조회, 대화, 분석의 비율. 0이면 그 동작을 하지 않음 |
| `LOAD_EXECUTOR_WEIGHT` / `LOAD_BATCH_WEIGHT` | 0 / 0 | executor 실행, 배치 실행의 비율 |
| `LOAD_PLAN_INPUTS` | `{}` | 분석 계획의 빈 입력 칸에 넣을 값(JSON). 이름은 파라미터 이름 또는 칸의 키 |
| `LOAD_EXECUTOR_CODE` | 10초 쉬고 `print(1 + 1)` | executor 실행에 보낼 코드. 실행 하나가 슬롯을 잡는 시간을 이 코드로 정함 |
| `LOAD_EXECUTOR_PROFILE` | default | executor 런타임 프로필 |
| `LOAD_BATCH_NAME_PREFIX` | `load-` | 배치 실행에 쓸 배치 이름의 앞부분 |
| `LOAD_STEP_USERS` / `LOAD_STEP_SECONDS` / `LOAD_MAX_USERS` | 0 / 300 / 100 | 계단식 부하. `LOAD_STEP_USERS`가 0이면 끄고 `-u`, `-r`을 따름 |
| `LOAD_WAIT_MIN_SECONDS` / `LOAD_WAIT_MAX_SECONDS` | 1 / 5 | 한 사용자가 동작 하나를 끝내고 다음 동작까지 쉬는 시간(초)의 범위 |
| `LOAD_POLL_SECONDS` | 2 | run 상태 조회 간격(초) |
| `LOAD_RUN_TIMEOUT_SECONDS` | 900 | 턴 하나의 제한 시간(초). 넘으면 취소하고 실패 |
| `LOAD_DELETE_SESSIONS` | true | 턴이 끝난 뒤 세션 삭제. 실패 원인을 화면에서 보려면 false |
| `LOAD_VERIFY_TLS` | true | 인증서 검증. 사내 인증서를 PC가 믿지 않아 실패할 때만 false |

## 결과 읽기

- 종류가 `RUN`인 줄(`chat turn`, `analysis turn`, `executor execution`, `batch run`)이 사용자가 느끼는 값입니다. 요청을 보낸 때부터 끝날 때까지의 시간이고, 실패·취소로 끝나거나 제한 시간을 넘으면 실패로 셉니다. 실패 사유는 Failures 탭에 나옵니다.
- `batch run`은 배치 실행이 `COMPLETED`가 될 때까지입니다. 그 뒤에 쓰이는 배치 리포트(LLM)는 재지 않습니다. 리포트 적체는 화면의 배치 리포트 목록이나 키바나에서 봅니다.
- 한 사용자가 분당 보내는 호출 수는 결과 표의 전체 req/s × 60 ÷ 사용자 수입니다. 새 실행 수는 `POST /executor/executions` 줄의 req/s로 봅니다. 호출 수를 늘리려면 `LOAD_POLL_SECONDS`와 쉬는 시간을 줄이고, 줄이려면 늘립니다.
- `executor execution`의 시간에서 코드가 도는 시간(기본 10초)을 뺀 값이 대기와 준비 시간입니다. 사용자 수를 올렸을 때 이 값이 늘기 시작하면 executor 슬롯이 찬 것입니다.
- 나머지 줄은 API 한 번의 응답 시간입니다. `GET /runs/[id]`는 상태 조회라 수가 많은 것이 정상입니다.
- 실행하는 동안 서비스 쪽에서 함께 봐야 하는 값(executor 실행 슬롯, PostgreSQL 연결 수, 파드 수, 오류 로그)은 `docs/integration-test/scenarios/OPS-08.md`에 있습니다.

## 지금 설정으로 본 예상치

측정한 값이 아니라 설정값으로 계산한 것입니다. 실제 한계는 계단식 실행으로 찾습니다.

기준 구성: 우리 서비스 파드 2개(`RUN_MODE: all`), executor 1개, pr-batch 1개. 괄호는 HPA가 우리 파드를 4개까지 늘렸을 때입니다.

| 자원 | 설정 | 예상 |
| --- | --- | --- |
| 우리 서비스, 동시에 도는 턴 | `RUN_CONCURRENCY` 16 × 파드 2개 | 32개(최대 64개). 넘으면 실패하지 않고 `queued`로 기다려 턴 시간이 늘어남. 승인 대기와 executor 대기 중인 턴은 자리를 차지하지 않음 |
| 한 사용자의 동시 턴 | `RUN_USER_CONCURRENCY` 4 | 사번 하나를 가상 사용자 여럿이 돌려 쓰면 여기에 먼저 걸림. 가상 사용자 수만큼 사번을 준비하는 편이 정확함 |
| 우리 서비스 처리량 | 로컬 측정(`docs/load-design.md`), LLM 제외 | 프로세스 하나가 초당 약 24턴, 조회 초당 약 1,000건. 서비스 자체보다 LLM, executor가 먼저 한계가 됨 |
| PostgreSQL 연결 | 파드당 최대 14 × 파드 2개 | 우리 몫 28개(최대 56개). 한도가 150이면 executor와 pr-batch가 쓸 수 있는 것은 122개(최소 94개) |
| LLM 동시 호출 | (`RUN_CONCURRENCY` 16 + `BATCH_REPORT_CONCURRENCY` 4) × 파드 2개 | 최대 40개(80개) |
| 배치 리포트 | `BATCH_REPORT_CONCURRENCY` 4 × 파드 2개 | 동시에 8건(16건) 작성. 배치가 한꺼번에 많이 끝나면 리포트가 밀림(실패는 아님) |
| executor 실행 슬롯 | 100으로 둘 예정, executor 파드 1개 | 동시에 실행 100개. 넘는 요청이 기다리는지 거절되는지, 파드 하나가 100개를 감당하는지는 이번 측정으로 확인할 항목 |
| pr-batch | 파드 1개 | 동시에 제출하고 따라갈 수 있는 배치 실행 수는 pr-batch 설정에 달려 있어 "배치만" 실행으로 확인할 항목 |

우리 파드를 API용(`RUN_MODE: api`)과 워커용(`RUN_MODE: worker`)으로 나누면, 턴과 배치 리포트는 워커 파드만 처리하므로 위 숫자는 워커 파드 수로 계산합니다(워커 1개면 턴 16개, 리포트 4건, LLM 20개).

가장 먼저 한계가 될 것으로 보는 곳은 executor 슬롯입니다. 분석 세션은 턴이 끝난 뒤에도 커널을 한동안 잡고 있으므로(대기 시간 설정), "동시에 코드를 돌리는 사람"이 아니라 "최근에 분석을 한 사람과 돌고 있는 배치의 합"이 100을 넘으면 찹니다. 이 부분은 executor 설정을 읽고 한 추정이 아니라서 측정으로 확인해야 합니다.

## 주의

- **실제 LLM과 executor를 씁니다.** 호출 비용과 한도를 쓰고, 같은 환경에서 테스트하는 다른 사람이 느려집니다. 시간을 정해 알리고 혼자 수행합니다.
- 분석 턴은 `LOAD_ANALYSIS_PROMPT`의 데이터가 그 환경에 있어야 끝까지 갑니다. 한 명으로 먼저 돌려 확인합니다.
- 시작할 때 키나 사번 목록이 없으면 이유를 출력하고 종료 코드 2로 끝납니다.
- `users.csv`, 보고서 파일은 `.gitignore`로 커밋에서 빠집니다.
- 강제로 중단하면(Ctrl+C) 진행 중이던 세션이 남을 수 있습니다. 테스트 사번의 세션 목록에서 지웁니다.

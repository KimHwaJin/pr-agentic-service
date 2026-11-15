# 부하 테스트 (Locust)

통합 테스트 OPS-08 "동시 사용자 부하"를 수행하는 도구입니다. 서비스 코드와 따로 떨어져 있고 이미지에 들어가지 않습니다. 부하를 거는 PC에서 실행하고, 대상 서비스에는 키 호출(`X-Api-Key` + `X-User-Id`)로 들어가므로 SSO 로그인이 필요 없습니다.

## 무엇을 하는가

가상 사용자 한 명이 사번 하나로 아래 세 가지를 1~5초 간격으로 되풀이합니다. 괄호는 기본 비율입니다.

| 동작 | 내용 |
| --- | --- |
| 가벼운 조회 (6) | 내 정보, 세션 목록 조회 |
| 대화 턴 (3) | 새 세션에 대화 한 줄을 보내고 run이 끝날 때까지 2초마다 상태를 조회 |
| 분석 턴 (1) | 새 세션에 분석 요청을 보내고, 계획 승인과 코드 승인 질문에 스스로 "승인"으로 답하며 끝까지 진행. executor에서 코드가 실제로 실행됨 |

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

## 설정 (환경 변수)

| 이름 | 기본값 | 뜻 |
| --- | --- | --- |
| `LOAD_API_KEY` | (필수) | 우리 테넌트 표준 키 원문 |
| `LOAD_USERS_FILE` | `locust/users.csv` | 사번 목록 파일 |
| `LOAD_API_PREFIX` | `/api/v1` | API 경로 앞부분 |
| `LOAD_MODEL` | (비움) | 쓸 모델 이름. 비우면 서비스 기본 모델 |
| `LOAD_CHAT_PROMPT` | 안녕, 오늘 할 수 있는 분석을 알려줘 | 대화 턴에 보낼 문장 |
| `LOAD_ANALYSIS_PROMPT` | nce 데이터 불러와서 기술통계 보여줘 | 분석 턴에 보낼 문장 |
| `LOAD_QUESTION_ANSWER` | 기본값으로 진행해줘 | 선택지 없는 질문에 보낼 답 |
| `LOAD_READ_WEIGHT` / `LOAD_CHAT_WEIGHT` / `LOAD_ANALYSIS_WEIGHT` | 6 / 3 / 1 | 세 동작의 비율. 0이면 그 동작을 하지 않음 |
| `LOAD_POLL_SECONDS` | 2 | run 상태 조회 간격(초) |
| `LOAD_RUN_TIMEOUT_SECONDS` | 900 | 턴 하나의 제한 시간(초). 넘으면 취소하고 실패 |
| `LOAD_DELETE_SESSIONS` | true | 턴이 끝난 뒤 세션 삭제. 실패 원인을 화면에서 보려면 false |
| `LOAD_VERIFY_TLS` | true | 인증서 검증. 사내 인증서를 PC가 믿지 않아 실패할 때만 false |

## 결과 읽기

- 종류가 `RUN`인 두 줄(`chat turn`, `analysis turn`)이 사용자가 느끼는 값입니다. 요청을 보낸 때부터 run이 끝날 때까지의 시간이고, run이 `failed`·`cancelled`로 끝나거나 제한 시간을 넘으면 실패로 셉니다. 실패 사유는 Failures 탭에 나옵니다.
- 나머지 줄은 API 한 번의 응답 시간입니다. `GET /runs/[id]`는 상태 조회라 수가 많은 것이 정상입니다.
- 실행하는 동안 서비스 쪽에서 함께 봐야 하는 값(executor 실행 슬롯, PostgreSQL 연결 수, 파드 수, 오류 로그)은 `docs/integration-test/scenarios/OPS-08.md`에 있습니다.

## 주의

- **실제 LLM과 executor를 씁니다.** 호출 비용과 한도를 쓰고, 같은 환경에서 테스트하는 다른 사람이 느려집니다. 시간을 정해 알리고 혼자 수행합니다.
- 분석 턴은 `LOAD_ANALYSIS_PROMPT`의 데이터가 그 환경에 있어야 끝까지 갑니다. 한 명으로 먼저 돌려 확인합니다.
- 시작할 때 키나 사번 목록이 없으면 이유를 출력하고 종료 코드 2로 끝납니다.
- `users.csv`, 보고서 파일은 `.gitignore`로 커밋에서 빠집니다.
- 강제로 중단하면(Ctrl+C) 진행 중이던 세션이 남을 수 있습니다. 테스트 사번의 세션 목록에서 지웁니다.

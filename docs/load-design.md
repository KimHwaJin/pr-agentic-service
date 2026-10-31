# 부하 설계와 측정

배포 조건: 1레포 1Deployment, 단일 컨테이너, CPU 기반 HPA. 사용자 약 200명.

## 설계 원칙

| 항목 | 방식 | 이유 |
| --- | --- | --- |
| 프로세스 | Pod당 uvicorn worker 1개, API + worker 동시 기동 | CPU HPA가 Pod 수로 확장. 프로세스를 늘리면 백그라운드 루프와 DB 풀이 곱절이 됨 |
| 대기 중 run | HITL·executor 대기는 interrupt 후 슬롯 반납 (`waiting_*`) | 수시간~수일 적재도 Pod 자원을 잡지 않음 |
| run 배분 | PG `FOR UPDATE SKIP LOCKED` + Redis wake 신호, 슬롯이 비면 즉시 다음 run | 폴링(5초)은 보조. 모든 Pod가 같은 큐를 나눠 처리 |
| 동시 실행 | `RUN_CONCURRENCY`(기본 32) | turn은 LLM·executor 대기가 대부분이라 CPU 대비 동시성을 높게 둠 |
| SSE | 프로세스당 Redis 패턴 구독 1개 → 메모리 큐로 분배 | SSE 연결 수와 Redis 연결 수가 무관 |
| 토큰 스트리밍 | run별 50ms 단위로 묶어 발행, 저장하지 않음 | 토큰마다 Redis 발행하던 부하 제거. 최종 답변만 저장 |
| executor 진행 이벤트 | 실시간 전달만, 저장은 `execution_completed` 요약만 | 이벤트 테이블 쓰기 감소 |
| 체크포인트 | LangGraph `durability="async"` | 단계별 저장을 응답 경로에서 분리 |
| executor 호출 | run·tool_call 기반 멱등 키 + 1회 실행 기록 | 재개·재시도 시 중복 실행 없음 |
| 인증 | Redis 세션 + 사용자 정보 30초 프로세스 캐시 | 요청마다 DB 조회 제거 |
| 파일 자산 | skill/tool/프롬프트는 5초 간격으로만 변경 확인 | 모델 호출마다 디렉터리 스캔 제거 |
| HTTP 클라이언트 | LLM(별칭별)·executor·pr-batch 클라이언트 프로세스당 1개 | 연결 재사용 |
| 인덱스 | 대기 run의 execution_id, 세션 이벤트(session_id, id), 메시지(session_id, created_at) | 이벤트 수신·SSE 재생·대화 조회가 인덱스로 처리 |
| 데이터 증가 | 이벤트 30일, executor inbox 7일 보존 후 소량 배치 삭제. run 종료 시 재개 기록 삭제 | 테이블 무한 증가 방지 |

## 측정 (로컬, mock LLM)

`scripts/loadtest.py`: 가상 사용자마다 SSE를 열고 대화 턴을 연속 전송, `message_final`까지 시간 측정. LLM을 즉시 응답 mock으로 바꿔 서비스 자체 처리량만 본 값이다.

| 조건 | 처리량 | 턴 지연 p50 / p95 | 읽기 API |
| --- | --- | --- | --- |
| 개선 전, 프로세스 1개, 50명 | 9.5턴/s | 2.78s / 7.56s | 730 req/s |
| 개선 후, 프로세스 1개, 50명 | 14.4턴/s | 2.08s / 3.17s | 1,147 req/s |
| 개선 후, 프로세스 1개, 100명 | 24.2턴/s | 3.65s / 5.10s | 982 req/s |
| 개선 후, 프로세스 2개(Pod 2개 모사), 100명 | 28.1턴/s | 1.10s / 2.42s | 1,123 req/s |

- 개선 후 프로세스 1개는 CPU 1코어가 포화된 상태다. 단순 대화 1턴의 서비스 CPU 비용은 약 40ms(LLM 대기 제외)이며, 그중 약 1/3은 OpenAI SDK의 요청 직렬화다.
- 실제 LLM은 호출당 수 초가 걸리므로 운영에서는 CPU보다 LLM 대기가 지배한다. 분석 1턴에 모델 호출 5~10회를 가정해도 Pod 1개(1 CPU)가 초당 수 턴을 처리하며, 200명 규모에는 Pod 2개(minReplicas)로 충분한 여유가 있다.
- Redis 연결은 프로세스당 고정(측정 시 2개 프로세스 합계 32개), PostgreSQL 연결은 2개 프로세스 합계 25개였다.

## 운영 튜닝

| 설정 | 기본 | 조정 기준 |
| --- | --- | --- |
| `RUN_CONCURRENCY` | 32 | `waiting`이 아닌 `queued` run이 계속 쌓이면 올린다. LLM 게이트웨이의 동시 처리 한도를 넘지 않게 Pod 수 × 값으로 맞춘다 |
| `RUN_USER_CONCURRENCY` | 4 | 한 사용자가 여러 Pod에 걸쳐 동시에 돌릴 수 있는 turn 수. 한 사용자가 세션을 여러 개 열어 슬롯을 독차지하지 못하게 한다. 0이면 제한 없음 |
| `DB_POOL_SIZE` | 5 (+overflow 5) | SQLAlchemy 풀(앱 테이블). Pod당 최대 `DB_POOL_SIZE × 2` 연결. 턴이 도는 동안에는 거의 쓰지 않고, 많은 턴이 한꺼번에 시작될 때만 몰린다(아래 측정). 로그에 `QueuePool limit`이 보이면 올린다 |
| `BATCH_REPORT_CONCURRENCY` | 4 | 배치 리포트를 Pod 하나가 동시에 몇 건 쓰는지. 리포트 1건은 LLM을 최대 `BATCH_REPORT_MODEL_CALL_LIMIT`(20)번 차례로 부르므로 LLM 동시 요청은 Pod당 최대 `RUN_CONCURRENCY + BATCH_REPORT_CONCURRENCY`. 배치가 한꺼번에 끝나 리포트가 밀리면 올리고, LLM 게이트웨이 한도에 가까우면 내린다. 작업마다 lease(SKIP LOCKED)를 잡으므로 같은 리포트를 두 번 쓰지 않는다 |
| `CHECKPOINT_POOL_SIZE` | 16 | LangGraph checkpointer/store 풀. 실행 중인 turn의 graph step마다 체크포인트를 쓰므로 `RUN_CONCURRENCY`의 절반 이상으로 둔다. 연결을 30초(`CHECKPOINT_POOL_TIMEOUT_SECONDS`) 안에 못 얻으면 turn이 실패한다 |
| PG `max_connections` | — | 우리 Pod당 최대 연결 = `DB_POOL_SIZE × 2 + CHECKPOINT_POOL_SIZE` (기본 26). 같은 DB를 executor·pr-batch도 쓰므로 아래 "공용 DB 연결 예산"의 합계보다 커야 한다 |
| HPA | CPU 60%, min 2 / max 6 | CPU가 LLM 대기를 반영하지 않으므로 min 2를 유지한다. 큐 적체는 `RUN_CONCURRENCY`로 흡수 |
| `terminationGracePeriodSeconds` | 60 | preStop 5초 → uvicorn 연결 종료 대기(`--timeout-graceful-shutdown 20`, SSE가 있으면 끝까지 기다림) → 새 run 수락 중단, 진행 중 turn과 메모리 작업을 함께 마무리(최대 20초) → 남은 run은 lease 반납 후 다른 Pod가 이어감. 합계 약 45~50초 |

## checkpoint 저장이 한 줄로 서던 문제 (2026-10-31)

LangGraph `AsyncPostgresSaver`는 연결 풀을 받아도 saver 하나에 락을 걸고 모든 읽기·쓰기를 그 안에서 합니다. 프로세스가 saver 하나를 같이 쓰므로, `CHECKPOINT_POOL_SIZE`가 16이어도 checkpoint I/O는 한 번에 하나였습니다. `core/checkpoints.py`의 `PooledPostgresSaver`는 풀일 때 이 락을 끕니다(같은 라이브러리의 store가 풀에서 하는 것과 같음). 같은 대화(thread)에 동시에 쓰는 일은 세션당 한 턴 규칙이 막습니다.

측정(로컬 PostgreSQL 16, 풀 16, 동시 턴 32개 × 10단계, 단계마다 읽기·상태 저장·중간 결과 저장, 상태 약 20KB):

| | 전체 | 호출 평균 | p95 | 동시에 일한 DB 연결 |
| --- | --- | --- | --- | --- |
| 기존 saver | 1.95~2.30초 | 62~74ms | 75~119ms | 1 |
| PooledPostgresSaver | 0.70~0.73초 | 20~21ms | 32~34ms | 16 |

DB가 같은 기계에 있어 쿼리가 빠른 조건입니다. DB가 네트워크 너머라 쿼리가 느릴수록 기존 방식의 대기는 동시 턴 수만큼 곱해져 차이가 더 커집니다. 라이브러리 버전은 고정했고(`langgraph-checkpoint-postgres==3.1.3`), 락 위치가 바뀌면 `tests/test_checkpoint_saver.py`가 실패합니다.

## 공용 DB 연결 예산 (2026-10-31)

pr-agentic-service, executor, pr-batch가 같은 PostgreSQL을 씁니다. 모든 풀이 꽉 찼을 때의 최대 연결 수입니다.

| 서비스 | Pod당 최대 | 구성 | 평소 Pod | 최대 Pod |
| --- | --- | --- | --- | --- |
| pr-agentic-service | 26 | 앱 풀 5 + overflow 5, checkpoint/store 16 | 2 | 6 (HPA) |
| executor | 16 | `DATABASE_POOL_SIZE` 10 + `DATABASE_MAX_OVERFLOW` 5, readiness 1 | 1 | 1 |
| pr-batch | 10 | `DB_POOL_SIZE` 5 + `DB_MAX_OVERFLOW` 5 | 1 | 4 (HPA) |

| 상황 | 합계 |
| --- | --- |
| 평소 (2 + 1 + 1) | 78 |
| 우리 배포 중 (maxSurge로 Pod 1개씩 더) | 104 |
| 모두 최대 스케일 (6 + 1 + 4) | 212 |
| 최대 스케일 + 배포 여유 + 운영 접속 20 | 약 260 |

- PostgreSQL 기본값은 `max_connections` 100이고 superuser 예약 3을 빼면 97입니다. 평소 운영은 들어가지만, 배포나 스케일아웃이 겹치면 넘습니다. 운영 DB는 **`max_connections` 260 이상**으로 두거나, 늘릴 수 없으면 앞단에 PgBouncer(transaction 모드)를 둡니다. 우리 연결은 `prepare_threshold 0`이라 그대로 붙습니다.
- `pg_stat_activity.application_name`으로 우리 풀을 구분합니다. 앱 풀은 `pr-agentic-app`, checkpoint/store 풀은 `pr-agentic-graph`입니다([operations.md](operations.md) 8절).

측정(로컬, 실제 LLM, 턴 32개를 동시에 시작, 턴마다 도구 호출 4~5회, 200ms마다 `pg_stat_activity` 샘플링):

| `DB_POOL_SIZE` | 성공 | 턴 시간 중간값 / p95 | 앱 풀 연 연결 / 동시 사용 최대 / p95 | graph 풀 연 연결 / 동시 사용 최대 | 풀 대기 오류 |
| --- | --- | --- | --- | --- | --- |
| 10 | 32/32 | 124.6초 / 163.9초 | 20 / 12 / 0 | 16 / 3 | 없음 |
| 5 | 32/32 | 121.2초 / 159.8초 | 10 / 10 / 0 | 16 / 9 | 없음 |

앱 풀이 꽉 찬 것은 32개 턴의 세션·run을 한꺼번에 만든 첫 1초뿐이었고, 턴이 도는 2~3분 동안은 평균 0.03~0.04개였습니다. 5로 줄여도 턴 시간과 성공률은 그대로여서 기본값을 5로 내렸습니다.

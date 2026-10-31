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
| `DB_POOL_SIZE` | 10 (+overflow 10) | SQLAlchemy 풀. Pod당 최대 `DB_POOL_SIZE × 2` 연결 |
| `CHECKPOINT_POOL_SIZE` | 16 | LangGraph checkpointer/store 풀. 실행 중인 turn의 graph step마다 체크포인트를 쓰므로 `RUN_CONCURRENCY`의 절반 이상으로 둔다. 연결을 30초(`CHECKPOINT_POOL_TIMEOUT_SECONDS`) 안에 못 얻으면 turn이 실패한다 |
| PG `max_connections` | — | Pod당 최대 연결 = `DB_POOL_SIZE × 2 + CHECKPOINT_POOL_SIZE` (기본 36). `maxReplicas × 36 + 여유(마이그레이션, 운영 접속 등 20)`보다 커야 한다. 기본값(max 6)이면 236 이상 |
| HPA | CPU 60%, min 2 / max 6 | CPU가 LLM 대기를 반영하지 않으므로 min 2를 유지한다. 큐 적체는 `RUN_CONCURRENCY`로 흡수 |
| `terminationGracePeriodSeconds` | 60 | preStop 5초 → uvicorn 연결 종료 대기(`--timeout-graceful-shutdown 20`, SSE가 있으면 끝까지 기다림) → 새 run 수락 중단, 진행 중 turn과 메모리 작업을 함께 마무리(최대 20초) → 남은 run은 lease 반납 후 다른 Pod가 이어감. 합계 약 45~50초 |

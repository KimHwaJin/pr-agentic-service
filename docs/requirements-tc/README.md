# 요구사항별 테스트 케이스

요구사항 17개(번호 1~11, 14~19)에 대해 요구사항마다 시나리오 페이지 하나와 TC를 정리했습니다. 시나리오 17개, TC 95개입니다. 양식과 작성 규칙은 통합테스트와 같습니다([양식](../integration-test/scenario-page-template.md), [통합테스트 계획](../integration-test/integration-test-plan.md)).

- ID는 `REQ-<요구사항 번호 두 자리>`, TC는 `REQ-<번호>-<순번>`입니다. 요구사항 번호는 받은 그대로 썼고 12, 13번은 목록에 없어 비워 두었습니다.
- 판정은 통합테스트와 같이 서버 응답(상태 코드, 응답 본문, 이벤트)과 서비스 기록으로 합니다. 우리 화면(`/dev/`)은 요청을 보내고 응답을 읽는 보조 도구입니다.
- 각 페이지 4절 예상 결과의 한 줄이 TC 하나이고, 상황판([requirements-tc-tracker.xlsx](requirements-tc-tracker.xlsx))의 한 줄과 같습니다.
- tool 이름(`load_synthetic`, `clean_data`, `xgboost_model` 등)은 시험 카탈로그(`catalogs/analysis_test`) 기준입니다. 환경의 카탈로그 구성이 다르면 `GET /api/v1/catalog/skills`에서 확인한 이름으로 바꿔 판정합니다.
- "※ 미확인"은 코드로 확인하지 못해 환경에서 확인이 필요한 내용입니다.
- 7~9절(수행 기록, 증빙, 결함)과 상황판의 상태·일자 칸은 수행자가 채우는 칸이라 비워 두었습니다.

## 요구사항 추적표

| 번호 | 요구사항 | 시나리오 | 우선 | 화면 | 필요 권한 | TC 수 | 관련 통합테스트 시나리오 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 데이터 로드(데이터 다운로드) tool 실행 | [REQ-01](scenarios/REQ-01.md) | P0 | O | 일반 | 5 | RUN-01, RUN-19, PREP-10 |
| 2 | agent-jupyter 연계 | [REQ-02](scenarios/REQ-02.md) | P0 | 일부 | 일반 | 4 | RUN-01, RUN-03, EXEC-08, PREP-08 |
| 3 | 정형 데이터 전처리 수행 | [REQ-03](scenarios/REQ-03.md) | P0 | O | 일반 | 5 | RUN-17(정리 후 분석), RUN-19 |
| 4 | 정형 데이터 EDA 수행 | [REQ-04](scenarios/REQ-04.md) | P0 | O | 일반 | 5 | RUN-01, RUN-19 |
| 5 | 결과 레포트 작성 | [REQ-05](scenarios/REQ-05.md) | P0 | O | 일반 | 5 | RUN-01, RUN-19, EXEC-05 |
| 6 | 모델 학습 수행 | [REQ-06](scenarios/REQ-06.md) | P0 | O | 일반 | 5 | RUN-01, RUN-13 |
| 7 | 모델 평가 수행 | [REQ-07](scenarios/REQ-07.md) | P0 | O | 일반 | 5 | RUN-19, REQ-06 |
| 8 | workflow 계획 | [REQ-08](scenarios/REQ-08.md) | P0 | O | 일반 | 5 | RUN-01, RUN-04, RUN-07, RUN-08, RUN-14, RUN-16, RUN-17 |
| 9 | 산출물 및 정보 조회 | [REQ-09](scenarios/REQ-09.md) | P0 | O | 일반 | 6 | RUN-01, RUN-03, EXEC-05, ADM-02 |
| 10 | context 조회 | [REQ-10](scenarios/REQ-10.md) | P0 | 일부 | 일반 | 6 | RUN-15, RUN-19, REQ-19 |
| 11 | 전체 시스템 (api - agent - executor - batch - runtime) 연계 | [REQ-11](scenarios/REQ-11.md) | P0 | 일부 | 일반 + 운영 | 7 | PREP-08, RUN-01, RUN-02, RUN-03, BAT-01, BAT-02, BAT-03, BAT-04, EXEC-08 |
| 14 | 로깅 및 agent context | [REQ-14](scenarios/REQ-14.md) | P0 | 일부 | 관리자 + 운영 | 6 | AUTH-04, RUN-15, OPS-03 |
| 15 | jupyter pv에 데이터 저장 | [REQ-15](scenarios/REQ-15.md) | P0 | 일부 | 일반 + 운영 | 5 | RUN-01, EXEC-05, REQ-02 |
| 16 | 코드 실행이력 조회 | [REQ-16](scenarios/REQ-16.md) | P0 | O | 일반 + 관리자 | 6 | RUN-01, EXEC-01, EXEC-04, EXEC-06, EXEC-07, ADM-05 |
| 17 | 아티팩트 조회 | [REQ-17](scenarios/REQ-17.md) | P0 | O | 일반 + 관리자 | 5 | EXEC-05, RUN-01, REQ-05 |
| 18 | 배치작업 | [REQ-18](scenarios/REQ-18.md) | P0 | O | 일반 | 7 | BAT-01, BAT-02, BAT-03, BAT-04, BAT-05, BAT-06, BAT-07, BAT-09 |
| 19 | 프로젝트 공유 메모리 | [REQ-19](scenarios/REQ-19.md) | P0 | O | 일반 | 8 | RUN-15 |

## TC 목록

| TC ID | TC명 | 확인 단계 | 기대 결과 |
| --- | --- | --- | --- |
| REQ-01-01 | 카탈로그에 data_load skill과 데이터 로드 tool 등록 | 1 | `GET /catalog/skills/data_load` 200, tool 목록에 데이터 로드 tool 1개 이상 |
| REQ-01-02 | 계획 첫 단계가 데이터 로드 tool | 3 | `hitl_request`의 `type`이 `plan_approval`, 1번 후보 첫 호출의 tool이 데이터 로드 tool, 입력 `data_type` = `nce` |
| REQ-01-03 | 데이터 로드 tool 실행 성공과 데이터 모양 반환 | 4 | `execution_completed.results`에서 해당 tool의 `status`가 `SUCCEEDED`, `observations`에 행·열 수(shape)가 있고 행 수가 1 이상. run 상태 `succeeded` |
| REQ-01-04 | 조회 조건(LOT) 반영 | 5 | 계획의 `lot_cd`에 `L3`, 결과 행 수가 4번보다 작음 |
| REQ-01-05 | 실행 이력 단계에 데이터 로드 기록 | 6 | `GET /executor/executions/{id}/steps` 200, 첫 단계 상태 `SUCCEEDED` |
| REQ-02-01 | 코드 실행 중 run 상태가 waiting_executor | 3 | `run_status` 이벤트에 `status: waiting_executor`와 `execution_id` 값. 실행 중 `execution_progress` 이벤트 수신 |
| REQ-02-02 | executor 실행이 Jupyter 런타임에 배정 | 4 | 실행 ID가 `execution_id`와 같음, 상태 `SUCCEEDED`, 방식 `MULTI`, `runtime.kernel_id`에 값, 런타임이 1번의 ACTIVE 런타임 중 하나 |
| REQ-02-03 | 한 대화의 단계가 한 노트북에 순서대로 기록 | 5 | `GET /executor/executions/{id}/notebook` 200, 셀 순서가 단계 순서와 같고 셀마다 실행 출력이 있음 |
| REQ-02-04 | 결과 노트북이 JupyterLab에서 열림 | 6 | `artifact` 이벤트(`kind: notebook`)에 `lab_url` 값, 그 주소에서 노트북이 열림 |
| REQ-03-01 | 전처리 tool이 계획에 포함 | 2 | `plan_approval` 후보에 `check_missing`, `check_duplicates`, `clean_data`가 데이터 로드 뒤 순서로 있음 |
| REQ-03-02 | 결측·중복 확인 값이 실제 데이터와 같음 | 3 | `check_missing`의 PMX 결측 수, `check_duplicates`의 중복 행 수가 기준값과 같음 |
| REQ-03-03 | 정리 결과(clean_data) 반환 | 3 | `clean_data` `status: SUCCEEDED`, `removed_rows` 1 이상, 정리 뒤 `shape`의 행 수 = 원래 행 수 − `removed_rows` |
| REQ-03-04 | 행 선택·집계 tool 실행 | 4 | `filter_rows`, `aggregate_by` `SUCCEEDED`, 집계 결과 4행(L3의 W01~W04) |
| REQ-03-05 | 실행 이력에 전처리 단계 기록 | 5 | 전처리 단계 전부 `SUCCEEDED`, run 상태 `succeeded` |
| REQ-04-01 | EDA tool이 계획에 포함 | 2 | `plan_approval` 후보에 `compute_statistics`, 분포 tool 1개 이상, `correlation_analysis` |
| REQ-04-02 | 기술통계 값이 실제 데이터와 같음 | 3 | `compute_statistics` `SUCCEEDED`, SN OPEN 평균·표준편차가 기준값과 같음(반올림 차이만) |
| REQ-04-03 | 상관분석 결과 | 3 | `correlation_analysis` `SUCCEEDED`, DNW–MBO 상관계수 약 0.86(기준값과 같음) |
| REQ-04-04 | 분포 그림 생성과 조회 | 4 | 그림 tool 결과 `images` 1개 이상, `GET /sessions/{id}/outputs` 200(이미지) |
| REQ-04-05 | 답변 값과 실행 결과 일치 | 5 | 답변의 통계값이 `execution_completed` 결과 값과 같음, run 상태 `succeeded` |
| REQ-05-01 | 리포트 작성 tool 호출 | 2 | `tool_call` 이벤트 `name: write_report`, `activity`(`report_writing`) `started` → `finished` |
| REQ-05-02 | 리포트·노트북 게시 | 3 | `artifact` 이벤트 2개(`kind: report`, `kind: notebook`), 각각 `artifact_id` 값. run 상태 `succeeded` |
| REQ-05-03 | 리포트 열람과 내용의 근거 | 4 | `GET /view/artifacts/{id}` 200, 리포트의 LOT별 평균이 `execution_completed` 값과 같음 |
| REQ-05-04 | 리포트 artifact 정보 | 5 | `GET /artifacts/{id}` 200, 이름 `final-report.md`, metadata의 `session_id`·`run_id`가 이 대화 값. `/content` 200(markdown) |
| REQ-05-05 | 리포트 게시 뒤 후속 분석은 새 실행 | 6 | 같은 세션에 실행 2개, 첫 실행은 종료 시각이 찍힌 `SUCCEEDED` |
| REQ-06-01 | 카탈로그에 모델링 skill·tool 등록 | 1 | `GET /catalog/skills/modeling` 200, 모델링 tool 7개 |
| REQ-06-02 | 모델 학습 tool이 계획에 포함 | 3 | `plan_approval` 후보에 `xgboost_model`(또는 `feature_importance`), `target_column` = `yield_pct` |
| REQ-06-03 | 모델 학습 실행 성공 | 4 | `xgboost_model` `status: SUCCEEDED`, `task: regression`, `rows`가 입력 데이터 행 수와 같음, `importances` 1개 이상. run 상태 `succeeded` |
| REQ-06-04 | 학습 코드가 노트북에 기록 | 5 | 노트북에 `xgboost_model` 호출 셀과 출력이 있음 |
| REQ-06-05 | 분류 목표 학습(선택) | 6 | `task: classification`, `SUCCEEDED` |
| REQ-07-01 | 평가 조건(시험 데이터 비율) 반영 | 2 | 계획의 `xgboost_model` 입력 `test_ratio` = 0.25 |
| REQ-07-02 | 모델 성능 지표 반환 | 3 | `xgboost_model` 결과에 `metric`(`r2`)과 `score`(숫자) 값, `score`가 0보다 큼 |
| REQ-07-03 | 영향 변수 순위 | 3 | `importances` 상위 변수에 `avg_pressure` 포함 |
| REQ-07-04 | 다른 모델로 교차 확인 | 4 | `feature_importance` `score` 값, `linear_regression` `r2`·`adj_r2`·`p_values` 값, 모두 `SUCCEEDED`(조건부 단계를 건너뛰면 그 사유가 계획 결과에 남음) |
| REQ-07-05 | 답변·리포트 지표가 실행 결과와 같음 | 5 | 답변과 리포트의 지표 숫자가 `execution_completed` 값과 같음(반올림 차이만) |
| REQ-08-01 | 계획 후보 제시와 승인 대기 | 2 | `hitl_request` `type: plan_approval`, 후보 1개 이상, 후보 중복 없음, 한 응답에 계획 카드 1개. run 상태 `waiting_input` |
| REQ-08-02 | 수정 요청이 계획에 반영 | 3 | 응답 요청 202 `resumed: true`, 새 계획 후보에 `compare_groups_ttest` 포함, run ID는 그대로 |
| REQ-08-03 | 승인된 계획이 Workflow 1.0 문서 | 4 | `plan_approved` 이벤트에 `plan_id`·`title`·`document`, `POST /workflows/validate` 통과 |
| REQ-08-04 | 실행한 계획을 워크플로우로 저장 | 5 | `workflow_saved` 이벤트(`workflow_id`, `name`), `GET /workflows` 응답에 그 이름 |
| REQ-08-05 | 저장된 워크플로우 추천 | 6 | `plan_approval` 후보 중 `source`에 워크플로우 ID가 있는 후보 1개 이상 |
| REQ-09-01 | 대화와 첨부 다시 조회 | 1 | `GET /projects/{id}/sessions`에 세션 있음, `GET /sessions/{id}/messages` 200, 답변 메시지에 리포트·노트북 첨부 |
| REQ-09-02 | run 목록·상세 조회 | 2 | `GET /sessions/{id}/runs`, `GET /runs/{id}` 200, `status: succeeded` |
| REQ-09-03 | run 이벤트 다시 조회 | 3 | `GET /runs/{id}/events` 200, 저장 이벤트가 순서대로 있고 `execution_completed`·`artifact` 포함 |
| REQ-09-04 | 단계 산출물(그림·파일) 조회 | 4 | `GET /sessions/{id}/outputs` 200, 없는 경로는 404 |
| REQ-09-05 | 카탈로그·모델 정보 조회 | 5 | `/catalog/skills`, `/catalog/tools`, `/catalog/tools/{name}`, `/models` 모두 200 |
| REQ-09-06 | 다른 사용자의 대화는 조회 불가 | 6 | B의 요청은 403 또는 404, 응답 본문에 대화 내용 없음 |
| REQ-10-01 | 도메인 지식 문서 조회 | 1 | `tool_call` 이벤트 `name: read_knowledge`, 답변 내용이 지식 문서와 같음 |
| REQ-10-02 | skill·tool 설명 조회 후 계획 | 2 | 계획 전 `tool_call`에 `read_skill`(또는 `search_tools`·`read_tool`), 이후 `plan_approval` |
| REQ-10-03 | 앞선 실행 결과를 맥락으로 사용 | 3 | 답의 LOT이 2번 실행 결과와 같음(`L3`), 지어낸 값 없음 |
| REQ-10-04 | 프로젝트 메모리를 새 대화의 맥락으로 사용 | 4 | 새 대화의 결과에 메모리의 선호가 반영됨 |
| REQ-10-05 | 맥락 조회 기록 다시 조회 | 5 | `GET /runs/{id}/events` 200, `tool_call` 이벤트가 순서대로 남음 |
| REQ-10-06 | 긴 대화의 맥락 요약 | 6 | `context_summarized` 이벤트(`messages` 1 이상, `summary_chars` ≤ `AGENT_SUMMARY_MAX_CHARS` 기본 6000), 요약 뒤에도 첫 요청의 데이터 이름을 맞게 답함 |
| REQ-11-01 | API가 분석 요청을 받아 run 생성 | 2 | `POST /sessions/{id}/runs` 202, 응답에 run ID, 응답 헤더 `X-Request-ID` 값 |
| REQ-11-02 | Agent(워커)가 run을 끝까지 진행 | 3 | `run_status`가 `queued`에서 시작해 `waiting_input`, `waiting_executor`를 거쳐 `succeeded`로 끝남 |
| REQ-11-03 | executor 실행 기록이 사용자·세션·run과 묶임 | 4 | 실행 상태 `SUCCEEDED`, 사용자 = A의 사번, `metadata.run_id` = run ID, tenant `dtest-agent-service`, 런타임 값 있음 |
| REQ-11-04 | 채팅 결과 노트북이 pr-batch 배치로 실행 | 5 | 스크립트 등록·배치 생성 2xx, 배치 실행 상태가 `COMPLETED`로 끝남 |
| REQ-11-05 | 배치 실행이 executor에 A의 이름으로 기록 | 6 | 방식 `BATCH`, 사용자 = A의 사번, `created_by_client` = pr-batch 키 이름 |
| REQ-11-06 | 배치 리포트 생성 | 7 | `/batch-reports` 응답의 그 실행 리포트 `status: SUCCEEDED`, `artifact_id` 값 |
| REQ-11-07 | 서비스 사이 요청 추적 | 8 | 우리 로그와 executor 로그에 같은 `request_id` |
| REQ-14-01 | 요청 로그에 request id | 2 | 로그 메시지 끝에 `request_id=<응답 헤더 값>`이 있는 줄 1개 이상 |
| REQ-14-02 | 호출자가 준 request id 유지 | 3 | 응답 헤더 `X-Request-ID` = `it-req14-001`, 로그에 `api_client_request client=<키 이름> tenant=dtest-agent-service user=<사번> method=GET path=/api/v1/users/me status=200` 한 줄과 같은 request id |
| REQ-14-03 | 로그의 비밀값 가림 | 4 | 로그에 키 원문 없음(`***`로 표시) |
| REQ-14-04 | Agent 실행 맥락이 executor 기록에 전달 | 5 | executor 실행의 사용자·프로젝트·세션·`metadata.run_id`가 채팅의 값과 같음 |
| REQ-14-05 | 메모리 처리 로그 | 6 | `memory_extract_done project=<ID> …` 또는 `memory_extract_skipped project=<ID> … reason=…` 한 줄 |
| REQ-14-06 | Agent 트레이스(선택) | 7 | Phoenix에서 `session.id`가 세션 ID인 트레이스에 모델·tool 호출이 보임 |
| REQ-15-01 | tool이 만든 데이터 파일 저장 | 2 | `export_parquet` `SUCCEEDED`, `file_path` 값, `rows`가 집계 결과 행 수와 같음, `size_bytes` > 0 |
| REQ-15-02 | 노트북이 공유 스토리지에 저장 | 3 | `GET /executor/executions/{id}/notebook` 200, `storage.relative_path` 값 있음 |
| REQ-15-03 | JupyterLab에서 저장된 파일 열람 | 4 | `lab_url`의 경로가 `relative_path`와 같고 노트북이 열림 |
| REQ-15-04 | 실행 코드가 PV에 저장 | 5 | PV의 `sources/` 아래에 이 실행의 코드 파일 있음 |
| REQ-15-05 | 커널 종료 뒤에도 데이터 유지 | 6 | 커널 종료 뒤 `lab_url`과 `/artifacts/{id}/content` 모두 열림(200) |
| REQ-16-01 | 본인 실행 목록 조회 | 1 | `GET /executor/executions` 200, 항목의 사용자가 모두 A의 사번 |
| REQ-16-02 | 세션·상태 조건 조회 | 2 | 세션 ID 조건으로 그 세션의 실행만, 상태 조건 반영 |
| REQ-16-03 | 단계별 코드와 출력 조회 | 3 | `/executions/{id}`, `/steps`, `/steps/{step_id}` 200, 단계에 코드·상태·출력 |
| REQ-16-04 | 이벤트·노트북 조회 | 4 | `/events`, `/notebook`, `/notebook/cells/{n}` 200 |
| REQ-16-05 | 다른 사용자의 실행은 조회 불가 | 5 | B의 요청 403 또는 404, B 목록에 A의 실행 없음 |
| REQ-16-06 | 관리자 전체 조회와 진단 정보 | 6 | 관리자는 A의 실행 조회 200, `/diagnostics`·`/attempts` 200. 일반 사용자의 `/attempts`는 403 |
| REQ-17-01 | 실행별 artifact 목록 | 2 | `GET /executor/executions/{id}/artifacts` 200, 리포트·노트북 ID 포함 |
| REQ-17-02 | artifact 정보와 원문 | 3 | `GET /artifacts/{id}` 200(이름 `final-report.md`, metadata에 `session_id`·`run_id`), `/content` 200 |
| REQ-17-03 | 보기 화면 | 4 | `GET /view/artifacts/{id}` 리포트·노트북 모두 200 |
| REQ-17-04 | 프로젝트 멤버가 아닌 사용자는 조회 불가 | 5 | B의 요청 403 또는 404, 내용 없음 |
| REQ-17-05 | 키 호출자 조회와 tenant 격리 | 6 | 우리 tenant 키 + A 사번 200, 외부 tenant 키 403 또는 404, 없는 ID 404 |
| REQ-18-01 | 분석 노트북으로 배치 스크립트 등록 | 1 | `POST /batch/scripts/from-notebook` 201, 스크립트 버전 1, 노트북 내용 조회됨 |
| REQ-18-02 | 일정 있는 배치 생성 | 2 | `POST /batch/batches` 2xx, `can_enable: true`, tenant `dtest-agent-service` |
| REQ-18-03 | 즉시 실행 | 3 | 상태 `SUBMITTED → RUNNING → COLLECTING → COMPLETED`, executor 실행 방식 `BATCH`, 사용자 = A의 사번 |
| REQ-18-04 | 배치 리포트 생성 | 4 | 리포트 `status: SUCCEEDED`(최대 30분), `artifact_id` 값, 노트북 마지막 셀에 리포트 markdown |
| REQ-18-05 | 일정에 의한 실행 | 5 | 정한 시각 뒤 자동 실행 1건, `COMPLETED` |
| REQ-18-06 | 실패한 배치의 기록 | 6 | 배치 실행이 실패 상태, executor 실행 `FAILED`, 오류에 `it-fail` |
| REQ-18-07 | 같은 배치 반복 실행 | 7 | 실행 이력 2건, 실행 ID가 서로 다름 |
| REQ-19-01 | 프로젝트 메모리 조회(기본 주제) | 1 | `GET /projects/{id}/memory` 200, 주제 4개(`overview`, `preferences`, `core_interests`, `key_events`), 본문 비어 있음 |
| REQ-19-02 | 사용자 요청으로 Agent가 메모리에 저장 | 2 | `tool_call` `save_memory`, `memory_updated` 이벤트(`by: agent`), 메모리 응답에 그 줄(`author: agent`) |
| REQ-19-03 | 같은 프로젝트의 다른 대화에서 메모리 공유 | 3 | 새 대화의 그림 제목이 한국어 |
| REQ-19-04 | 사용자가 메모리 직접 수정 | 4 | `PUT /projects/{id}/memory/{topic}` 200, `version` 증가, `author: user`. 예전 `expected_version`은 409, 한도 초과는 422 |
| REQ-19-05 | 변경 이력과 되돌리기 | 5 | `GET …/memory/history`에 변경 기록, `POST …/memory/{topic}/revert` 뒤 본문이 이전 상태 |
| REQ-19-06 | 다른 프로젝트와 격리 | 6 | b의 메모리 비어 있음, b의 대화에 a의 선호 미적용 |
| REQ-19-07 | 사용자 요청으로 메모리 삭제 | 7 | `tool_call` `delete_memory`, 메모리 응답에서 그 줄 없음 |
| REQ-19-08 | 대화 뒤 자동 추출 | 8 | Core Interests에 관심 줄 1개, 로그 `memory_extract_done project=<ID> … parse_status=ok` |

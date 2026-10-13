# executor 코드 저장 체계 (설계안)

상태: 구현됨 (마이그레이션 0004). 결정 사항은 마지막 장에 있습니다.

## 1. 지금 방식과 문제

에이전트가 executor에 코드를 보낼 때 `SharedStorage.write_source`가 코드를 공유 PVC의 입력 영역에 파일로 쓰고, 그 경로를 PATH source로 넘깁니다.

```
{EXECUTOR_INPUT_ROOT}/agentic/sources/<sha 앞 2자>/<sha256>.py
```

- 내용 해시로만 이름을 붙여서 **누가, 어느 세션·run·단계에서 만든 코드인지 파일만 보고 알 수 없습니다.**
- 우리 DB에도 기록이 없습니다. 코드가 어떤 실행과 연결되는지는 run 이벤트와 executor 쪽 정보로 거꾸로 찾아야 합니다.
- 지우는 사람이 없습니다. 사용자·프로젝트 삭제나 보존 기간 정책을 적용할 방법이 없습니다.
- tool 코드는 `assets/tools`의 현재 파일로 만들어지는데, 어느 버전의 tool로 실행됐는지 남지 않습니다.

## 2. executor 쪽 사실 (조사 결과)

| 항목 | 내용 | 근거 (executor 레포) |
| --- | --- | --- |
| source 종류 | `INLINE {content}`(최대 256KiB), `PATH {path, sha256}`(`.py`, 최대 50MiB, 입력 루트 밖·절대경로·symlink 탈출 거부, sha256 일치 필수) | `src/executor_service/execution_specs.py` |
| 읽는 시점 | submit/append 요청을 받을 때 **한 번** 읽고, 실행별 불변 사본으로 복사합니다: `{SHARED}/executions/<exec>/sources/<step>/source.py` | `_result_storage/sources.py`, `commands.py` |
| 이후 | 재시도·failover·노트북 생성 모두 이 사본을 씁니다. **원본 파일은 submit이 받아들여진 뒤에는 바꾸거나 지워도 영향이 없습니다.** | `single_runner.py`, `multi_runner.py`, `notebook_projector.py` |
| executor가 남기는 것 | DB에 `source_path`(우리가 준 경로), `source_sha256`, 사본 경로, 크기, lineage(skill, tool, input_parameters). 코드 본문은 파일(사본, attempt별 `source.py`, `manifest.json`)과 노트북 셀에만 있습니다. API 응답에는 본문이 없습니다. | `db/_models/executions.py`, `_contracts/steps.py` |
| 정리 | 입력 영역은 호출자 소유입니다. executor는 입력 파일도, 실행 사본도 지우지 않습니다. | README "Retention" |
| 멱등성 | 같은 idempotency key로 다시 보내면 코드·경로·sha·lineage까지 비교합니다. 하나라도 다르면 409 충돌입니다. 단, 경로의 파일 내용이 바뀌었으면 멱등성 확인 전에 sha 검증에서 400이 납니다. | `_execution_service/support.py` |

결론적으로 **입력 영역의 파일은 "전달 수단"이고, 실행된 코드의 원본 기록은 executor의 불변 사본과 노트북입니다.** 우리 쪽에서 필요한 것은 (1) 안전하게 전달하고, (2) 무엇을 보냈는지 색인하고, (3) 전달용 파일을 정리하는 체계입니다.

## 3. 제안

### 3.1 저장 경로

서비스 전용 루트(`STORAGE_ROOT`) 아래 `sources/`에 둡니다. 서비스 루트는 executor 입력 PV(`INPUT_STORAGE_ROOT`) 안의 한 폴더여야 하고(executor는 그 아래만 읽음), executor에 넘기는 경로 앞에는 `STORAGE_EXECUTOR_PATH`(입력 루트 기준 같은 폴더)를 붙입니다.

```
{STORAGE_ROOT}/sources/
  users/<employee_id>/
    projects/<project_id>/
      sessions/<session_id>/
        runs/<run_id>/
          01-run_plan/                # executor operation 하나 (submit 또는 append 한 번)
            00-setup.py               # 새 실행(커널)이 시작될 때만
            01-tool-extract_data.py
            02-tool-transform_nce.py
          02-run_plan/                # conditional 판단 뒤 이어서 실행
            01-tool-boxplot_eda.py
          03-run_custom_code/
            01-custom-custom-1.py
```

| 환경 | `STORAGE_ROOT` | `STORAGE_EXECUTOR_PATH` | executor에 보내는 path 예 |
| --- | --- | --- | --- |
| 로컬 compose | `/mnt/executor-shared/agentic` | `agentic` | `agentic/sources/users/dev0001/…/01-run_plan/01-tool-extract_data.py` |
| k8s | `/mnt/data/agent/pr-agentic-service` | `pr-agentic-service` | `pr-agentic-service/sources/users/…` |

**경로 각 부분**

| 부분 | 값 | 이유 |
| --- | --- | --- |
| `users/<employee_id>` | 사번 (`[A-Za-z0-9_.-]` 밖의 문자는 `-`) | executor에 넘기는 `context.user_id`, 노트북 workspace 경로(`users/<사번>/…`)와 같은 값 |
| `projects/<id>`, `sessions/<id>` | 우리 DB UUID | 프로젝트·세션 단위로 찾기 |
| `runs/<run_id>` | 턴 UUID | 한 턴에 보낸 코드를 한 폴더에 |
| `<NN>-<도구>` | 이 턴에서 몇 번째 실행 도구 호출(`run_plan`, `run_custom_code`)인지 + 도구 이름 | executor operation 하나와 1:1. 번호는 체크포인트의 메시지 기록에서 계산하므로 재실행 때도 같음 |
| 파일 이름 | `<NN>-<kind>[-<name>].py` | operation 안에서 보낸 순서. `00-setup`은 새 커널일 때만, tool·custom은 01부터. `.py`는 executor가 요구 |

**규칙**

- **결정적 경로:** 같은 run, 같은 도구 호출, 같은 순번이면 항상 같은 경로입니다. HITL 재개나 Pod 장애 뒤 도구가 다시 실행돼도 경로가 바뀌지 않습니다.
- **한 번만 씀:** 파일이 이미 있으면 새로 만들지 않고 **있는 파일의 내용과 sha를 그대로 씁니다.** 그 사이 tool 파일이 수정돼도 executor에 처음과 같은 코드가 가므로, 멱등 재전송(같은 키는 같은 코드)이 깨지지 않습니다.
- **원자적 쓰기:** 같은 폴더에 임시 파일(`.<pid>.tmp`)로 쓴 뒤 `os.replace`. executor가 반쯤 쓴 파일을 읽지 않습니다.
- **권한:** 파일 `0644`, 폴더 `0755`. executor는 읽기만 합니다.
- **경로 검증:** 모든 부분을 안전 문자로 만든 뒤, 최종 경로가 입력 루트 밖으로 나가지 않는지 확인합니다(executor도 같은 검사를 함).
- **동시성:** 한 run은 lease를 가진 한 Pod만 실행하므로 같은 경로에 두 Pod가 동시에 쓰는 일은 없습니다. 그래도 원자적 교체라 마지막 쓰기만 남고 내용은 같습니다.

**정리 (보존 7일)**

- Retention 워커가 `code_sources.created_at`이 7일 지난 행의 파일을 지우고 `file_deleted_at`을 채운 뒤, 빈 폴더(`<NN>-<도구>`, `runs/<run_id>`, …)를 지웁니다.
- 세션·프로젝트 삭제는 지금처럼 소프트 삭제라 파일도 같은 7일 규칙을 따릅니다.
- 예전 해시 이름 파일(`sources/<sha 앞 2자>/<sha>.py`)은 executor가 이미 사본을 가지고 있으므로, 같은 워커가 수정 시각 기준 7일이 지나면 지웁니다.

### 3.2 DB 색인: `code_sources` 테이블

전달한 코드 한 건당 한 행. 실행 이력·감사와 파일 정리의 기준이 됩니다.

| 컬럼 | 설명 |
| --- | --- |
| id | |
| user_id, project_id, session_id, run_id | 소유와 run 연결 |
| tool_call_id | 코드를 보낸 에이전트 도구 호출 |
| kind | setup / tool / custom |
| skill, tool, call_key | tool 단계일 때 skill, tool, 계획의 호출 키(`1.0`) |
| tool_version | tool 파일의 sha256 (어느 버전의 tool로 만들었는지) |
| purpose, approved_by, edited | custom일 때 목적, 승인한 사용자, 사용자가 승인 화면에서 코드를 고쳤는지 |
| path, sha256, size_bytes | 우리가 보낸 PATH source |
| execution_id, operation_id, step_id | executor 접수 응답에서 채움 |
| created_at, file_deleted_at | 전달 파일 정리 여부 |

- 행은 파일을 쓴 직후, submit 전에 넣습니다. path가 유니크라 재실행 때는 기존 행이 그대로 남습니다.
- submit이 성공하면 같은 트랜잭션은 아니어도 `execution_id`, `step_id`를 채웁니다. 이 값이 비어 있는 행은 "보냈지만 접수가 확인되지 않은 것"으로 볼 수 있습니다.
- 본문은 DB에 넣지 않습니다. 실행된 코드는 노트북과 executor 사본(step 결과 manifest의 `source.relative_path`)에서 확인합니다.

### 3.3 구현 위치

- `core/executor/storage.py`: `write_source(code, relative)` 한 번만 쓰기, `delete_source(path)` 파일과 빈 폴더 삭제
- `core/executor/sources.py`: 경로 규칙(`SourceOwner.folder`, `file_name`), `CodeSources.write / link / purge`
- `core/models.py` + 마이그레이션 `0004`: `code_sources`
- `agent/tools/analysis.py`: `run_plan`, `run_custom_code`, setup 단계가 새 경로로 쓰고, 접수 후 execution·operation·step id 기록
- `worker/maintenance.py`: 7일 정리(새 경로와 예전 해시 이름 파일)

## 4. 대안: INLINE source

우리 코드는 단계당 수 KB라서 executor의 INLINE(최대 256KiB)으로도 충분합니다. INLINE을 쓰면 PVC 쓰기와 정리 작업이 아예 없어지고, 색인(`code_sources`)만 남습니다. executor는 INLINE도 같은 방식으로 불변 사본을 만듭니다.

- 장점: 공유 볼륨 쓰기 권한·마운트가 필요 없고, 파일 정리도 필요 없습니다. Pod에서 입력 PVC 마운트를 빼도 됩니다(결과 읽기용 마운트는 남음).
- 단점: 256KiB를 넘는 코드는 PATH로 보내야 해서 두 경로가 생깁니다. 본문이 우리 쪽에 남지 않아 executor 사본에 의존합니다(DB에 본문을 넣으면 해결).
- 재전송 멱등성 때문에 INLINE이면 보낸 코드 본문을 우리 쪽에 보관해야 하고, 실패한 요청 본문이 executor 로그에 남을 수 있습니다. 검토 후 PATH 유지로 결정했습니다.

## 5. 결정 사항

| 항목 | 결정 |
| --- | --- |
| 전달 방식 | PATH 유지 |
| 전달 파일 보존 | 7일 |
| 코드 본문 보관 | executor 사본과 노트북에 의존 (우리 DB에는 색인만) |
| 저장 루트 | 서비스 전용 루트(`STORAGE_ROOT`) 아래 `sources/` |
| 폴더 단위 | executor operation 하나 = 폴더 하나 (`<NN>-<도구>`) |
| 사용자 경로 | 사번 |
| 코드 조회 API·"코드 보기" | 넣지 않음 (노트북으로 확인) |

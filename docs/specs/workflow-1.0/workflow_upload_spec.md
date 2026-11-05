# 워크플로우 업로드 규격

사람이 작성한 워크플로우를 화면이나 API로 직접 등록할 때 따르는 규격이다. 워크플로우 문서 자체의 구조는 [Workflow 표준 규격 1.0](workflow_spec_1.0.md)을 따르고, 이 문서는 그 문서를 **업로드 파일**로 감싸는 방법과 서버가 등록 전에 확인하는 규칙을 정리한다.

## 1. 올리는 방법

| 경로 | 방법 |
|---|---|
| 화면 | 워크플로우 탭 → **워크플로우 업로드** → `.json` 파일 선택 또는 문서 붙여넣기 → **검증** → **등록** |
| API | `POST /api/v1/workflows/validate`(검증만) → `POST /api/v1/workflows`(등록) |

등록된 워크플로우는 **후보(candidate)** 다. 작성자에게만 보이고 추천 대상이 아니다. 상세 화면의 **공개(승격)**, 또는 `POST /api/v1/workflows/{id}/promote`로 **공개(template)** 하면 모든 사용자의 계획 추천 후보가 된다. 승격 권한은 `WORKFLOW_PROMOTION` 설정을 따른다. `author`(기본)면 작성자가, `admin`이면 SSO로 로그인한 관리자만 승격한다.

## 2. 업로드 파일 형식

업로드 파일은 UTF-8 JSON이며, 다음 두 형식 중 하나다.

**(A) 업로드 파일(권장)**: `POST /workflows` 요청 본문과 같은 형식이다.

```json
{
  "document": { "workflow_version": "1.0", "workflow": { "...": "..." } },
  "user_queries": ["NCE 표본 뽑아서 기술통계랑 히스토그램 보여줘"],
  "tags": ["nce", "eda"]
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `document` | object | 예 | Workflow 1.0 문서 ([workflow_spec_1.0.md](workflow_spec_1.0.md)) |
| `user_queries` | string[] | 예 | 추천 질문. **최소 1개**. 이런 질문이 오면 이 워크플로우를 추천한다. 앞뒤 공백을 지우고 빈 값과 중복을 버린 뒤, 질문당 4000자, 최대 1000개까지 저장한다 |
| `tags` | string[] | 아니요 | 분류 태그. 소문자로 바꾸고 중복을 없애 정렬해 저장한다. 기본값 `[]` |

**(B) Workflow 1.0 문서만**: `workflow_version`과 `workflow`로 시작하는 문서다. 화면에서만 받는다. 추천 질문은 자동으로 채우지 않으므로 화면의 **추천 질문** 칸에 직접 적어야 등록된다. API로 보낼 때는 (A) 형식으로 감싸야 한다.

예시 파일: [workflow_upload.example.json](workflow_upload.example.json). [workflow_static.example.json](workflow_static.example.json)을 (A) 형식으로 감싼 것이다.

## 3. 문서 작성 규칙 요약

전체 규칙은 [workflow_spec_1.0.md](workflow_spec_1.0.md)를 따른다. 업로드에서 자주 틀리는 항목은 다음과 같다.

| 항목 | 규칙 |
|---|---|
| `workflow_version` | `"1.0"` 고정 |
| `workflow.actor` | 필수. 사람이 작성했으면 `{"type": "USER", "id": "<사번>"}` |
| `workflow.name`, `workflow.user_request` | 필수, 빈 문자열 불가. 화면의 **이름**·**목적** 칸 값이 문서에 덮어써진다 |
| `workflow.execution_mode` | 서버가 다시 계산한다. `conditional` Tool이 하나라도 있으면 `adaptive`, 없으면 `static` |
| `workflow.allow_immediate_execution` | 필수 boolean. `true`여도 실제 즉시 실행은 서버 정책(유사도 `WORKFLOW_AUTO_RUN_SIMILARITY`, 필수 입력 충족)에 따른다 |
| 정의되지 않은 필드 | 스키마가 `additionalProperties: false`라 거부된다 |

## 3-1. 실행 방식 (등록된 워크플로우)

| 실행 방식 | 조건 | 실행 |
|---|---|---|
| static | 모든 Tool이 `always` | 에이전트는 파라미터만 채운다(모르는 값은 사용자에게 묻는다). executor **SINGLE** 실행 한 번으로 정의된 그대로 돈다. 인자 수정, 재실행, 코드 추가가 없고, 실패하면 리포트 없이 실패로 끝나며 에이전트가 원인을 설명한다 |
| adaptive | `conditional` Tool이 하나 이상 | 파라미터 처리는 static과 같다. executor **MULTI** 실행에서 앞 결과를 보고 conditional Tool의 실행 여부를 에이전트가 그때그때 정한다 |

에이전트가 새로 짠 계획(등록된 워크플로우가 아닌 것)은 이 구분 없이 MULTI로 실행한다.

## 4. 서버 검증 규칙

`/workflows/validate`와 `/workflows`(등록)는 같은 검증을 거친다. 먼저 구조 검증([workflow_schema_1.0.json](workflow_schema_1.0.json))을 하고, 통과하면 현재 서버에 등록된 analysis 카탈로그로 의미 검증을 한다.

| 규칙 | 실패 메시지 예 |
|---|---|
| `steps[].skill`은 등록된 Skill이어야 한다 | `unknown skill 'x'` |
| `tools[].tool`은 그 Skill의 Tool 목록에 있어야 한다 | `tool 'x' does not belong to skill 'y'` |
| `tools[].execution`은 Skill 정의의 실행 방식(항상/조건부)과 같아야 한다 | `'x' must be 'conditional' per skill 'y'` |
| Tool 코드가 정상적으로 로드되어야 한다 | `unknown tool 'x'`, `tool 'x' failed to load: ...` |
| `arguments`의 키는 Tool 함수의 파라미터여야 한다 | `'x' has no parameter 'p'` |
| 기본값이 없는 파라미터는 반드시 `arguments`에 있어야 한다 | `'x' is missing required parameter 'p'` |
| `tool_output`은 앞선 호출만 참조한다 | `tool_output must reference an earlier call` |
| `tool_output.output`은 참조한 Tool의 출력 이름이어야 한다 | `'x' has no output 'o' (['data', ...])` |
| `always` 호출은 `conditional` 호출의 출력에 기댈 수 없다 | `an always-run call cannot depend on conditional call 1.0` |

출력 이름은 Tool 함수가 `return {"data": ..., "query": ...}`처럼 dict 리터럴을 돌려주면 그 키들이고, 그렇지 않으면 `result` 하나다. Skill과 Tool의 정의는 서버의 `assets/skills`, `assets/tools`(와 `CATALOG_EXTENSIONS`로 더한 카탈로그)에 있다. Skill 문서의 **Tool list** 표에 Tool별 실행 방식이 있다. 다른 환경에서 만든 워크플로우는 카탈로그가 다르면 검증에 실패할 수 있다.

## 5. 응답과 오류

| 요청 | 성공 | 실패 |
|---|---|---|
| `POST /workflows/validate` (본문: Workflow 1.0 문서) | `200 {"valid": true, "document": <정규화된 문서>}` | `200 {"valid": false, "errors": ["steps[0].tools[1]: ...", ...]}` |
| `POST /workflows` (본문: 2절 (A) 형식) | `201` 등록된 워크플로우(`id`, `lifecycle: "candidate"`, `revision: 1`, `index_state` 등) | `422 INVALID_WORKFLOW`: `details[]`마다 문서 안의 위치(`location`)와 이유. `user_queries`가 비었거나 형식이 틀리면 일반 요청 검증 오류(422) |

등록하면 추천 질문이 색인된다(임베딩이 설정된 경우). `index_state`가 `ready`가 아니면 공개해도 추천에 걸리지 않는다. 상세 화면의 안내를 따르거나 `POST /workflows/{id}/reindex`로 다시 색인한다.

## 6. 같은 워크플로우를 다시 올릴 때

업로드는 항상 **새 워크플로우**를 만든다. 이름이 같아도 덮어쓰지 않는다. 이미 있는 워크플로우를 고치려면 상세 화면의 **수정**, 또는 `PATCH /workflows/{id}`(`expected_revision` 필수)를 쓴다. 남의 워크플로우는 **복제**한 뒤 고친다.

## 7. curl 예

```bash
# 검증만
jq '.document' workflow_upload.example.json \
  | curl -sS -X POST "$BASE/api/v1/workflows/validate" \
      -H 'Content-Type: application/json' -H "X-Api-Key: $API_KEY" -H "X-User-Id: $EMPLOYEE_ID" -d @-

# 등록
curl -sS -X POST "$BASE/api/v1/workflows" \
  -H 'Content-Type: application/json' -H "X-Api-Key: $API_KEY" -H "X-User-Id: $EMPLOYEE_ID" \
  -d @workflow_upload.example.json
```

API 키로 부르면 `X-User-Id`의 사용자가 작성자가 된다. SSO 세션(쿠키 + `X-CSRF-Token`)으로 부르는 방법과 자세한 인증 규칙은 [api-guide.md](../../api-guide.md)를 따른다.

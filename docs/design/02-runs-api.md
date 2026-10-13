# 에이전트 실행 API: `POST /sessions/{session_id}/runs` (설계안)

상태: 구현됨 (마이그레이션 0005, 0006). 결정 사항은 마지막 장에 있습니다. 프론트 연동 요약은 [api-guide.md](../api-guide.md).

에이전트를 시작하는 것과 멈춘 run을 이어 가는 것을 하나의 API로 받습니다. 지금의 `POST /sessions/{id}/messages`(시작)와 `POST /runs/{id}/resume`(재개)를 대체합니다. `GET /sessions/{id}/messages`는 읽기 전용 대화 기록으로 남고, 취소는 `POST /runs/{id}/cancel` 그대로입니다.

## 1. 요청

```http
POST /api/v1/sessions/{session_id}/runs
Content-Type: application/json
X-CSRF-Token: …
Idempotency-Key: 7f0c…            (선택, 권장)
```

본문은 `input`과 `command` 중 **정확히 하나**를 담습니다.

### 1.1 새 턴: `input`

```json
{
  "input": {"content": "NCE와 WT 결합해서 탐색 분석해줘"},
  "model": "qwen38-27b-nvfp4"
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `input.content` | string(1~20000자) 또는 content block 목록(1.6) | 예 | 사용자 메시지. 대화 기록(`messages`)에 user 메시지로 저장됩니다. |
| `model` | string | 아니요 | `GET /models`의 `items[].name` 중 하나(1.5). 없으면 기본 모델. 이 run이 끝날 때까지 유지됩니다. |

`code_level`은 받지 않습니다. 세션(`PATCH /sessions/{id}`)이나 프로젝트 설정을 따릅니다.

### 1.2 재개: `command.resume`

```json
{
  "command": {
    "resume": {
      "interrupt_id": "cddaffd84a6afa6c2f8c76848605a8c0",
      "value": {"action": "approve", "index": 0, "input_values": {"0.0.lot_cd": "L1"}}
    }
  }
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `command.resume.interrupt_id` | string | 예 | `hitl_request` 이벤트나 `Run.waiting.interrupt_id`의 값 |
| `command.resume.value` | 확인 종류별 (아래 표) | 예 | 사용자의 답 |

재개 때 `model`은 받지 않습니다(그 run의 모델을 유지).

**`value` 형식 (확인 종류 = `Run.waiting.type`)**

| type | value | 서버 검사 |
| --- | --- | --- |
| `question` | 문자열, 또는 `fields`가 있으면 `{<key>: 값}` | `fields[].required` 키가 비어 있으면 422 |
| `plan_approval` | `{"action": "approve", "index": n, "input_values": {"<s>.<t>.<param>": 값}, "overrides": {"<s>.<t>.<param>": 값}}` | `index`가 후보 범위 안인지, 그 후보의 `input_slots` 중 `required`가 모두 채워졌는지, `overrides` 키가 그 후보의 파라미터인지 |
| | `{"action": "revise", "feedback": "..."}` | `feedback` 1자 이상 |
| | `{"action": "cancel"}` | |
| `code_approval` | `{"approve": true, "code": "수정한 코드(선택)"}` / `{"approve": false, "feedback": "..."}` | `approve` 불리언 필수 |
| `memory_change` | `{"approve": true \| false}` | `approve` 불리언 필수 |
| `workflow_save` | `{"approve": true, "name": "...", "user_queries": [...]}` / `{"approve": false}` | `approve` 필수, `user_queries` 1개 이상(승인 시) |

지금은 "객체인지"만 보고 나머지는 에이전트 안에서 처리해서, 잘못된 답이 와도 202 후 에이전트가 다시 묻습니다(리뷰 H2). 이 표대로 API에서 먼저 검사합니다.

### 1.3 대기 중에 `input`이 온 경우 (결정 필요)

세션이 확인을 기다리는 중(`waiting_input`)에 사용자가 채팅창에 글을 쓰면 `input`이 옵니다. 두 가지 안이 있습니다.

- **A. 409로 거절 (지금 방식):** 프론트는 확인 카드에 답하거나 취소해야 다음 메시지를 보낼 수 있습니다.
- **B. 기다리던 확인에 대한 글 답으로 처리:** 서버가 `content`를 확인 종류에 맞는 `value`로 바꿔 재개합니다.

| 기다리던 type | B안에서 `content`가 되는 것 |
| --- | --- |
| `question` | 답 문자열 그대로 |
| `plan_approval` | `{"action": "revise", "feedback": content}` |
| `code_approval` | `{"approve": false, "feedback": content}` |
| `memory_change`, `workflow_save` | `{"approve": false}`로 닫고, `content`는 에이전트에게 이어서 전달 |

B안에서는 그 글도 대화 기록에 user 메시지로 남깁니다.

### 1.4 `Idempotency-Key`

- 같은 세션에서 같은 키로 다시 오면 처음 만든(또는 재개한) run을 그대로 돌려주고 아무것도 새로 하지 않습니다. 본문이 다르면 409 `idempotency_conflict`.
- 24시간 보관. 네트워크 재시도로 같은 질문이 두 번 도는 것을 막습니다(리뷰 M2).

### 1.5 모델 지정: `model_alias` → `model` (결정)

지금은 `LLM_MODELS={"default": "qwen38-27b-nvfp4", "fp8": "qwen38-27b-fp8"}`처럼 별칭을 두고, 요청에는 별칭(`default`, `fp8`)을 보냅니다.

필드 이름을 `model`로 바꾸고 값은 **게이트웨이 모델 이름**(`qwen38-27b-nvfp4`)을 그대로 씁니다. 서버는 허용 목록(카탈로그)에 있는 이름만 받습니다.

```json
{"input": {"content": "…"}, "model": "qwen38-27b-nvfp4"}
```

**카탈로그 설정: 프로젝트 루트의 환경별 설정 파일 `config.<ENV>.yml`의 `models`** (설정 파일 체계는 [03-config.md](03-config.md))

```yaml
# config.<ENV>.yml (레포 루트)
models:
  - name: qwen38-27b-nvfp4      # 게이트웨이 모델 이름 = API의 model 값
    label: Qwen 3.8 27B         # 화면 표시 이름 (선택, 없으면 name)
    default: true               # 정확히 하나
    input: [text]
  - name: example-vl-model
    label: 예시 비전 모델
    input: [text, image]
    max_images: 8
```

- **여기 적힌 모델만 씁니다.** 게이트웨이 목록 조회나 캐시는 하지 않습니다. 모델 추가·삭제는 운영자가 이 파일을 고쳐서 합니다.
- `default: true`는 정확히 하나여야 하고, 기동 시 검사해서 0개나 2개 이상이면 시작하지 않습니다. `name` 중복도 같습니다.
- 배포 환경에서는 ConfigMap·Secret을 쓸 수 없으므로, 설정 파일은 이미지에 복사해 읽습니다. 모델을 바꾸려면 파일 수정 후 이미지를 다시 빌드·배포합니다(로컬 compose는 마운트해서 바로 반영).
- 지금의 `LLM_MODELS`, `LLM_DEFAULT_ALIAS` 환경변수는 없앱니다.
- 모델 이름과 이미지 입력 여부는 배포 환경마다 다르므로 환경별 설정 파일에서 운영자가 정합니다. 로컬에서는 `qwen38-27b-nvfp4` 하나만 씁니다. 도구 호출 동작은 넣기 전에 확인이 필요합니다.

**모델 목록 API: `GET /api/v1/models`** (`/users/me`에서 분리)

```json
{"items": [
  {"name": "qwen38-27b-nvfp4", "label": "Qwen 3.8 27B", "default": true,  "input": ["text"], "max_images": 0},
  {"name": "example-vl-model", "label": "예시 비전 모델", "default": false, "input": ["text", "image"], "max_images": 8}
]}
```

`/users/me`는 사용자 정보와 `default_project_id`만 남기고, `default_code_level`은 프로젝트·세션 응답의 `effective_code_level`(실제 적용될 값)로 옮깁니다.

`Run.model_alias`는 `Run.model`(실제 이름)로 바꿉니다.

### 1.6 이미지 입력 (VLM 대비)

1단계는 **이미지만** 받고, 파일(문서·데이터)은 나중에 붙입니다. 이미지는 별도 업로드 없이 run 요청 안에 함께 받습니다.

**형식: LangChain 표준 content block.** `input.content`는 문자열 또는 블록 목록입니다. LangGraph(`HumanMessage.content`, LangGraph 서버 API의 `input.messages[].content`)와 같은 틀입니다.

```json
{
  "input": {
    "content": [
      {"type": "text", "text": "이 웨이퍼 맵에서 이상 패턴 찾아줘"},
      {"type": "image", "base64": "iVBOR…", "mime_type": "image/png", "name": "wafer_map.png"}
    ]
  },
  "model": "example-vl-model"
}
```

| 블록 | 필드 | 설명 |
| --- | --- | --- |
| `text` | `text` | 1자 이상. 블록 목록에 text가 하나 이상 있어야 함 |
| `image` | `base64`, `mime_type`, `name?` | `image/png`, `image/jpeg`, `image/webp`만. `url` 블록은 받지 않음(서버가 외부 URL을 가져오지 않도록) |

- 한도(제안): 장당 10MB(디코딩 후), 요청당 최대 `max_images`장(모델 카탈로그, 기본 8), 합계 20MB.
- 텍스트 전용 모델에 이미지가 있으면 422 `model_not_multimodal`.
- 문자열 `content`는 지금처럼 그대로 받습니다.

**서버 처리**

1. base64를 풀고 Pillow로 실제 이미지인지 확인, 긴 변이 1568px를 넘으면 줄임
2. `{STORAGE_ROOT}/images/users/<사번>/projects/<p>/sessions/<s>/<image_id>.<ext>`에 저장, DB `images` 테이블(id, 세션, 업로더, 이름, mime, 크기, 가로·세로, sha256, 경로, created_at)
3. 대화 기록: user 메시지의 `attachments`에 `{kind: "image", image_id, name}`. 화면은 `GET /api/v1/images/{id}`로 그림
4. **체크포인트에는 참조만:** 사용자 메시지 블록을 `{"type": "image", "file_id": "<image_id>", "mime_type": …}`로 바꿔 넣고, 모델을 부르기 직전에 middleware가 최근 N턴(기본 3)의 이미지만 실제 데이터로 채움. 그보다 오래된 이미지는 "[이미지: wafer_map.png]" 글로 남김
5. 분석 담당으로 넘어가도 같은 메시지 기록을 보므로 같은 규칙으로 이미지를 봄

**보존:** 세션이 살아 있는 동안 유지, 세션 삭제(소프트) 후 7일 뒤 지움.

**나중에 파일을 붙일 때:** `{"type": "file", …}` 블록(업로드 id 참조)을 추가하면 됩니다. 커널에서 업로드 데이터를 읽으려면 executor 런타임의 입력 PV 마운트가 필요합니다(로컬 compose 기준 지금은 안 보임).

## 2. 응답

```http
202 Accepted
{
  "run": { "id": "…", "session_id": "…", "status": "queued", "model": "qwen38-27b-nvfp4",
           "waiting": null, "error": null, "created_at": "…", "updated_at": "…", "finished_at": null },
  "resumed": false
}
```

- 새 턴이면 `resumed: false`와 새 run, 재개면 `resumed: true`와 기다리던 그 run(같은 id)입니다.
- 진행은 지금처럼 `GET /sessions/{id}/events`(SSE)로 받습니다.

## 3. 오류

본문은 `{"detail": "사람이 읽는 설명", "code": "기계가 읽는 코드", ...추가 정보}` 형태로 통일합니다(리뷰 L3).

| 상태 | code | 언제 | 추가 정보 |
| --- | --- | --- | --- |
| 409 | `session_busy` | 새 턴인데 다른 run이 돌고 있음 (A안이면 확인 대기 중일 때도) | `run` (진행 중인 run) |
| 409 | `not_waiting` | 재개인데 run이 확인을 기다리지 않음 (이미 답해서 진행 중이거나 끝남) | `run` |
| 409 | `stale_interrupt` | 재개인데 `interrupt_id`가 지금 기다리는 질문이 아님 (오래된 화면) | `run` (현재 `waiting` 포함) |
| 409 | `idempotency_conflict` | 같은 키, 다른 본문 | |
| 422 | `invalid_body` | `input`과 `command`가 둘 다 있거나 둘 다 없음, 형식 오류 | `errors` |
| 422 | `invalid_answer` | 확인 종류별 검사 실패 | `errors`: `[{"field": "input_values.0.0.lot_cd", "message": "필수 입력입니다"}]` |
| 422 | `unknown_model` | `model`이 카탈로그에 없음 | `models` |
| 422 | `model_not_multimodal` | 텍스트 전용 모델에 이미지 첨부 | `models` (이미지 가능한 모델) |
| 422 | `invalid_image` | 이미지가 아니거나 형식·개수 초과 | `errors` |
| 413 | `image_too_large` | 이미지 크기 한도 초과 | `max_bytes` |
| 404 | `not_found` | 세션이 없거나 접근 권한 없음 | |
| 403 | `read_only` | 읽기 전용 멤버 | |

`not_waiting`과 `stale_interrupt`에 현재 run을 담아서, 프론트가 더블 클릭은 무시하고 오래된 화면은 새로 그릴 수 있게 합니다(리뷰 M3).

## 4. 함께 바뀌는 것

- `POST /projects/{id}/sessions`의 `message`를 `input: {content}`로 바꿔 같은 형식을 씁니다. 세션 생성과 첫 run 생성은 한 트랜잭션으로 묶어서, 모델 별칭이 틀리면 세션도 만들지 않습니다(리뷰 H1).
- `POST /sessions/{id}/messages`와 `POST /runs/{id}/resume`은 없앱니다(프론트가 아직 없으므로 호환 기간 없이).
- `docs/api-guide.md`, 테스트 콘솔, `scripts/smoke_e2e.py`를 새 API로 바꿉니다.

## 5. 결정 사항

| 항목 | 결정 |
| --- | --- |
| 시작·재개 API | `POST /sessions/{id}/runs` 하나 (`input` 또는 `command.resume`) |
| 대기 중 `input` | B안: 기다리던 확인에 대한 글 답으로 처리, 글은 대화 기록에 남김 |
| 확인 응답(승인 등) 기록 | 대화 기록에 남기지 않음 (run 이벤트에만) |
| 응답 형태 | `{run, resumed}` |
| 모델 지정 | 모델 이름, 설정 파일 `models` 목록만 사용, `default: true`로 기본 지정, `GET /models` |
| 이미지 | 1단계는 이미지만, run 요청 안에 LangChain content block, 체크포인트에는 참조만 |
| 코드 레벨 기본값 | `/users/me`에서 빼고 프로젝트·세션 응답의 `effective_code_level` |

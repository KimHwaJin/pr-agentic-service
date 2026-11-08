# Executor gateway: guide for coding agents

You are writing a client that runs Python code through the **executor gateway** of pr-agentic-service. This one file is enough to write that client. Read the rules first. Use the TypeScript types at the end (and `openapi/executor-gateway.openapi.json`) as the exact field contract.

- Base path: `{BASE_URL}/api/v1/executor`. `BASE_URL` is `http://localhost:8080` locally. Other environments get it from config (the service's public API origin).
- Every route below is relative to that base path. Any route not listed here returns `404 NOT_FOUND`.
- The gateway relays to the executor. Request and success response bodies are the executor's own, unchanged. The gateway checks the key and user, sets the identity headers itself, and decides the read scope.

## 1. Rules

### MUST

1. Send `X-Api-Key: <key>` on every request. Read the key from config or an env var (e.g. `AGENTIC_API_KEY`). Never hard-code it or log it. Keys look like `pas_live_…` (local/dev: `pas_dev_…`).
2. Send `X-User-Id: <employee id>` on **every** request, reads included. Use the user your service authenticated, lower case, matching `^[a-z0-9][a-z0-9._-]{0,63}$`. If it is missing or malformed, you get `400 INVALID_IDENTITY`.
3. Send `Content-Type: application/json` on every POST.
4. Generate one `idempotency_key` (a UUID string, 1–255 chars) per logical write **before** the first attempt. Put it in the JSON body (not a header). Reuse the same key **and the same body** on every retry of that write.
5. Treat every write (submit, add operation, finalize, cancel, retry) as asynchronous. `202` means accepted and queued. Poll for the outcome (section 4).
6. Branch on `error.code`, never on `error.message` or on the HTTP status alone.
7. Use `INLINE` code sources: `{"type": "INLINE", "content": "<python>"}`.
8. Read raw cell output only through the notebook routes (`/notebook?view=FULL`, `/notebook/cells/{n}`). Download files only through `/artifacts/{artifact_id}/content`.
9. For MULTI commands, send `expected_version` = the `state.version` you read just before.
10. Pass `next_cursor` back as `cursor` unchanged. Stop when `next_cursor` is `null`.

### MUST NOT

1. Do not send `tenant_id`, `context`, `actor`, `created_by` or any other unknown field in a request body. Request schemas reject unknown fields with `422 REQUEST_VALIDATION_ERROR`.
2. Do not send `X-Tenant-Id`. It is ignored, because the key fixes the tenant.
3. Do not call the executor directly, and do not use executor keys. Only this gateway.
4. Do not open `result_ref.relative_path`. It is an internal storage path that callers cannot read.
5. Do not send `Range` (it is not forwarded; a file always comes whole with `200`), `Idempotency-Key`, or `If-Match`. None of them is forwarded.
6. Do not use a `PATH` code source. External callers cannot write to the executor's input storage.
7. Do not poll faster than every 2 seconds, and do not retry 4xx errors unchanged (except as in section 5).
8. Do not reuse an idempotency key for a different body. That returns `409 IDEMPOTENCY_CONFLICT`.

## 2. Headers

| Header | When | Value |
| --- | --- | --- |
| `X-Api-Key` | always | the issued key |
| `X-User-Id` | always | acting user (employee id). Writes are recorded as this user (`created_by`) |
| `X-Project-Id` | optional | `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$`, not `unscoped`. Stored only on `POST /executions` (into `context.project_id`). Other routes check the format and ignore it |
| `X-Session-Id` | optional | same format. Needs `X-Project-Id` (otherwise `400`). Stored only on submit |
| `Content-Type` | POST | `application/json` |

Response headers you may use: `Content-Type`, `ETag` (artifact content: SHA-256), `Location` (submit), `Content-Disposition` (artifact file name), `X-Request-ID` (quote it when reporting a problem).

`Location` is the executor's own path (`/api/v1/executions/{id}`). Rewrite `/api/v1/` to `/api/v1/executor/` before following it, or simply build the URL from `execution_id`.

If the key belongs to the agentic service's own tenant (`dtest-agent-service`), `X-User-Id` must be an active user of that service (else `403 FORBIDDEN`). `X-Project-Id` must be a project that user is a member of, and `X-Session-Id` a session of that project (else `404`). Keys of other tenants only get format checks.

## 3. Read scope: standard key vs master key

A key is `standard` (default) or `master`. The kind changes **only what reads return**. Writes behave the same for both.

| | standard key | master key |
| --- | --- | --- |
| `GET /executions` | only the `X-User-Id` user's executions | the whole tenant |
| query `user_id` | optional; if sent it must equal `X-User-Id`, else `403 FORBIDDEN` | narrows the list to that user |
| detail routes (`/executions/{id}/…`, `/artifacts/{id}…`) | someone else's execution → `404` | any execution in the tenant |
| writes | made as `X-User-Id` | made as `X-User-Id` |

- A malformed `user_id` query returns `400 INVALID_IDENTITY`.
- The `tenant_id` query is always dropped.
- `404` never tells "does not exist" apart from "not yours or another tenant's".
- Your client does not need to know its key kind, except to avoid a `user_id` filter on a standard key.

## 4. Flows

### 4.1 SINGLE: run once

```
POST /executions                        → 202 {execution_id, state:{status:"QUEUED", version}}
GET  /executions/{id}                   → repeat every 2–5 s until state.status is terminal
GET  /executions/{id}/result            → per-step status, error_message, output_summary
GET  /executions/{id}/notebook?view=FULL → code and raw outputs (only if needed)
```

Submit body (minimal):

```json
{
  "idempotency_key": "6f1c9a52-3d1e-4c55-9a43-1f0e2a7b9c10",
  "lifecycle": {"operation_mode": "SINGLE"},
  "trigger": {"type": "INTERACTIVE"},
  "runtime": {"type": "JUPYTER", "profile": "default"},
  "operation": {
    "operation_timeout_seconds": 600,
    "spec": {
      "schema_version": "1.0",
      "steps": [
        {"sequence": 0,
         "payload": {"type": "PYTHON_EXECUTE",
                     "source": {"type": "INLINE", "content": "import pandas as pd\nprint(pd.__version__)"}},
         "step_timeout_seconds": 300}
      ]
    },
    "metadata": {}
  },
  "metadata": {"caller_task_id": "t-100"}
}
```

Field rules:

- `trigger.type`: `INTERACTIVE` (online) or `BATCH`. It picks the kernel pool. MULTI requires `INTERACTIVE`.
- `runtime.profile`: kernel environment. The default is `default`. Valid values are the `profile`s from `GET /api/v1/batch/runtimes` (same key).
- `steps`: 1–100 per operation, 1000 per execution. `sequence` starts at 0 and is contiguous across the **whole execution**.
- `step_timeout_seconds` and `operation_timeout_seconds` are ≥ 1 and optional (no limit when absent, up to the executor's maximum run time).
- `lifecycle.operation_wait_timeout_seconds` is MULTI only (≥ 30). Sending it with SINGLE is a 422.
- `metadata`: at most 32 keys matching `^[a-z][a-z0-9_]{0,63}$`, at most 4096 bytes of JSON. Never put secrets in it.
- Step `lineage` (`{skill_name?, tool_name?, input_parameters?}`) is optional and stored as given.

### 4.2 MULTI: inspect, then continue

The kernel stays alive between operations, so variables persist.

```
POST /executions  lifecycle = {"operation_mode":"MULTI","operation_wait_timeout_seconds":600}, trigger.type = INTERACTIVE
GET  /executions/{id}            until status == WAITING_FOR_OPERATION; remember state.version
GET  /executions/{id}/operations/{operation_id}/result   (or /result, /notebook)
POST /executions/{id}/operations {idempotency_key, expected_version, spec:{schema_version:"1.0", steps:[{sequence: next…}]}}
     … repeat until done …
POST /executions/{id}/finalize   {idempotency_key, expected_version}
GET  /executions/{id}            until SUCCEEDED / FAILED
```

- The add-operation body has `spec`, `operation_timeout_seconds` and `metadata` at top level. Do **not** resend `lifecycle`, `trigger`, `runtime` or `operation`.
- The next step `sequence` continues from the last one. For example, if the first operation used 0 and 1, the next one starts at 2.
- The `202` reply gives the new `state.version` and `operation.operation_id`.
- A stale `expected_version` returns `409 EXECUTION_VERSION_CONFLICT`. Re-read the state, then decide. The version check runs before step validation.
- Within `operation_wait_timeout_seconds` you must add an operation or finalize. Otherwise the execution ends by itself (`state.finalized_by = "WAIT_TIMEOUT"`). Reads do not extend the deadline (`deadlines.operation_wait_expires_at`).
- `finalize` works only in `WAITING_FOR_OPERATION` after a **succeeded** last operation. Otherwise it returns `409 INVALID_STATE_TRANSITION`. After a failed operation, add a fixed operation or cancel.
- For MULTI, idempotency keys of added operations are scoped to the execution. Submit keys are scoped to the tenant.

### 4.3 Cancel and retry

- `POST /executions/{id}/cancel` `{"idempotency_key", "reason"?}` (reason ≤ 2000 chars) → `CANCEL_REQUESTED`, then poll for `CANCELLED` (or `FAILED`).
  - A terminal execution returns `409`. An execution already in `CANCEL_REQUESTED` returns its current state.
  - After cancelling, running steps become `CANCELLED` and steps not yet started become `SKIPPED`.
- `POST /executions/{id}/retry` `{"idempotency_key"}`: only for a SINGLE execution in `FAILED` whose `retry.strategy` is not `NOT_RETRYABLE`. It reruns under the **same** `execution_id`, starting at `retry.from_sequence`. Otherwise it returns `409`. For MULTI, add a fixed operation instead.

### 4.4 Polling and events

- The gateway does not relay the executor's Redis event stream.
- Poll `GET /executions/{id}` every 2–5 s. Terminal states are `SUCCEEDED`, `FAILED` and `CANCELLED`. MULTI also stops being busy at `WAITING_FOR_OPERATION`.
- Or read new events: `GET /executions/{id}/events?after_sequence=<last seen event_sequence>&limit=200` (limit 1–500).
  - Results are in ascending `event_sequence`.
  - If `next_cursor` is set, call again with `cursor=<next_cursor>` (and no `after_sequence`).
  - Use events to wake up; decide on the state read.

| `event_type` | meaning |
| --- | --- |
| `execution.started` | Kernel ready, first run started. Sent once, never again on retry. `payload.runtime = {provider, profile, target_id, kernel_id}`. It may never come if the execution fails before the runtime is ready |
| `execution.operation_started` | An operation started |
| `execution.step_started`, `execution.step_completed` | A step attempt started or ended |
| `execution.step_handover_started`, `execution.step_handover_completed` | Another executor worker took over a running step |
| `execution.operation_completed` | An operation ended. `payload.status`; `payload.execution_status` (MULTI: `WAITING_FOR_OPERATION`) |
| `execution.completed` | The execution ended: **success, failure or cancel**. Read `payload.status` |

Ignore unknown `event_type`s; new ones may be added.

`kernel_id` (in `runtime` of executions, attempts and the started event) is the Jupyter kernel id. It is unrelated to your `X-Session-Id`, and it is `null` before the kernel exists and after cleanup.

### 4.5 Reading results (cheapest first)

1. `GET /executions/{id}` gives `state.status` and `failure` (`{type, message}` or null).
2. `GET /executions/{id}/result` gives every operation and step with `result.status`, `error_message` and `output_summary` (`output_count`, `has_image`, `has_error`, `mime_types`, …), plus an artifact summary. It is small and has no paging.
3. Raw output:
   - Use `GET /executions/{id}/notebook?view=SUMMARY&start_index=0&limit=20` to find cells.
   - Then use `view=FULL` for full code and `outputs[]`, or `GET /executions/{id}/notebook/cells/{index}` for one full cell.
   - Outputs use the Jupyter format (`stream`, `execute_result`, `display_data`, `error`). Images are base64 in `data["image/png"]`.
   - Cell index is notebook order and may differ from step `sequence`.
   - `page = {start_index, limit, total_count, has_more}`, and `limit` is 1–200.
4. Files:
   - `GET /executions/{id}/artifacts` lists the artifacts (limit 1–1000).
   - `GET /artifacts/{artifact_id}` returns one artifact's metadata.
   - `GET /artifacts/{artifact_id}/content` returns the bytes. `Content-Type` is the file's type, `Content-Disposition` carries the file name and `ETag` is the SHA-256.
   - The execution notebook (`type: NOTEBOOK`) exists from the start and can be fetched while the execution runs.
   - `status: AVAILABLE` does not mean the analysis succeeded.
5. Save your own text (for example a report) as an artifact of a **SUCCEEDED** execution:
   - Call `POST /executions/{id}/artifacts` with `{"idempotency_key", "type": "REPORT", "source": {"type": "INLINE", "content": "<utf-8 text>"}, "name"?, "description"?, "media_type"?, "append_to_notebook"?: true, "metadata"?}`. It returns `201`.
   - `type` may be `REPORT`, `NOTEBOOK`, `PLOT`, `METRIC`, `LOG` or `OTHER`.

Notebook freshness is in `GET /executions/{id}` → `workspace.notebook_projection.status` (`NOT_STARTED`, `PENDING`, `SUCCEEDED`, `FAILED`).

## 5. Errors and retries

All errors (from the gateway and from the executor) look like this:

```json
{"error": {"code": "EXECUTION_VERSION_CONFLICT", "message": "human text, may change",
           "details": [{"location": ["body", "expected_version"], "type": "version_conflict",
                        "message": "…", "context": {"expected": 3, "current": 4}}],
           "context": {}}}
```

`details` is always present (`[]` when empty). `details[].location[0]` is one of `body`, `header`, `query` or `path`. `details[].type` is a stable snake_case reason, and `details[].context` holds limits and actual values.

| HTTP | `error.code` | from | cause | what the client does |
| --- | --- | --- | --- | --- |
| 400 | `INVALID_IDENTITY` | gateway / executor | `X-User-Id` missing or malformed, bad `X-Project-Id`/`X-Session-Id`, session without project, bad `user_id` query | fix the request; do not retry |
| 401 | `LOGIN_REQUIRED` | gateway | no `X-Api-Key` | fix config |
| 401 | `INVALID_API_KEY` | gateway | unknown or revoked key | stop; report |
| 403 | `FORBIDDEN` | gateway | unknown or inactive user (our tenant), or a standard key with someone else's `user_id` | do not retry |
| 404 | `NOT_FOUND` | gateway | route not in the list, project not a member, foreign session | fix the path |
| 404 | `EXECUTION_NOT_FOUND`, `ARTIFACT_NOT_FOUND`, other `*_NOT_FOUND` | executor | missing, other tenant, or (standard key) other user | check the id |
| 409 | `EXECUTION_VERSION_CONFLICT` | executor | stale `expected_version` | GET the state; decide; send with the new version and a **new** idempotency key |
| 409 | `INVALID_STATE_TRANSITION` | executor | not allowed in this state (cancel a finished one, add while not waiting, finalize after a failed op, retry not allowed) | GET the state; decide |
| 409 | `IDEMPOTENCY_CONFLICT` | executor | same key, different body | bug: new work needs a new key |
| 413 | `TOO_LARGE` | gateway | body > 32 MB | shrink |
| 413 | `REQUEST_BODY_TOO_LARGE` | executor | body > 30 MB | shrink |
| 422 | `REQUEST_VALIDATION_ERROR` | executor | missing, typed wrong, length or pattern, unknown field | fix per `details` |
| 422 | `INVALID_EXECUTION_SPEC` | executor | rule violation; `details[].type` in the list below | fix per `details[].context` |
| 500 | `INTERNAL_ERROR` | executor | bug | report with `X-Request-ID` |
| 502 | `EXECUTOR_UNAVAILABLE` | gateway | executor unreachable | retry with backoff, same key and body |
| 503 | `DATABASE_UNAVAILABLE` | executor | transient DB loss | retry with backoff, same key and body |
| 504 | `EXECUTOR_TIMEOUT` | gateway | executor took > 30 s | retry with backoff, same key and body |

`INVALID_EXECUTION_SPEC` `details[].type` values:

| type | context |
| --- | --- |
| `too_many_steps` | `limit`, `actual` |
| `execution_step_limit_exceeded` | `limit`, `existing`, `requested`, `actual` |
| `inline_source_too_large` | `limit_bytes`, `actual_bytes`, `sequence` |
| `source_blank` | `sequence` |
| `steps_empty` | (none) |
| `sequence_not_contiguous`, `first_sequence_not_zero` | `expected`, `actual` |
| `unsupported_schema_version` | `expected`, `actual` |
| `exceeds_max_runtime` | `limit_seconds`, `actual_seconds` |
| `not_allowed_for_single`, `required_for_multi` | `actual` |
| `multi_requires_interactive` | `expected`, `actual` |
| `session_without_project`, `reserved_value` | `actual` |

Retry policy:

- Retry with exponential backoff (1 s, 2 s, 4 s, … up to 30 s, at most 5 tries) only on network errors, timeouts, `502`, `503` and `504`.
- Use the **same idempotency key and the same body**; you get the first result back.
- Never retry other 4xx unchanged.

## 6. Endpoints

All paths are under `/api/v1/executor`.

| # | Method | Path | Body | Success |
| --- | --- | --- | --- | --- |
| 1 | GET | `/executions?user_id=&project_id=&session_id=&trigger_type=&status=&cursor=&limit=` (limit 1–200, default 100) | – | 200 `ExecutionPageResponse` |
| 2 | POST | `/executions` | `ExecutionSubmitRequest` | 202 `ExecutionCommandResponse` + `Location` |
| 3 | GET | `/executions/{execution_id}` | – | 200 `ExecutionResponse` |
| 4 | GET | `/executions/{execution_id}/result` | – | 200 `ExecutionResultResponse` |
| 5 | GET | `/executions/{execution_id}/steps?cursor=&limit=` | – | 200 `ExecutionStepPageResponse` |
| 6 | GET | `/executions/{execution_id}/steps/{step_id}` | – | 200 `ExecutionStepResponse` |
| 7 | GET | `/executions/{execution_id}/operations?cursor=&limit=` | – | 200 `ExecutionOperationPageResponse` |
| 8 | POST | `/executions/{execution_id}/operations` | `ExecutionOperationCreateRequest` | 202 `ExecutionCommandResponse` |
| 9 | GET | `/executions/{execution_id}/operations/{operation_id}` | – | 200 `ExecutionOperationResponse` |
| 10 | GET | `/executions/{execution_id}/operations/{operation_id}/result` | – | 200 `ExecutionOperationResultResponse` |
| 11 | GET | `/executions/{execution_id}/operations/{operation_id}/steps?cursor=&limit=` | – | 200 `ExecutionStepPageResponse` |
| 12 | GET | `/executions/{execution_id}/events?after_sequence=&cursor=&limit=` | – | 200 `ExecutionEventPageResponse` |
| 13 | GET | `/executions/{execution_id}/artifacts?cursor=&limit=` | – | 200 `ExecutionArtifactPageResponse` |
| 14 | POST | `/executions/{execution_id}/artifacts` | `ExecutionArtifactMaterializeRequest` | 201 `ExecutionArtifactResponse` |
| 15 | GET | `/executions/{execution_id}/notebook?view=SUMMARY\|FULL&start_index=&limit=` | – | 200 `ExecutionNotebookResponse` |
| 16 | GET | `/executions/{execution_id}/notebook/cells/{cell_index}` | – | 200 `ExecutionNotebookCellResponse` |
| 17 | POST | `/executions/{execution_id}/finalize` | `ExecutionFinalizeRequest` | 202 `ExecutionCommandResponse` |
| 18 | POST | `/executions/{execution_id}/cancel` | `ExecutionCancelRequest` | 202 `ExecutionCommandResponse` |
| 19 | POST | `/executions/{execution_id}/retry` | `ExecutionRetryRequest` | 202 `ExecutionCommandResponse` |
| 20 | GET | `/artifacts/{artifact_id}` | – | 200 `ExecutionArtifactResponse` |
| 21 | GET | `/artifacts/{artifact_id}/content` | – | 200 file bytes |

Not available with a key (they return 404): attempts, diagnostics, runtime targets and pools, and maintenance. Those routes are for the service's administrators only.

States:

- `ExecutionStatus`: `QUEUED`, `RUNNING`, `WAITING_FOR_OPERATION`, `FINALIZING`, `CANCEL_REQUESTED`, and the terminal `SUCCEEDED`, `FAILED` and `CANCELLED`.
- Operation `result.status`: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`.
- Step `result.status`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`, `CANCELLED`.
- `failure.type`:
  - `TOOL_ERROR` means your code raised.
  - The timeout types are `STEP_TIMEOUT`, `OPERATION_TIMEOUT`, `OPERATION_WAIT_TIMEOUT`, `EXECUTION_TIMEOUT` and `QUEUE_TIMEOUT`.
  - `OUTPUT_LIMIT_EXCEEDED`.
  - The infrastructure types are `RUNTIME_UNAVAILABLE`, `RUNTIME_SESSION_LOST`, `INFRASTRUCTURE_ERROR`, `WORKER_SHUTDOWN`, `LEASE_EXPIRED` and `INTERNAL_ERROR`.
  - `COMPLETION_FAILED` means post-processing failed; it cannot be retried.

## 7. Reference client (Python, httpx)

```python
"""Executor gateway client. Config: AGENTIC_BASE_URL, AGENTIC_API_KEY."""

import os
import time
import uuid
from typing import Any

import httpx

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
RETRYABLE_STATUS = {502, 503, 504}


class GatewayError(Exception):
    def __init__(self, status: int, body: dict[str, Any]):
        error = body.get("error", {}) if isinstance(body, dict) else {}
        self.status = status
        self.code = error.get("code", "UNKNOWN")
        self.details = error.get("details", [])
        self.context = error.get("context")
        super().__init__(f"{status} {self.code}: {error.get('message', '')}")


class ExecutorGateway:
    def __init__(self, user_id: str, *, project_id: str | None = None,
                 session_id: str | None = None):
        self.http = httpx.Client(
            base_url=os.environ["AGENTIC_BASE_URL"].rstrip("/") + "/api/v1/executor",
            timeout=httpx.Timeout(40.0, connect=5.0),  # gateway waits 30 s upstream
        )
        self.headers = {"X-Api-Key": os.environ["AGENTIC_API_KEY"],
                        "X-User-Id": user_id.lower()}
        if project_id:
            self.headers["X-Project-Id"] = project_id
            if session_id:
                self.headers["X-Session-Id"] = session_id

    # transport: retries only network errors and 502/503/504, same body
    def _call(self, method: str, path: str, *, json: Any = None,
              params: dict[str, Any] | None = None, raw: bool = False) -> Any:
        delay = 1.0
        for attempt in range(5):
            try:
                r = self.http.request(method, path, json=json, params=params,
                                      headers=self.headers)
            except httpx.TransportError:
                if attempt == 4:
                    raise
            else:
                if r.status_code < 400:
                    return r if raw else (r.json() if r.content else None)
                if r.status_code not in RETRYABLE_STATUS or attempt == 4:
                    try:
                        body = r.json()
                    except ValueError:
                        body = {}
                    raise GatewayError(r.status_code, body)
            time.sleep(delay)
            delay = min(delay * 2, 30)

    # commands (idempotency key made once per logical write)
    def submit(self, codes: list[str], *, mode: str = "SINGLE",
               wait_seconds: int | None = None, profile: str = "default",
               step_timeout: int | None = 300, metadata: dict | None = None) -> dict:
        lifecycle: dict[str, Any] = {"operation_mode": mode}
        if mode == "MULTI":
            lifecycle["operation_wait_timeout_seconds"] = wait_seconds or 600
        body = {
            "idempotency_key": str(uuid.uuid4()),
            "lifecycle": lifecycle,
            "trigger": {"type": "INTERACTIVE"},
            "runtime": {"type": "JUPYTER", "profile": profile},
            "operation": {"spec": self._spec(codes, start=0, timeout=step_timeout)},
            "metadata": metadata or {},
        }
        return self._call("POST", "/executions", json=body)

    def add_operation(self, execution_id: str, codes: list[str], *,
                      start: int, expected_version: int) -> dict:
        body = {"idempotency_key": str(uuid.uuid4()),
                "expected_version": expected_version,
                "spec": self._spec(codes, start=start, timeout=300)}
        return self._call("POST", f"/executions/{execution_id}/operations", json=body)

    def finalize(self, execution_id: str, expected_version: int) -> dict:
        return self._call("POST", f"/executions/{execution_id}/finalize",
                          json={"idempotency_key": str(uuid.uuid4()),
                                "expected_version": expected_version})

    def cancel(self, execution_id: str, reason: str | None = None) -> dict:
        body: dict[str, Any] = {"idempotency_key": str(uuid.uuid4())}
        if reason:
            body["reason"] = reason
        return self._call("POST", f"/executions/{execution_id}/cancel", json=body)

    def retry(self, execution_id: str) -> dict:
        return self._call("POST", f"/executions/{execution_id}/retry",
                          json={"idempotency_key": str(uuid.uuid4())})

    # reads
    def get(self, execution_id: str) -> dict:
        return self._call("GET", f"/executions/{execution_id}")

    def wait(self, execution_id: str, *, until: set[str] = TERMINAL,
             interval: float = 3.0, timeout: float = 3600) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            execution = self.get(execution_id)
            if execution["state"]["status"] in until:
                return execution
            if time.monotonic() > deadline:
                raise TimeoutError(execution_id)
            time.sleep(interval)

    def result(self, execution_id: str) -> dict:
        return self._call("GET", f"/executions/{execution_id}/result")

    def notebook(self, execution_id: str, *, full: bool = False) -> list[dict]:
        cells, start = [], 0
        while True:
            page = self._call("GET", f"/executions/{execution_id}/notebook",
                              params={"view": "FULL" if full else "SUMMARY",
                                      "start_index": start, "limit": 200})
            cells += page["cells"]
            if not page["page"]["has_more"]:
                return cells
            start = page["page"]["start_index"] + len(page["cells"])

    def artifacts(self, execution_id: str) -> list[dict]:
        items, cursor = [], None
        while True:
            params = {"limit": 1000, **({"cursor": cursor} if cursor else {})}
            page = self._call("GET", f"/executions/{execution_id}/artifacts", params=params)
            items += page["items"]
            cursor = page.get("next_cursor")
            if not cursor:
                return items

    def download(self, artifact_id: str) -> bytes:
        return self._call("GET", f"/artifacts/{artifact_id}/content", raw=True).content

    @staticmethod
    def _spec(codes: list[str], *, start: int, timeout: int | None) -> dict:
        steps = []
        for i, code in enumerate(codes):
            step: dict[str, Any] = {
                "sequence": start + i,
                "payload": {"type": "PYTHON_EXECUTE",
                            "source": {"type": "INLINE", "content": code}},
            }
            if timeout:
                step["step_timeout_seconds"] = timeout
            steps.append(step)
        return {"schema_version": "1.0", "steps": steps}
```

The idempotency key is made inside each command method. A retry inside `_call` reuses the same `json` object, so the key and body stay the same. If you add retries outside `_call` (for example a job queue), make the key once per job and pass it in instead.

Usage:

```python
gw = ExecutorGateway("e12345", project_id="project-100")

# SINGLE
sub = gw.submit(["import pandas as pd", "print(pd.DataFrame({'a': [1, 2]}).sum())"])
done = gw.wait(sub["execution_id"])
if done["state"]["status"] != "SUCCEEDED":
    print(done["failure"])                       # {"type": "TOOL_ERROR", "message": ...}
for op in gw.result(sub["execution_id"])["operations"]:
    for step in op["steps"]:
        print(step["sequence"], step["result"]["status"], step["result"]["error_message"])
cells = gw.notebook(sub["execution_id"], full=True)   # raw outputs in cells[i]["outputs"]

# MULTI
sub = gw.submit(["df = 1 + 1"], mode="MULTI", wait_seconds=600)
eid = sub["execution_id"]
state = gw.wait(eid, until={"WAITING_FOR_OPERATION", *TERMINAL})
if state["state"]["status"] == "WAITING_FOR_OPERATION":
    try:
        gw.add_operation(eid, ["print(df)"], start=1, expected_version=state["state"]["version"])
    except GatewayError as e:
        if e.code != "EXECUTION_VERSION_CONFLICT":
            raise
        # re-read and decide
    state = gw.wait(eid, until={"WAITING_FOR_OPERATION", *TERMINAL})
    if state["state"]["status"] == "WAITING_FOR_OPERATION":
        gw.finalize(eid, state["state"]["version"])
gw.wait(eid)

# files
for a in gw.artifacts(eid):
    if a["type"] == "NOTEBOOK":
        open("execution.ipynb", "wb").write(gw.download(a["artifact_id"]))
```

## 8. Checklist (common mistakes)

- [ ] `X-User-Id` on every request, reads too.
- [ ] `idempotency_key` in the body, made once per logical write, reused on retry with the same body.
- [ ] No `actor`, `context`, `tenant_id` in bodies. No `X-Tenant-Id`.
- [ ] Step `sequence` continues across operations (MULTI). It does not restart at 0.
- [ ] MULTI: `trigger.type = INTERACTIVE`, `operation_wait_timeout_seconds ≥ 30`. SINGLE: no `operation_wait_timeout_seconds`.
- [ ] `expected_version` comes from the latest read. A `409` conflict means re-read, not blind resend.
- [ ] `execution.completed` / `FAILED` / `CANCELLED` are all "done". Check `state.status` and `failure`.
- [ ] Output comes from `/notebook`, files from `/artifacts/{id}/content`. Never from `result_ref`.
- [ ] Follow `Location` only after rewriting `/api/v1/` → `/api/v1/executor/`.
- [ ] Standard key: no `user_id` filter, or exactly your `X-User-Id`.
- [ ] Ignore unknown response fields and unknown `event_type`s.
- [ ] Do not ask for `Range`; downloads are whole.

## 9. Types

Generated from the executor OpenAPI (`scripts/gateway_docs.py`). Do not edit by hand. Interfaces marked `unknown fields → 422` are request bodies; response types may gain fields, so ignore unknown ones. `string` timestamps are ISO 8601 with time zone, and ids are UUID strings.

<!-- gen:begin types -->
```ts
interface ArtifactLineage {
  parent_artifact_id: string | null;
  external_parent_asset_id: string | null;
}
interface ArtifactProducer {
  execution_id: string;
  execution_attempt_id: string | null;
  execution_step_id: string | null;
  execution_step_attempt_id: string | null;
}
type ArtifactStatus = "AVAILABLE" | "INCOMPLETE" | "DELETED";
interface ArtifactStorage {
  type: ArtifactStorageType;
  uri: string;
  relative_path: string | null;
  media_type: string | null;
  size_bytes: number | null;
  checksum_sha256: string | null;
}
interface ArtifactStorageSummary {
  type: ArtifactStorageType;
  media_type: string | null;
  size_bytes: number | null;
}
type ArtifactStorageType = "PV" | "S3";
type ArtifactType = "DATASET" | "NOTEBOOK" | "REPORT" | "PLOT" | "MODEL" | "METRIC" | "LOG" | "OTHER";
interface AttemptState {
  status: AttemptStatus;
}
type AttemptStatus = "RUNNING" | "WAITING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
type CodeSourceType = "INLINE" | "PATH";
interface DeadlinesResponse {
  operation_wait_expires_at: string | null;
  execution_expires_at: string | null;
}
interface EventDelivery {
  status: OutboxStatus;
  attempt_count: number;
  available_at: string;
  published_at: string | null;
  last_error: string | null;
}
interface ExecutionArtifactMaterializeRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  type: "NOTEBOOK" | "REPORT" | "PLOT" | "METRIC" | "LOG" | "OTHER";
  source: InlineArtifactSource | PathArtifactSource;
  name?: string | null; // 길이 ≥ 1, 길이 ≤ 255
  description?: string | null; // 길이 ≤ 4000
  media_type?: string | null; // 길이 ≥ 1, 길이 ≤ 255
  append_to_notebook?: boolean; // default false
  metadata?: Record<string, unknown>;
}
interface ExecutionArtifactPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionArtifactSummaryResponse[];
}
interface ExecutionArtifactResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  artifact_id: string;
  name: string;
  description: string | null;
  type: ArtifactType;
  status: ArtifactStatus;
  produced_by: ArtifactProducer;
  lineage: ArtifactLineage;
  storage: ArtifactStorage;
  metadata: Record<string, unknown>;
}
interface ExecutionArtifactSummaryResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  artifact_id: string;
  name: string;
  type: ArtifactType;
  status: ArtifactStatus;
  produced_by: ArtifactProducer;
  storage: ArtifactStorageSummary;
}
interface ExecutionAttemptResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  attempt_id: string;
  execution_id: string;
  attempt_number: number;
  state: AttemptState;
  failure: FailureResponse | null;
  lifecycle: Lifecycle;
  step_count: number;
}
interface ExecutionCancelRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  reason?: string | null; // 길이 ≤ 2000
}
interface ExecutionCommandResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  execution_id: string;
  operation: ExecutionOperationReceipt | null;
  state: ExecutionCommandState;
}
interface ExecutionCommandState {
  status: ExecutionStatus;
  version: number;
}
interface ExecutionContext {
  user_id: string;
  project_id: string | null;
  session_id: string | null;
}
interface ExecutionEventPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionEventResponse[];
}
interface ExecutionEventResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  event_id: string;
  execution_id: string;
  event_sequence: number;
  schema_version: string;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  delivery: EventDelivery | null;
}
interface ExecutionFinalizeRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  expected_version: number; // ≥ 0
}
interface ExecutionLifecycleInput { // unknown fields → 422
  operation_mode: OperationMode;
  operation_wait_timeout_seconds?: number | null; // ≥ 30
}
interface ExecutionLifecycleResponse {
  operation_mode: OperationMode;
  operation_wait_timeout_seconds: number | null;
  started_at: string | null;
  finished_at: string | null;
}
interface ExecutionNotebookCellResponse {
  execution_id: string;
  cell: NotebookCellResponse;
}
interface ExecutionNotebookResponse {
  execution_id: string;
  view: "SUMMARY" | "FULL";
  metadata: Record<string, unknown>;
  cells: (NotebookCellSummaryResponse | NotebookCellResponse)[];
  page: NotebookPage;
}
interface ExecutionOperationCreateRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  expected_version: number; // ≥ 0
  operation_timeout_seconds?: number | null; // ≥ 1
  spec: ExecutionSpec;
  metadata?: Record<string, unknown>;
}
interface ExecutionOperationInput { // unknown fields → 422
  operation_timeout_seconds?: number | null; // ≥ 1
  spec: ExecutionSpec;
  metadata?: Record<string, unknown>;
}
interface ExecutionOperationPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionOperationSummaryResponse[];
}
interface ExecutionOperationReceipt {
  operation_id: string;
  steps: ExecutionStepReceipt[];
}
interface ExecutionOperationResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  operation_id: string;
  execution_id: string;
  operation_number: number;
  schema_version: string;
  sequence_range: OperationSequenceRange;
  operation_timeout_seconds: number | null;
  metadata: Record<string, unknown>;
  execution_attempt_id: string | null;
  result: OperationResult;
  lifecycle: Lifecycle;
  step_count: number;
}
interface ExecutionOperationResultResponse {
  execution: ExecutionResultExecutionResponse;
  operation: ExecutionResultOperationResponse;
}
interface ExecutionOperationSummaryResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  operation_id: string;
  operation_number: number;
  sequence_range: OperationSequenceRange;
  result: OperationResult;
  lifecycle: Lifecycle;
  step_count: number;
}
interface ExecutionPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionSummaryResponse[];
}
interface ExecutionResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  execution_id: string;
  trigger_type: TriggerType;
  trigger: ExecutionTrigger;
  tenant_id: string;
  context: ExecutionContext;
  metadata: Record<string, unknown>;
  runtime: ExecutionRuntime;
  state: ExecutionState;
  workspace: WorkspaceResponse;
  failure: FailureResponse | null;
  retry: RetryResponse;
  recovery: RecoveryResponse;
  deadlines: DeadlinesResponse;
  lifecycle: ExecutionLifecycleResponse;
}
interface ExecutionResultExecutionResponse {
  execution_id: string;
  state: ExecutionCommandState;
}
interface ExecutionResultOperationResponse {
  operation_id: string;
  operation_number: number;
  sequence_range: OperationSequenceRange;
  result: OperationResult;
  lifecycle: Lifecycle;
  steps: ExecutionResultStepResponse[];
}
interface ExecutionResultResponse {
  execution: ExecutionResultExecutionResponse;
  operations: ExecutionResultOperationResponse[];
  attempts: ExecutionAttemptResponse[];
  artifacts: ExecutionArtifactSummaryResponse[];
}
interface ExecutionResultStepResponse {
  step_id: string;
  sequence: number;
  lineage: ToolReference;
  result: StepResult;
  lifecycle: Lifecycle;
}
interface ExecutionRetryRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
}
interface ExecutionRuntime {
  type: RuntimeType;
  pool: RuntimePool;
  profile: string;
  target_id: string | null;
  kernel_id: string | null;
}
interface ExecutionRuntimeInput { // unknown fields → 422
  type: RuntimeType;
  profile: string; // 길이 ≥ 1, 길이 ≤ 128
}
interface ExecutionSpec { // unknown fields → 422
  schema_version: "1.0";
  steps: ExecutionStepInput[]; // 항목 ≥ 1
}
interface ExecutionState {
  status: ExecutionStatus;
  version: number;
  cancellation_reason: string | null;
  finalized_by?: FinalizedBy | null;
}
type ExecutionStatus = "QUEUED" | "RUNNING" | "WAITING_FOR_OPERATION" | "FINALIZING" | "CANCEL_REQUESTED" | "CANCELLED" | "SUCCEEDED" | "FAILED";
interface ExecutionStepInput { // unknown fields → 422
  sequence: number; // ≥ 0
  payload: PythonExecutePayload;
  step_timeout_seconds?: number | null; // ≥ 1
  lineage?: StepLineage | null;
}
interface ExecutionStepPageResponse {
  next_cursor: string | null;
  has_more: boolean;
  items: ExecutionStepSummaryResponse[];
}
interface ExecutionStepReceipt {
  sequence: number;
  step_id: string;
}
interface ExecutionStepResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  step_id: string;
  execution_id: string;
  sequence: number;
  code_hash: string | null;
  source: StepSourceResponse;
  step_timeout_seconds: number | null;
  lineage: ToolReference;
  result: StepResult;
  lifecycle: Lifecycle;
}
interface ExecutionStepSummaryResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  step_id: string;
  execution_id: string;
  sequence: number;
  lineage: ToolReference;
  result: StepResultSummary;
  lifecycle: Lifecycle;
}
interface ExecutionSubmitRequest { // unknown fields → 422
  idempotency_key: string; // 길이 ≥ 1, 길이 ≤ 255
  lifecycle: ExecutionLifecycleInput;
  trigger: ExecutionTriggerInput;
  runtime: ExecutionRuntimeInput;
  operation: ExecutionOperationInput;
  metadata?: Record<string, unknown>;
}
interface ExecutionSummaryResponse {
  created_by_client: string | null;
  created_by: string | null;
  updated_by_client: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  execution_id: string;
  operation_mode: OperationMode;
  trigger_type: TriggerType;
  trigger: ExecutionTrigger;
  tenant_id: string;
  context: ExecutionContext;
  metadata: Record<string, unknown>;
  state: ExecutionCommandState;
  lifecycle: Lifecycle;
  step_count: number;
}
interface ExecutionTrigger {
  type: TriggerType;
}
interface ExecutionTriggerInput { // unknown fields → 422
  type: TriggerType;
}
interface FailureResponse {
  type: FailureType;
  message: string;
}
type FailureType = "TOOL_ERROR" | "INFRASTRUCTURE_ERROR" | "WORKER_SHUTDOWN" | "RUNTIME_UNAVAILABLE" | "LEASE_EXPIRED" | "INTERNAL_ERROR" | "OPERATION_WAIT_TIMEOUT" | "OPERATION_TIMEOUT" | "STEP_TIMEOUT" | "EXECUTION_TIMEOUT" | "QUEUE_TIMEOUT" | "OUTPUT_LIMIT_EXCEEDED" | "RUNTIME_SESSION_LOST" | "COMPLETION_FAILED";
type FinalizedBy = "AGENT" | "WAIT_TIMEOUT" | "MAX_RUNTIME";
interface InlineArtifactSource { // unknown fields → 422
  type: "INLINE";
  content: string; // 길이 ≥ 1
}
interface InlineStepSource { // unknown fields → 422
  type: "INLINE";
  content: string; // 길이 ≥ 1
}
interface Lifecycle {
  started_at: string | null;
  finished_at: string | null;
}
interface NotebookCellResponse {
  index: number;
  id: string | null;
  type: string;
  execution_count: number | null;
  source: string;
  line_count: number;
  metadata: Record<string, unknown>;
  output_summary: OutputSummary;
  outputs: Record<string, unknown>[];
}
interface NotebookCellSummaryResponse {
  index: number;
  id: string | null;
  type: string;
  execution_count: number | null;
  source_preview: string;
  source_truncated: boolean;
  line_count: number;
  metadata: Record<string, unknown>;
  output_summary: OutputSummary;
}
interface NotebookPage {
  start_index: number;
  limit: number;
  total_count: number;
  has_more: boolean;
}
interface NotebookProjectionResponse {
  status: NotebookProjectionStatus;
  attempt_count: number;
  error_message: string | null;
  projected_at: string | null;
}
type NotebookProjectionStatus = "NOT_STARTED" | "PENDING" | "SUCCEEDED" | "FAILED";
type OperationMode = "SINGLE" | "MULTI";
interface OperationResult {
  status: OperationStatus;
  error_message: string | null;
}
interface OperationSequenceRange {
  first: number;
  last: number;
}
type OperationStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
type OutboxStatus = "PENDING" | "PUBLISHED";
interface OutputSummary {
  output_count: number; // ≥ 0
  output_types: Record<string, unknown>;
  stream_names: string[];
  mime_types: string[];
  has_image: boolean;
  image_count: number; // ≥ 0
  has_error: boolean;
}
interface PathArtifactSource { // unknown fields → 422
  type: "PATH";
  path: string; // 길이 ≥ 1, 길이 ≤ 4096
  sha256: string; // `^[0-9a-fA-F]{64}$`
}
interface PathStepSource { // unknown fields → 422
  type: "PATH";
  path: string; // 길이 ≥ 1, 길이 ≤ 4096
  sha256: string; // `^[0-9a-fA-F]{64}$`
}
interface PythonExecutePayload { // unknown fields → 422
  type: "PYTHON_EXECUTE";
  source: InlineStepSource | PathStepSource;
}
interface RecoveryResponse {
  count: number;
  runtime_session_cleanup_status: RuntimeSessionCleanupStatus;
  runtime_abort_status: RuntimeAbortStatus;
}
interface RetryResponse {
  strategy: RetryStrategy;
  count: number;
  from_sequence: number | null;
  retained_runtime_session_until: string | null;
}
type RetryStrategy = "NOT_RETRYABLE" | "FROM_FAILED_STEP" | "FROM_START";
type RuntimeAbortStatus = "NOT_REQUIRED" | "PENDING" | "IDLE_CONFIRMED" | "SESSION_DELETED" | "SESSION_MISSING" | "FAILED";
type RuntimePool = "INTERACTIVE" | "BATCH";
type RuntimeSessionCleanupStatus = "NOT_REQUIRED" | "PENDING" | "SUCCEEDED" | "FAILED";
type RuntimeType = "JUPYTER";
interface StepLineage { // unknown fields → 422
  skill_name?: string | null; // 길이 ≤ 255
  tool_name?: string | null; // 길이 ≤ 255
  input_parameters?: Record<string, unknown>;
}
interface StepResult {
  status: StepStatus;
  output_summary: OutputSummary;
  error_message: string | null;
  result_ref: StepResultReference | null;
}
interface StepResultReference {
  storage?: "SHARED_PV"; // default "SHARED_PV"
  execution_id: string;
  step_id: string;
  attempt_id: string;
  fencing_token: number;
  relative_path: string;
  checksum_sha256: string;
  size_bytes: number;
  complete: boolean;
  representation_count: number;
  total_size_bytes: number;
}
interface StepResultSummary {
  status: StepStatus;
  output_summary: OutputSummary;
  error_message: string | null;
}
interface StepSourceResponse {
  type: CodeSourceType;
  path: string | null;
  sha256: string;
}
type StepStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED" | "CANCELLED";
interface ToolReference {
  skill_name: string | null;
  tool_name: string | null;
  input_parameters: Record<string, unknown>;
}
type TriggerType = "INTERACTIVE" | "BATCH";
interface WorkspaceResponse {
  path: string | null;
  notebook_path: string | null;
  notebook_projection: NotebookProjectionResponse;
}
```
<!-- gen:end types -->

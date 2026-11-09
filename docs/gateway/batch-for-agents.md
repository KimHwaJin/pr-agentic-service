# Batch gateway: guide for coding agents

You are writing a client that uploads Jupyter notebooks and runs them on a schedule (or on demand) through the **batch gateway** of pr-agentic-service. This one file is enough to write that client. Read the rules first. Use the TypeScript types at the end (and `openapi/batch-gateway.openapi.json`) as the exact field contract.

- Base paths:
  - `{BASE_URL}/api/v1/batch` relays to pr-batch (scripts, batches, runs, runtimes).
  - `{BASE_URL}/api/v1/batch-reports` and `{BASE_URL}/api/v1/batch/scripts/from-notebook` are pr-agentic-service's own batch routes.
- `BASE_URL` is the deployed service (Kubernetes): the environment's public origin `https://<api-host>` from outside the cluster, or `http://pr-agentic-service.<namespace>.svc.cluster.local` from inside it. Read it from config (`AGENTIC_BASE_URL`); never hard-code it.
- Any route not listed in section 6 returns `404 NOT_FOUND`.
- Request and success response bodies are pr-batch's own. The gateway checks the key and user, sets the identity headers itself, and decides the read scope.
- pr-batch stores notebooks, schedules and tracks runs. The code itself runs on the executor. Run results (the executed notebook) are downloaded from the **executor gateway** with the same key (section 4.4).

## 1. Rules

### MUST

1. Send `X-Api-Key: <key>` on every request. Read it from config or an env var (e.g. `AGENTIC_API_KEY`). Never hard-code it or log it.
2. Send `X-User-Id: <employee id>` on **every** request, reads included. Use lower case, matching `^[a-z0-9][a-z0-9._-]{0,63}$`. If it is missing or malformed, you get `400 INVALID_IDENTITY`. Every script, batch and run belongs to (tenant of the key, this user).
3. Send an `Idempotency-Key` **header** on every POST, PATCH and DELETE to `/api/v1/batch/…` (1–255 chars, ASCII, no spaces; use a UUID).
   - Make it once per logical write, before the first try.
   - Reuse it with the same body on retries.
   - Exception: `scripts/from-notebook` and `/batch-reports/…/retry` do not need one.
4. Send `If-Match: <ETag>` on rename or delete of a script, and on update, delete, enable or disable of a batch.
   - Take the ETag from the detail GET or the last write response.
   - Send it **with its quotes**, e.g. `If-Match: "3"`.
5. Take `runtime` for a batch verbatim from an item of `GET /api/v1/batch/runtimes`.
6. Treat a new batch as **disabled**. Call `enable` to start its schedule.
7. Poll runs at most every 5 seconds. Stop at `COMPLETED`, `FAILED`, `CANCELLED` or `SKIPPED`.
8. Branch on `error.code`, never on `error.message`.
9. Pass `next_cursor` back as `cursor` unchanged. Stop when `next_cursor` is `null`.

### MUST NOT

1. Do not send unknown fields. JSON bodies reject them with `422 VALIDATION_ERROR`. Do not send `tenant_id`, `user_id`, `owner_id` or `actor` in a body; the owner is always `X-User-Id`.
2. Do not send `X-Tenant-Id`. It is ignored, because the key fixes the tenant.
3. Do not call pr-batch or the executor directly. Only these gateways.
4. Do not reuse an `Idempotency-Key` for a different body (`409 IDEMPOTENCY_CONFLICT`). Do not reuse one after a `409 REVISION_CONFLICT`: fetch the new ETag and use a **new** key.
5. Do not strip the quotes from the ETag (`422 INVALID_REVISION`).
6. Do not resend an unchanged `schedule` in a PATCH. Resending restarts interval schedules from now. Leave the field out.
7. Do not send policy fields that the chosen `mode` does not use (422).

## 2. Headers

| Header | When | Value |
| --- | --- | --- |
| `X-Api-Key` | always | the issued key |
| `X-User-Id` | always | acting user. The owner of what you create |
| `Idempotency-Key` | POST, PATCH, DELETE under `/api/v1/batch/` | UUID per logical write. pr-batch keeps it 7 days |
| `If-Match` | rename/delete script; update/delete/enable/disable batch | the ETag, quotes included |
| `X-Project-Id` | optional, `POST /batches` only | stored on the batch, never changes. For the agentic service's own tenant it must be a project the user is a member of |
| `Content-Type` | JSON bodies | `application/json`. Uploads use `multipart/form-data` |
| `Accept` | optional | passed on |

`X-Session-Id` is not forwarded.

Response headers: `ETag` (detail and write responses), `Location` (creates), `Content-Type`, `X-Request-ID`. `Location` is pr-batch's own path (`/api/v1/batches/{id}`). Rewrite `/api/v1/` → `/api/v1/batch/` before following it. `Content-Disposition` is **not** passed on, so name downloaded files yourself.

## 3. Read scope: standard key vs master key

| | standard key | master key |
| --- | --- | --- |
| `GET /scripts`, `GET /batches` | only the `X-User-Id` user's | the whole tenant |
| query `user_id` | optional; must equal `X-User-Id`, else `403 FORBIDDEN` | narrows the list to that user |
| detail routes | someone else's → `404` | any in the tenant |
| writes | as `X-User-Id` | as `X-User-Id` |

A malformed `user_id` returns `400 INVALID_IDENTITY`. Every Script, Version, Batch and Run carries `user_id` (owner; not on versions), `created_by`/`updated_by` (the `X-User-Id` that made the change) and `created_by_client`/`updated_by_client` (the calling key's name, `pr-agentic-service` through this gateway). Both are `null` for changes no user made, such as scheduled runs and status updates. `GET /runtimes` is the same list for everyone, though `X-User-Id` is still required.

## 4. Flows

### 4.1 Upload, register, try once, enable

```
GET   /api/v1/batch/runtimes                        → {"items":[{"type":"JUPYTER","profile":"default"}, …]}
POST  /api/v1/batch/scripts          multipart       → 201 ScriptView (latest_version.version_number = 1)
POST  /api/v1/batch/batches          CreateBatch     → 201 BatchView (enabled: false), ETag "1"
POST  /api/v1/batch/batches/{id}/runs                → 202 RunView (status WAITING/QUEUED)
GET   /api/v1/batch/batches/{id}/runs/{run_id}       → poll ≥ 5 s until terminal
GET   /api/v1/batch/batches/{id}                     → ETag, can_enable, enable_blocked_reason
POST  /api/v1/batch/batches/{id}/enable   If-Match   → 200 BatchView (enabled: true, next_run_at)
```

Upload (multipart form fields):

- `file`: the `.ipynb` (nbformat v4).
- `type`: `NOTEBOOK`.
- `name`: optional.

Uploading identical bytes again does not create a new version.

Notebook limits:

| rule | default | error |
| --- | --- | --- |
| file is `.ipynb`, nbformat v4 JSON | n/a | 422 `INVALID_NOTEBOOK` |
| file size | 10 MiB | 413 `UPLOAD_TOO_LARGE` / `REQUEST_TOO_LARGE` |
| all cells (markdown included) | 1000 | 422 `TOO_MANY_CELLS` |
| non-empty code cells (each is one executor step) | 100 | 422 `TOO_MANY_CELLS` |
| one code cell | 1 MiB | 422 `CELL_TOO_LARGE` |
| at least one code cell | n/a | 422 `EMPTY_NOTEBOOK` |
| kernel language, if stated, is Python | n/a | 422 `UNSUPPORTED_LANGUAGE` |

CreateBatch:

```jsonc
{
  "name": "Weekdays 08:00 line report",          // required, 1–255, no control chars
  "script_id": "<uuid>",                          // required
  "script_version_number": 2,                     // optional; omitted = latest at create time
  "runtime": {"type": "JUPYTER", "profile": "default"},   // required; from GET /runtimes
  "schedule": {                                   // optional; omitted = manual runs only (cannot enable)
    "definition": {"kind": "CRON", "expression": "0 8 * * MON-FRI"},
    "timezone": "Asia/Seoul",                     // optional; the only allowed value
    "start_at": null, "end_at": null              // optional, ISO 8601 with offset; start inclusive, end exclusive
  },
  "policy": {                                     // optional; default overlap SKIP, misfire SKIP
    "overlap": {"mode": "QUEUE", "max_queued": 100},
    "misfire": {"mode": "LATEST", "grace_seconds": 300}
  }
}
```

Schedule `definition` (pick one `kind`):

```jsonc
{"kind": "ONCE", "at": "2026-12-01T09:00:00+09:00"}
{"kind": "INTERVAL", "seconds": 1800, "anchor": null}                 // 60–31536000
{"kind": "CALENDAR", "frequency": "DAILY", "at": "08:00:00"}           // Seoul local time, no offset
{"kind": "CALENDAR", "frequency": "WEEKLY", "at": "08:00:00", "weekdays": ["MON", "FRI"]}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "month_days": [1, 15]}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "last_day": true}
{"kind": "CALENDAR", "frequency": "MONTHLY", "at": "09:00:00", "nth_weekdays": [{"weekday": "MON", "nth": 1}]}  // nth 1–5 or -1
{"kind": "CRON", "expression": "*/10 9-17 * * MON-FRI"}               // 5 fields or @hourly etc.; no seconds, no L/W/#
```

Policy (send only the fields of the chosen mode):

| part | mode | fields (default, range) |
| --- | --- | --- |
| `overlap` (previous run not finished) | `SKIP` | (none) |
| | `QUEUE` | `max_queued` (100, 1–10000) |
| | `PARALLEL` | `max_concurrent` (required, 1–100), `max_queued` (100) |
| | `REPLACE` | (none); cancels the running run and starts the new one |
| `misfire` (scheduled time missed) | `SKIP` | `grace_seconds` (300, 1–86400) |
| | `LATEST` | `grace_seconds` |
| | `CATCH_UP` | `grace_seconds`, `max_runs` (10, 1–1000), `max_age_seconds` (86400, 60–31536000) |

### 4.2 Enable and disable

- Before enabling, read `can_enable` and `enable_blocked_reason` from BatchView. Possible errors on enable:
  - `409 SCHEDULE_REQUIRED`
  - `422 NO_FUTURE_OCCURRENCE`, `UNKNOWN_RUNTIME`, `RUNTIME_NOT_SUPPORTED`
  - `503 EXECUTOR_NOT_CONFIGURED`, `RUNTIMES_NOT_CONFIGURED`
- Enabling an enabled batch or disabling a disabled one is `200` with no change.
- Enabling starts counting from now. Missed windows while disabled are not back-filled.
- `disabled_reason` is one of:
  - `OWNER`: you disabled it.
  - `USER_DEACTIVATED`: the owner was deactivated. Manual runs then return `409 OWNER_DEACTIVATED`.
  - `TENANT_REVOKED`: the tenant's keys were revoked. Manual runs then return `409 TENANT_REVOKED`.
- Manual runs work on disabled batches and on batches without a schedule, except in the two cases above.

### 4.3 Update (PATCH)

- Send only the fields you change. `{}` is a 422.
- `name`, `script_id`, `runtime` and `policy` cannot be `null`.
- `script_version_number: null` re-pins the batch to the latest version.
- `schedule: null` removes the schedule. On an enabled batch that is a `409 SCHEDULE_REQUIRED`.
- `policy` merges per part. Changing a part's `mode` resets that part to the new mode's defaults.
- A new script version does not change existing batches. PATCH `script_version_number` to move a batch to it.

### 4.4 Runs and their results

Run states:

```
WAITING → QUEUED → RUNNING → COLLECTING → COMPLETED | FAILED
WAITING / QUEUED / RUNNING → CANCELLED        (cancel only from these)
SKIPPED                                       (policy decided not to run; terminal at creation)
```

- `POST /batches/{id}/runs` takes no body (or `{}`) and returns `202 RunView`.
- If the manual run hits the concurrency limit, the gateway answers `409` with `{"error": {"code": "CONFLICT", "message": "pr-batch refused the request.", "details": [], "context": <RunView>}}`. In that `context`, `status` is `"SKIPPED"` and `skip_reason` is `"SKIPPED_CAPACITY"`. Try again after the running run ends.
- Cancel a run with `POST /batches/{id}/runs/{run_id}/cancel` and an `Idempotency-Key`.
  - For a QUEUED or RUNNING run, the reply is `202` with `cancel_requested: true` and the **same** status. Poll until `CANCELLED`.
  - A terminal run returns `409 NOT_CANCELLABLE`.
- Read `notebook_status` only after the run is terminal.
- Result notebook: when the run is `COMPLETED`, download `result.notebook_artifact_id` from the executor gateway with `GET /api/v1/executor/artifacts/{notebook_artifact_id}/content`, using the same key and the same `X-User-Id`.
- Execution details are at `GET /api/v1/executor/executions/{execution_id}`. See `executor-for-agents.md` for the notebook and cell routes.
- RunView fields you need: `id`, `batch_id`, `user_id` (owner), `status`, `skip_reason`, `failure_type`, `cancel_requested`, `trigger` (`MANUAL` or `SCHEDULED`), `scheduled_for`, `execution_id`, `notebook_status`, `result.notebook_artifact_id`, `last_error` and `completed_at`.
- RunDetail adds `steps[]` (`sequence`, `original_index` = notebook cell index, `status`).

### 4.5 Turn a chat notebook into a script (agentic service route)

- Call `POST /api/v1/batch/scripts/from-notebook` with `{"artifact_id": "<executor NOTEBOOK artifact id>", "name"?: "…"}`. It returns `201 ScriptView`.
- Only for keys of the agentic service's own tenant, with `X-User-Id` an active user who can see that artifact.
- An artifact that is not a notebook returns 422.
- No `Idempotency-Key`: the service derives one from the artifact and its content.

### 4.6 Batch reports (agentic service routes)

When a run of an agentic-tenant batch completes successfully, the service writes an analysis report and stores it as an executor artifact appended to the run's notebook. Failed runs get no report. Only the owner (the execution's `context.user_id`) sees their reports, and `X-User-Id` must be an active user of the service.

| route | what |
| --- | --- |
| `GET /api/v1/batch-reports?batch_id=&execution_id=&status=&cursor=&limit=` | newest first. `status` takes one or more of `QUEUED`, `COLLECTING`, `GENERATING`, `MATERIALIZING`, `SUCCEEDED`, `FAILED`, comma-separated |
| `GET /api/v1/batch-reports/{report_id}` | `markdown`, `summary`, `artifact_id`, `error`, `failed_stage`, `owner`, `execution` |
| `GET /api/v1/batch-reports/{report_id}/events?types=` | stored progress events (`token` and `activity` are not stored) |
| `GET /api/v1/batch-reports/{report_id}/stream` | Server-Sent Events: stored events, then live ones. Resume with the `Last-Event-ID` header (or `?after=`). The server sends `: keep-alive` every 15 s |
| `POST /api/v1/batch-reports/{report_id}/retry` | re-queue a `FAILED` report → 202. Any other state returns 409 |

Event types:

- `run_status`: `queued` → `running` → (`waiting_executor`) → `succeeded` or `failed`.
- `token`, `activity`, `tool_call`.
- `artifact`: the report or the notebook.
- `message_final`: the report Markdown.
- `run_error`.

## 5. Errors and retries

All errors have one shape (pr-batch's errors and the gateway's):

```json
{"error": {"code": "REVISION_CONFLICT", "message": "human text, may change",
           "details": [{"location": ["header", "If-Match"], "type": "revision_conflict",
                        "message": "…", "context": {"expected": 3, "current": 4}}],
           "context": {}}}
```

| HTTP | `error.code` | cause | what the client does |
| --- | --- | --- | --- |
| 400 | `INVALID_IDENTITY` | `X-User-Id` or `user_id` missing or malformed | fix; no retry |
| 401 | `LOGIN_REQUIRED`, `INVALID_API_KEY` | no key, or unknown or revoked key | fix config; stop |
| 403 | `FORBIDDEN` | unknown or inactive user (agentic tenant), standard key with someone else's `user_id`, own-route call from another tenant's user | no retry |
| 404 | `NOT_FOUND` | route not in the list; missing, deleted, other tenant, or (standard key) other user | check the path or id |
| 409 | `IDEMPOTENCY_CONFLICT` | same key, different body | new work needs a new key |
| 409 | `REVISION_CONFLICT` | stale `If-Match` (`details[0].context.expected`, `current`) | GET, take the new ETag, send with a **new** key |
| 409 | `SCRIPT_IN_USE`, `SCRIPT_HAS_ACTIVE_RUNS`, `BATCH_HAS_ACTIVE_RUNS`, `SCHEDULE_REQUIRED`, `NOT_CANCELLABLE`, `OWNER_DEACTIVATED`, `TENANT_REVOKED` | not allowed in this state | change the state first |
| 409 | `CONFLICT` (with RunView in `context`) | manual run hit the concurrency limit | wait for the running run |
| 413 | `TOO_LARGE` (gateway, 32 MB), `REQUEST_TOO_LARGE`, `UPLOAD_TOO_LARGE` (10 MiB) | too big | shrink |
| 422 | `VALIDATION_ERROR` | missing, typed wrong, out of range, unknown field, missing `If-Match` | fix per `details` |
| 422 | `INVALID_BODY` | the same, on the agentic service's own routes (`from-notebook`, `batch-reports`) or a non-notebook artifact for `from-notebook` | fix per `details` |
| 422 | `INVALID_REVISION`, `INVALID_CURSOR`, `INVALID_POLICY`, `INVALID_NOTEBOOK`, `TOO_MANY_CELLS`, `CELL_TOO_LARGE`, `EMPTY_NOTEBOOK`, `UNSUPPORTED_LANGUAGE`, `UNKNOWN_RUNTIME`, `RUNTIME_NOT_SUPPORTED`, `NO_FUTURE_OCCURRENCE` | bad value | fix |
| 500 | `INTERNAL_ERROR` | bug (`details[0].context.error_id`) | report with `X-Request-ID` |
| 502 | `BAD_GATEWAY` | pr-batch unreachable | retry with backoff, same key and body |
| 503 | `DATABASE_UNAVAILABLE`, `STORAGE_UNAVAILABLE`, `INCONSISTENT_STATE` | transient | retry with backoff, same key and body |
| 503 | `EXECUTOR_NOT_CONFIGURED`, `RUNTIMES_NOT_CONFIGURED` | server config | report; retry later |
| 504 | `ERROR` | pr-batch took > 60 s | retry with backoff, same key and body |

Retry with exponential backoff (1 s, 2 s, 4 s, … up to 30 s, at most 5 tries) only on network errors, `502`, `503` (except the two config codes) and `504`. Use the **same `Idempotency-Key` and the same body**, and you get the first response back.

## 6. Endpoints

Rows 1–22 relay to pr-batch under `/api/v1/batch`. Rows 23–28 are the agentic service's own routes. "IK" means an `Idempotency-Key` header is needed, and "IM" means `If-Match` is needed.

| # | Method | Path | Body | Headers | Success |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/v1/batch/runtimes` | – | | 200 `RuntimeList` |
| 2 | POST | `/api/v1/batch/scripts` | multipart `file`, `type`, `name`? | IK | 201 `ScriptView` |
| 3 | GET | `/api/v1/batch/scripts?limit=&cursor=&user_id=` (limit 1–100, default 50) | – | | 200 `ScriptPage` |
| 4 | GET | `/api/v1/batch/scripts/{script_id}` | – | | 200 `ScriptView` + `ETag` |
| 5 | PATCH | `/api/v1/batch/scripts/{script_id}` | `RenameScript` `{"name"}` | IK, IM | 200 `ScriptView` |
| 6 | DELETE | `/api/v1/batch/scripts/{script_id}` | – | IK, IM | 204 |
| 7 | POST | `/api/v1/batch/scripts/{script_id}/versions` | multipart `file` | IK | 201 `VersionView` (200 if identical bytes) |
| 8 | GET | `/api/v1/batch/scripts/{script_id}/versions?limit=&cursor=` | – | | 200 `VersionPage` (newest first) |
| 9 | GET | `/api/v1/batch/scripts/{script_id}/versions/{version_id}` | – | | 200 `VersionDetail` |
| 10 | GET | `/api/v1/batch/scripts/{script_id}/versions/{version_id}/content` | – | | 200 `.ipynb` bytes |
| 11 | POST | `/api/v1/batch/batches` | `CreateBatch` | IK, `X-Project-Id`? | 201 `BatchView` |
| 12 | GET | `/api/v1/batch/batches?limit=&cursor=&script_id=&user_id=` | – | | 200 `BatchPage` |
| 13 | GET | `/api/v1/batch/batches/{batch_id}` | – | | 200 `BatchView` + `ETag` |
| 14 | PATCH | `/api/v1/batch/batches/{batch_id}` | `UpdateBatch` | IK, IM | 200 `BatchView` |
| 15 | DELETE | `/api/v1/batch/batches/{batch_id}` | – | IK, IM | 204 |
| 16 | POST | `/api/v1/batch/batches/{batch_id}/enable` | – | IK, IM | 200 `BatchView` |
| 17 | POST | `/api/v1/batch/batches/{batch_id}/disable` | – | IK, IM | 200 `BatchView` |
| 18 | GET | `/api/v1/batch/batches/{batch_id}/skipped-windows?limit=&cursor=` | – | | 200 `SkippedPage` |
| 19 | POST | `/api/v1/batch/batches/{batch_id}/runs` | none or `{}` | IK | 202 `RunView` |
| 20 | GET | `/api/v1/batch/batches/{batch_id}/runs?limit=&cursor=` | – | | 200 `RunPage` |
| 21 | GET | `/api/v1/batch/batches/{batch_id}/runs/{run_id}` | – | | 200 `RunDetail` |
| 22 | POST | `/api/v1/batch/batches/{batch_id}/runs/{run_id}/cancel` | – | IK | 202 `RunView` |
| 23 | GET | `/api/v1/batch-reports?batch_id=&execution_id=&status=&cursor=&limit=` | – | | 200 `BatchReportPage` |
| 24 | GET | `/api/v1/batch-reports/{report_id}` | – | | 200 `BatchReportDetail` |
| 25 | GET | `/api/v1/batch-reports/{report_id}/events?types=` | – | | 200 `BatchReportEvents` |
| 26 | GET | `/api/v1/batch-reports/{report_id}/stream` | – | `Last-Event-ID`? | 200 `text/event-stream` |
| 27 | POST | `/api/v1/batch-reports/{report_id}/retry` | – | | 202 `BatchReportDetail` |
| 28 | POST | `/api/v1/batch/scripts/from-notebook` | `BatchScriptFromNotebook` | | 201 `ScriptView` |

The exact query parameters, limits and response codes per route are in `openapi/batch-gateway.openapi.json`.

## 7. Reference client (Python, httpx)

```python
"""Batch gateway client. Config: AGENTIC_BASE_URL, AGENTIC_API_KEY."""

import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "SKIPPED"}
RETRY_CODES = {"BAD_GATEWAY", "DATABASE_UNAVAILABLE", "STORAGE_UNAVAILABLE",
               "INCONSISTENT_STATE", "ERROR", "EXECUTOR_UNAVAILABLE", "EXECUTOR_TIMEOUT"}


class GatewayError(Exception):
    def __init__(self, status: int, body: Any):
        error = body.get("error", {}) if isinstance(body, dict) else {}
        self.status, self.code = status, error.get("code", "UNKNOWN")
        self.details, self.context = error.get("details", []), error.get("context")
        super().__init__(f"{status} {self.code}: {error.get('message', '')}")


class BatchGateway:
    def __init__(self, user_id: str):
        self.http = httpx.Client(base_url=os.environ["AGENTIC_BASE_URL"].rstrip("/"),
                                 timeout=httpx.Timeout(70.0, connect=5.0))  # gateway waits 60 s
        self.base = {"X-Api-Key": os.environ["AGENTIC_API_KEY"], "X-User-Id": user_id.lower()}

    def _call(self, method: str, path: str, *, write: bool = False,
              etag: str | None = None, headers: dict | None = None, **kw) -> httpx.Response:
        h = {**self.base, **(headers or {})}
        if write:
            h["Idempotency-Key"] = str(uuid.uuid4())   # once per logical write
        if etag:
            h["If-Match"] = etag                       # quotes kept, e.g. "3"
        delay = 1.0
        for attempt in range(5):
            try:
                r = self.http.request(method, path, headers=h, **kw)
            except httpx.TransportError:
                if attempt == 4:
                    raise
            else:
                if r.status_code < 400:
                    return r
                try:
                    body = r.json()
                except ValueError:
                    body = {}
                err = GatewayError(r.status_code, body)
                if err.code not in RETRY_CODES or attempt == 4:
                    raise err
            time.sleep(delay)                          # same key, same body
            delay = min(delay * 2, 30)

    # scripts
    def runtimes(self) -> list[dict]:
        return self._call("GET", "/api/v1/batch/runtimes").json()["items"]

    def upload(self, notebook: Path, name: str | None = None) -> dict:
        data = {"type": "NOTEBOOK", **({"name": name} if name else {})}
        files = {"file": (notebook.name, notebook.read_bytes(), "application/x-ipynb+json")}
        return self._call("POST", "/api/v1/batch/scripts", write=True,
                          data=data, files=files).json()

    def add_version(self, script_id: str, notebook: Path) -> dict:
        files = {"file": (notebook.name, notebook.read_bytes(), "application/x-ipynb+json")}
        return self._call("POST", f"/api/v1/batch/scripts/{script_id}/versions",
                          write=True, files=files).json()

    # batches
    def create_batch(self, body: dict, project_id: str | None = None) -> dict:
        headers = {"X-Project-Id": project_id} if project_id else None
        return self._call("POST", "/api/v1/batch/batches", write=True,
                          headers=headers, json=body).json()

    def get_batch(self, batch_id: str) -> tuple[dict, str]:
        r = self._call("GET", f"/api/v1/batch/batches/{batch_id}")
        return r.json(), r.headers["ETag"]

    def _with_etag(self, method: str, path: str, batch_id: str, **kw) -> dict:
        for _ in range(3):  # a stale ETag: read again, new key, try again
            _, etag = self.get_batch(batch_id)
            try:
                r = self._call(method, path, write=True, etag=etag, **kw)
                return r.json() if r.content else {}
            except GatewayError as e:
                if e.code != "REVISION_CONFLICT":
                    raise
        raise RuntimeError("batch keeps changing")

    def enable(self, batch_id: str) -> dict:
        return self._with_etag("POST", f"/api/v1/batch/batches/{batch_id}/enable", batch_id)

    def disable(self, batch_id: str) -> dict:
        return self._with_etag("POST", f"/api/v1/batch/batches/{batch_id}/disable", batch_id)

    def update(self, batch_id: str, changes: dict) -> dict:   # only changed fields
        return self._with_etag("PATCH", f"/api/v1/batch/batches/{batch_id}", batch_id,
                               json=changes)

    # runs
    def run_now(self, batch_id: str) -> dict:
        try:
            return self._call("POST", f"/api/v1/batch/batches/{batch_id}/runs",
                              write=True, json={}).json()
        except GatewayError as e:
            if e.code == "CONFLICT" and (e.context or {}).get("skip_reason") == "SKIPPED_CAPACITY":
                return e.context                        # a SKIPPED RunView
            raise

    def wait_run(self, batch_id: str, run_id: str, *, interval: float = 5.0,
                 timeout: float = 6 * 3600) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            run = self._call("GET", f"/api/v1/batch/batches/{batch_id}/runs/{run_id}").json()
            if run["status"] in TERMINAL:
                return run
            if time.monotonic() > deadline:
                raise TimeoutError(run_id)
            time.sleep(max(interval, 5.0))

    def result_notebook(self, run: dict) -> bytes | None:
        artifact = (run.get("result") or {}).get("notebook_artifact_id")
        if run["status"] != "COMPLETED" or not artifact:
            return None
        return self._call("GET", f"/api/v1/executor/artifacts/{artifact}/content").content

    def list_all(self, path: str, **params) -> list[dict]:
        items, cursor = [], None
        while True:
            q = {**params, **({"cursor": cursor} if cursor else {})}
            page = self._call("GET", path, params=q).json()
            items += page["items"]
            cursor = page.get("next_cursor")
            if not cursor:
                return items
```

Usage:

```python
gw = BatchGateway("e12345")
runtime = gw.runtimes()[0]                                  # {"type": "JUPYTER", "profile": "default"}
script = gw.upload(Path("daily.ipynb"), name="Daily line report")
batch = gw.create_batch({
    "name": "Weekdays 08:00",
    "script_id": script["id"],
    "runtime": runtime,
    "schedule": {"definition": {"kind": "CRON", "expression": "0 8 * * MON-FRI"}},
    "policy": {"overlap": {"mode": "SKIP"}, "misfire": {"mode": "LATEST", "grace_seconds": 600}},
}, project_id="project-100")

run = gw.run_now(batch["id"])                               # try once while still disabled
run = gw.wait_run(batch["id"], run["id"])
if run["status"] == "COMPLETED":
    Path("result.ipynb").write_bytes(gw.result_notebook(run))
else:
    print(run["status"], run["skip_reason"], run["failure_type"], run["last_error"])

view, _ = gw.get_batch(batch["id"])
if view["can_enable"]:
    gw.enable(batch["id"])
else:
    print("cannot enable:", view["enable_blocked_reason"])

gw.update(batch["id"], {"script_version_number": None})    # re-pin to latest; schedule left out
```

## 8. Checklist (common mistakes)

- [ ] `X-User-Id` on every request, reads too.
- [ ] `Idempotency-Key` header on every POST, PATCH and DELETE under `/api/v1/batch/`. Same key on retry, new key after `REVISION_CONFLICT`.
- [ ] `If-Match` with the quotes, from the latest GET or write response.
- [ ] `runtime` copied from `GET /runtimes`.
- [ ] New batches are disabled. Call `enable`, and check `can_enable` first.
- [ ] PATCH sends only changed fields. Never resend an unchanged `schedule`.
- [ ] The manual-run `409 CONFLICT` carries a SKIPPED RunView in `error.context`.
- [ ] Poll runs at ≥ 5 s. `SKIPPED` is terminal too.
- [ ] Result notebook from the executor gateway: `/api/v1/executor/artifacts/{notebook_artifact_id}/content`.
- [ ] Follow `Location` only after rewriting `/api/v1/` → `/api/v1/batch/`.
- [ ] Standard key: no `user_id` filter, or exactly your `X-User-Id`.
- [ ] Ignore unknown response fields and unknown event types.

## 9. Types

Generated from the pr-batch OpenAPI and the agentic service's own routes. Do not edit by hand.

- Interfaces marked `unknown fields → 422` are request bodies. Response types may gain fields, so ignore unknown ones.
- `string` timestamps are ISO 8601 with time zone, and ids are UUID strings.
- `BatchReportEvents.items` uses the agentic service's run event types (`*Event` / `*Data`).
- When our own route's schema name clashes with pr-batch's, our schema is prefixed with `Agentic`.

<!-- gen:begin types -->
```ts
interface ActivityData {
  id: string;
  kind: string;
  state: "started" | "finished" | "failed" | "paused";
  label?: string | null;
  elapsed_ms?: number | null;
}
interface ActivityEvent {
  id: number;
  type: "activity";
  data: ActivityData;
  created_at: string;
}
interface AgentSwitchedData {
  agent: "main" | "analyst";
  task?: string | null;
}
interface AgentSwitchedEvent {
  id: number;
  type: "agent_switched";
  data: AgentSwitchedData;
  created_at: string;
}
interface ArtifactAttachment {
  kind: "report" | "notebook";
  artifact_id: string;
  title: string;
  lab_url?: string | null;
}
interface ArtifactEvent {
  id: number;
  type: "artifact";
  data: ArtifactAttachment;
  created_at: string;
}
interface BatchPage {
  items: BatchView[];
  next_cursor: string | null;
}
interface BatchReportDetail {
  id: string;
  execution_id: string;
  batch_id: string | null;
  batch_run_id: string | null;
  state: "QUEUED" | "COLLECTING" | "GENERATING" | "MATERIALIZING" | "SUCCEEDED" | "FAILED";
  failed_stage: string | null;
  title: string | null;
  artifact_id: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  owner: BatchReportOwner;
  markdown: string | null;
  summary: string | null;
  execution: Record<string, unknown>;
}
interface BatchReportEvents {
  report_id: string;
  state: "QUEUED" | "COLLECTING" | "GENERATING" | "MATERIALIZING" | "SUCCEEDED" | "FAILED";
  items: (RunStatusEvent | TokenEvent | MessageFinalEvent | ToolCallEvent | AgentSwitchedEvent | PlanApprovedEvent | PlanAutoApprovedEvent | PlanRevisedEvent | ExecutionProgressEvent | ExecutionCompletedEvent | HitlRequestEvent | HitlResolvedEvent | ArtifactEvent | MemoryUpdatedEvent | WorkflowSavedEvent | RunErrorEvent | SessionTitledEvent | ActivityEvent | ContextSummarizedEvent)[];
}
interface BatchReportOwner {
  id: string;
  employee_id: string;
  name: string;
}
interface BatchReportPage {
  items: BatchReportRead[];
  next_cursor: string | null;
}
interface BatchReportRead {
  id: string;
  execution_id: string;
  batch_id: string | null;
  batch_run_id: string | null;
  state: "QUEUED" | "COLLECTING" | "GENERATING" | "MATERIALIZING" | "SUCCEEDED" | "FAILED";
  failed_stage: string | null;
  title: string | null;
  artifact_id: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}
interface BatchScriptFromNotebook { // unknown fields → 422
  artifact_id: string;
  name?: string | null;
}
interface BatchView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  name: string;
  script_id: string;
  script_version_id: string;
  script_version_number: number;
  runtime: RuntimeSpec;
  schedule: Schedule | null;
  policy: Policy;
  tenant_id: string;
  project_id: string | null;
  user_id: string;
  enabled: boolean;
  can_enable: boolean;
  can_disable: boolean;
  enable_blocked_reason: string | null;
  disabled_reason: string | null;
  disabled_at: string | null;
  next_run_at: string | null;
  preview_runs: string[];
  config_number: number;
  revision: number;
}
interface Body_add_version_api_v1_scripts__script_id__versions_post {
  file: string;
}
interface Body_create_script_api_v1_scripts_post {
  file: string;
  type: ScriptType;
  name?: string | null; // 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$`
}
interface Calendar { // unknown fields → 422
  kind: "CALENDAR";
  frequency: "DAILY" | "WEEKLY" | "MONTHLY";
  at: string;
  weekdays?: ("MON" | "TUE" | "WED" | "THU" | "FRI" | "SAT" | "SUN")[]; // 항목 ≤ 7
  month_days?: number[]; // 항목 ≤ 31
  last_day?: boolean; // default false
  nth_weekdays?: NthWeekday[]; // 항목 ≤ 35
}
interface CatchUpMisfire { // unknown fields → 422
  mode: "CATCH_UP";
  grace_seconds?: number; // default 300; ≥ 1, ≤ 86400
  max_runs?: number; // default 10; ≥ 1, ≤ 1000
  max_age_seconds?: number; // default 86400; ≥ 60, ≤ 31536000
}
interface CellCounts {
  total: number;
  executable: number;
  skipped: number;
}
interface CellEntry {
  index: number;
  type: string;
  executed: boolean;
  sequence?: number | null;
}
interface CodeApprovalRequest {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "code_approval";
  purpose: string;
  code: string;
  code_level: number;
}
interface ContextSummarizedData {
  messages: number;
  summary_chars: number;
}
interface ContextSummarizedEvent {
  id: number;
  type: "context_summarized";
  data: ContextSummarizedData;
  created_at: string;
}
interface CreateBatch { // unknown fields → 422
  name: string; // 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$`
  script_id: string;
  script_version_number?: number | null; // ≥ 1
  runtime: RuntimeSpec;
  schedule?: Schedule | null;
  policy?: Policy;
}
interface Cron { // unknown fields → 422
  kind: "CRON";
  expression: string; // 길이 ≥ 1, 길이 ≤ 128
}
interface ExecutionCompletedData {
  execution_id: string;
  results: StepResult[];
  error?: string | null;
}
interface ExecutionCompletedEvent {
  id: number;
  type: "execution_completed";
  data: ExecutionCompletedData;
  created_at: string;
}
interface ExecutionProgressData {
  event_type: string;
  status?: string | null;
  step?: Record<string, unknown> | null;
  error?: unknown;
  reason?: string | null;
  paused_seconds?: number | null;
  finished_during_handover?: boolean | null;
}
interface ExecutionProgressEvent {
  id: number;
  type: "execution_progress";
  data: ExecutionProgressData;
  created_at: string;
}
interface ExecutorWait {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "executor_wait";
  execution_id: string;
  operation_id: string | null;
  steps?: string[];
}
interface HitlRequestEvent {
  id: number;
  type: "hitl_request";
  data: QuestionRequest | PlanApprovalRequest | CodeApprovalRequest | WorkflowSaveRequest | ExecutorWait;
  created_at: string;
}
interface HitlResolvedData {
  interrupt_id: string | null;
}
interface HitlResolvedEvent {
  id: number;
  type: "hitl_resolved";
  data: HitlResolvedData;
  created_at: string;
}
interface InputSlot {
  key: string;
  tool: string;
  param: string;
  type?: string | null;
  required: boolean;
  value?: unknown;
}
interface Interval { // unknown fields → 422
  kind: "INTERVAL";
  seconds: number; // ≥ 60, ≤ 31536000
  anchor?: string | null;
}
interface LatestMisfire { // unknown fields → 422
  mode: "LATEST";
  grace_seconds?: number; // default 300; ≥ 1, ≤ 86400
}
type ManualRun = Record<string, unknown>;
interface MemoryUpdatedData {
  topic: string;
  title: string;
  content: string;
  version: number;
  updated_at: string | null;
  by: "user" | "agent";
}
interface MemoryUpdatedEvent {
  id: number;
  type: "memory_updated";
  data: MemoryUpdatedData;
  created_at: string;
}
interface MessageFinalData {
  content: string;
}
interface MessageFinalEvent {
  id: number;
  type: "message_final";
  data: MessageFinalData;
  created_at: string;
}
interface MisfirePatch { // unknown fields → 422
  mode?: "SKIP" | "LATEST" | "CATCH_UP" | null;
  grace_seconds?: number | null; // ≥ 1, ≤ 86400
  max_runs?: number | null; // ≥ 1, ≤ 1000
  max_age_seconds?: number | null; // ≥ 60, ≤ 31536000
}
interface NthWeekday { // unknown fields → 422
  weekday: "MON" | "TUE" | "WED" | "THU" | "FRI" | "SAT" | "SUN";
  nth: 1 | 2 | 3 | 4 | 5 | -1;
}
interface Once { // unknown fields → 422
  kind: "ONCE";
  at: string;
}
interface OverlapPatch { // unknown fields → 422
  mode?: "SKIP" | "QUEUE" | "PARALLEL" | "REPLACE" | null;
  max_concurrent?: number | null; // ≥ 1, ≤ 100
  max_queued?: number | null; // ≥ 1, ≤ 10000
}
interface ParallelOverlap { // unknown fields → 422
  mode: "PARALLEL";
  max_concurrent: number; // ≥ 1, ≤ 100
  max_queued?: number; // default 100; ≥ 1, ≤ 10000
}
interface ParamRef {
  call: number | null;
  tool: string | null;
  output: string;
}
interface PlanApprovalRequest {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "plan_approval";
  candidates: PlanCandidate[];
  allow_reject_templates?: boolean; // default false
}
interface PlanApprovedData {
  plan_id: string;
  title: string;
  document: Record<string, unknown>;
}
interface PlanApprovedEvent {
  id: number;
  type: "plan_approved";
  data: PlanApprovedData;
  created_at: string;
}
interface PlanAutoApprovedData {
  title: string;
  source?: WorkflowSource | null;
}
interface PlanAutoApprovedEvent {
  id: number;
  type: "plan_auto_approved";
  data: PlanAutoApprovedData;
  created_at: string;
}
interface PlanCall {
  index: number;
  key: string;
  skill: string;
  skill_description?: string; // default ""
  tool: string;
  summary?: string; // default ""
  execution: "always" | "conditional";
  condition?: string | null;
  params: PlanParam[];
}
interface PlanCandidate {
  title: string;
  rationale?: string; // default ""
  source?: WorkflowSource | null;
  document: Record<string, unknown>;
  calls: PlanCall[];
  input_slots: InputSlot[];
  input_values?: Record<string, unknown>;
}
interface PlanParam {
  name: string;
  key: string;
  type: string | null;
  required: boolean;
  doc?: string; // default ""
  source: "literal" | "input" | "tool_output" | "default";
  value?: unknown;
  default?: string | null;
  ref?: ParamRef | null;
}
interface PlanRevisedData {
  call: number;
  args: Record<string, unknown>;
}
interface PlanRevisedEvent {
  id: number;
  type: "plan_revised";
  data: PlanRevisedData;
  created_at: string;
}
interface Policy { // unknown fields → 422
  overlap?: SkipOverlap | QueueOverlap | ParallelOverlap | ReplaceOverlap;
  misfire?: SkipMisfire | LatestMisfire | CatchUpMisfire;
}
interface PolicyPatch { // unknown fields → 422
  overlap?: OverlapPatch | null;
  misfire?: MisfirePatch | null;
}
interface QuestionField {
  key: string;
  label?: string | null;
  type?: string | null;
  required?: boolean; // default false
}
interface QuestionRequest {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "question";
  question: string;
  options?: string[];
  fields?: QuestionField[];
}
interface QueueOverlap { // unknown fields → 422
  mode: "QUEUE";
  max_queued?: number; // default 100; ≥ 1, ≤ 10000
}
interface RenameScript { // unknown fields → 422
  name: string; // 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$`
}
interface ReplaceOverlap { // unknown fields → 422
  mode: "REPLACE";
}
interface ResultRefs {
  notebook_artifact_id?: string | null;
}
interface RunDetail {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  batch_id: string;
  user_id: string;
  script_id: string;
  script_version_id: string;
  config_number: number;
  runtime: Record<string, unknown>;
  snapshot: Record<string, unknown>;
  trigger: string;
  scheduled_for: string | null;
  status: string;
  skip_reason: string | null;
  cancel_requested: boolean;
  cancel_source: string | null;
  cancel_reason: string | null;
  execution_id: string | null;
  operation_id: string | null;
  execution_status: string | null;
  observed_version: number | null;
  failure_type: string | null;
  notebook_status: string | null;
  last_error: string | null;
  artifacts: Record<string, unknown>[];
  attempts: Record<string, unknown>[];
  retry_info: Record<string, unknown> | null;
  result?: ResultRefs; // default {}
  submitted_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  observed_at: string | null;
  completed_at: string | null;
  steps: StepView[];
}
interface RunErrorData {
  message: string;
}
interface RunErrorEvent {
  id: number;
  type: "run_error";
  data: RunErrorData;
  created_at: string;
}
interface RunPage {
  items: RunView[];
  next_cursor: string | null;
}
interface RunStatusData {
  status: "queued" | "running" | "waiting_input" | "waiting_executor" | "succeeded" | "failed" | "cancelled";
  execution_id?: string | null;
  operation_id?: string | null;
  steps?: string[] | null;
}
interface RunStatusEvent {
  id: number;
  type: "run_status";
  data: RunStatusData;
  created_at: string;
}
interface RunView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  batch_id: string;
  user_id: string;
  script_id: string;
  script_version_id: string;
  config_number: number;
  runtime: Record<string, unknown>;
  snapshot: Record<string, unknown>;
  trigger: string;
  scheduled_for: string | null;
  status: string;
  skip_reason: string | null;
  cancel_requested: boolean;
  cancel_source: string | null;
  cancel_reason: string | null;
  execution_id: string | null;
  operation_id: string | null;
  execution_status: string | null;
  observed_version: number | null;
  failure_type: string | null;
  notebook_status: string | null;
  last_error: string | null;
  artifacts: Record<string, unknown>[];
  attempts: Record<string, unknown>[];
  retry_info: Record<string, unknown> | null;
  result?: ResultRefs; // default {}
  submitted_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  observed_at: string | null;
  completed_at: string | null;
}
interface RuntimeList {
  items: RuntimeSpec[];
}
interface RuntimeSpec { // unknown fields → 422
  type?: "JUPYTER"; // default "JUPYTER"
  profile: string; // 길이 ≥ 1, 길이 ≤ 128, `^[^\x00-\x1f\x7f]+$`
}
interface Schedule { // unknown fields → 422
  definition: Once | Interval | Calendar | Cron;
  timezone?: "Asia/Seoul"; // default "Asia/Seoul"
  start_at?: string | null;
  end_at?: string | null;
}
interface ScriptPage {
  items: ScriptView[];
  next_cursor: string | null;
}
type ScriptType = "NOTEBOOK";
interface ScriptView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  name: string;
  type: ScriptType;
  user_id: string;
  revision: number;
  latest_version: VersionView;
}
interface SessionTitledData {
  title: string;
}
interface SessionTitledEvent {
  id: number;
  type: "session_titled";
  data: SessionTitledData;
  created_at: string;
}
interface SkipMisfire { // unknown fields → 422
  mode: "SKIP";
  grace_seconds?: number; // default 300; ≥ 1, ≤ 86400
}
interface SkipOverlap { // unknown fields → 422
  mode: "SKIP";
}
interface SkippedPage {
  items: SkippedView[];
  next_cursor: string | null;
}
interface SkippedView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  batch_id: string;
  config_number: number;
  from_at: string;
  until_at: string;
  occurrences: number;
  reason: string;
}
interface StepResult {
  call?: number | null;
  tool?: string | null;
  id?: string | null;
  status: string;
  observations?: unknown[];
  stdout?: string; // default ""
  images?: string[];
  error?: unknown;
}
interface StepView {
  sequence: number;
  original_index: number;
  source_sha256: string;
  step_id: string | null;
  status: string | null;
  result_ref: Record<string, unknown> | null;
}
interface TokenData {
  text: string;
}
interface TokenEvent {
  id: number;
  type: "token";
  data: TokenData;
  created_at: string;
}
interface ToolCallData {
  name: string;
  args: Record<string, unknown>;
  label?: string; // default ""
}
interface ToolCallEvent {
  id: number;
  type: "tool_call";
  data: ToolCallData;
  created_at: string;
}
interface UpdateBatch { // unknown fields → 422
  name?: string | null; // 길이 ≥ 1, 길이 ≤ 255, `^[^\x00-\x1f\x7f]+$`
  script_id?: string | null;
  script_version_number?: number | null; // ≥ 1
  runtime?: RuntimeSpec | null;
  schedule?: Schedule | null;
  policy?: PolicyPatch | null;
}
interface VersionDetail {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  script_id: string;
  version_number: number;
  filename: string;
  sha256: string;
  code_hash: string;
  size_bytes: number;
  cells: CellCounts;
  cell_list: CellEntry[];
}
interface VersionPage {
  items: VersionView[];
  next_cursor: string | null;
}
interface VersionView {
  created_at: string;
  created_by: string | null;
  created_by_client: string | null;
  updated_at: string;
  updated_by: string | null;
  updated_by_client: string | null;
  id: string;
  script_id: string;
  version_number: number;
  filename: string;
  sha256: string;
  code_hash: string;
  size_bytes: number;
  cells: CellCounts;
}
interface WorkflowSaveRequest {
  interrupt_id: string;
  kind?: "input" | "executor" | null;
  type: "workflow_save";
  name: string;
  user_queries: string[];
  tags?: string[];
  document: Record<string, unknown>;
  excluded_custom_steps?: number; // default 0
}
interface WorkflowSavedData {
  workflow_id: string;
  name: string;
}
interface WorkflowSavedEvent {
  id: number;
  type: "workflow_saved";
  data: WorkflowSavedData;
  created_at: string;
}
interface WorkflowSource {
  workflow_id: string;
  revision: number;
  name: string;
  similarity?: number | null;
}
```
<!-- gen:end types -->

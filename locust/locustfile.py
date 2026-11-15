"""Load test for pr-agentic-service, as a key caller (no SSO).

    locust -f locust/locustfile.py --host https://<host>

Every virtual user acts for one employee id (``X-Api-Key`` +
``X-User-Id``) and repeats five things, by weight: light reads, a plain
chat turn, an analysis turn it approves by itself, a code execution sent
straight to the executor (no LLM) and a run of one of its own batches
(no LLM until the report). Each is followed to its end by polling and
reported as its own row of type ``RUN``. Settings come from the
environment, then ``config.yml`` next to this file: see README.md.
"""

import itertools
import json
import os
import time
import uuid
from pathlib import Path

import yaml
from locust import HttpUser, LoadTestShape, between, events, task
from locust.exception import StopUser

HERE = Path(__file__).parent


def _file() -> dict:
    """The settings file: ``LOAD_CONFIG``, else ``config.yml`` next to this
    file when it is there."""
    named = os.environ.get("LOAD_CONFIG")
    path = Path(named) if named else HERE / "config.yml"
    if not path.is_file():
        if named:
            raise SystemExit(f"[locust] LOAD_CONFIG: no file {path}")
        return {}
    values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(values, dict):
        raise SystemExit(f"[locust] {path}: expected 'NAME: value' lines")
    print(f"[locust] settings from {path}")
    return values


FILE = _file()


def _env(name: str, default: str) -> str:
    """A setting: the environment, then the settings file, then the
    default."""
    if name in os.environ:
        return os.environ[name]
    value = FILE.get(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


unknown = sorted(k for k in FILE if not str(k).startswith("LOAD_"))
if unknown:
    raise SystemExit(f"[locust] unknown settings in the file: {unknown}")

HOST = _env("LOAD_HOST", "").rstrip("/")

API_KEY = _env("LOAD_API_KEY", "")
PREFIX = _env("LOAD_API_PREFIX", "/api/v1").rstrip("/")
USERS_FILE = Path(_env("LOAD_USERS_FILE", str(HERE / "users.csv")))
MODEL = _env("LOAD_MODEL", "")  # empty: the service default
CHAT_PROMPT = _env("LOAD_CHAT_PROMPT", "안녕, 오늘 할 수 있는 분석을 알려줘")
ANALYSIS_PROMPT = _env(
    "LOAD_ANALYSIS_PROMPT", "nce 데이터 불러와서 기술통계 보여줘"
)
QUESTION_ANSWER = _env("LOAD_QUESTION_ANSWER", "기본값으로 진행해줘")
POLL_SECONDS = float(_env("LOAD_POLL_SECONDS", "2"))
# pause between two actions of one user
WAIT_MIN = float(_env("LOAD_WAIT_MIN_SECONDS", "1"))
WAIT_MAX = float(_env("LOAD_WAIT_MAX_SECONDS", "5"))
RUN_TIMEOUT = float(_env("LOAD_RUN_TIMEOUT_SECONDS", "900"))
READ_WEIGHT = int(_env("LOAD_READ_WEIGHT", "6"))
CHAT_WEIGHT = int(_env("LOAD_CHAT_WEIGHT", "3"))
ANALYSIS_WEIGHT = int(_env("LOAD_ANALYSIS_WEIGHT", "1"))
EXECUTOR_WEIGHT = int(_env("LOAD_EXECUTOR_WEIGHT", "0"))
BATCH_WEIGHT = int(_env("LOAD_BATCH_WEIGHT", "0"))
# values for the empty inputs of a plan: {"<param name or slot key>": value}
PLAN_INPUTS = json.loads(_env("LOAD_PLAN_INPUTS", "{}"))
EXECUTOR_CODE = _env(
    "LOAD_EXECUTOR_CODE", "import time\ntime.sleep(10)\nprint(1 + 1)"
)
EXECUTOR_PROFILE = _env("LOAD_EXECUTOR_PROFILE", "default")
BATCH_PREFIX = _env("LOAD_BATCH_NAME_PREFIX", "load-")
# a fixed load from the settings instead of -u / -r / -t: USERS users, RATE
# more a second, for RUN_SECONDS (0: until stopped). USERS 0: off
USERS = int(_env("LOAD_USERS", "0"))
SPAWN_RATE = float(_env("LOAD_SPAWN_RATE", "1"))
RUN_SECONDS = int(_env("LOAD_RUN_SECONDS", "0"))
# users go up by STEP_USERS every STEP_SECONDS until MAX_USERS (0: off);
# wins over LOAD_USERS
STEP_USERS = int(_env("LOAD_STEP_USERS", "0"))
STEP_SECONDS = int(_env("LOAD_STEP_SECONDS", "300"))
MAX_USERS = int(_env("LOAD_MAX_USERS", "100"))
DELETE_SESSIONS = _env("LOAD_DELETE_SESSIONS", "true").lower() == "true"
VERIFY_TLS = _env("LOAD_VERIFY_TLS", "true").lower() == "true"
MAX_ANSWERS = 12  # questions answered in one turn before giving up

DONE = {"succeeded", "failed", "cancelled"}
EXECUTION_DONE = {"SUCCEEDED", "FAILED", "CANCELLED"}
BATCH_RUN_DONE = {"COMPLETED", "FAILED", "CANCELLED", "SKIPPED"}


def employee_ids() -> list[str]:
    """One id per line (a header line ``employee_id`` and # lines skipped)."""
    if not USERS_FILE.is_file():
        return []
    ids = []
    for line in USERS_FILE.read_text(encoding="utf-8").splitlines():
        value = line.split(",")[0].strip().lower()
        if value and not value.startswith("#") and value != "employee_id":
            ids.append(value)
    return ids


IDS = employee_ids()
NEXT_ID = itertools.cycle(IDS) if IDS else None


@events.init.add_listener
def check_settings(environment, **_):
    problems = []
    if not API_KEY:
        problems.append("LOAD_API_KEY is empty (our tenant's key)")
    if not IDS:
        problems.append(f"no employee ids in {USERS_FILE}")
    if problems:
        for problem in problems:
            print(f"[locust] {problem}")
        environment.process_exit_code = 2
        if environment.runner:
            environment.runner.quit()


def plan_inputs(candidate: dict) -> tuple[dict, list[str]]:
    """Values for the required empty inputs of a plan, and the ones
    ``LOAD_PLAN_INPUTS`` has no value for."""
    given = candidate.get("input_values") or {}
    values, missing = {}, []
    for slot in candidate.get("input_slots") or []:
        key = slot["key"]
        if given.get(key) not in (None, "", []) or slot.get("value") not in (
            None,
            "",
            [],
        ):
            continue
        for name in (key, slot.get("param")):
            if name in PLAN_INPUTS:
                values[key] = PLAN_INPUTS[name]
                break
        else:
            if slot.get("required"):
                missing.append(f"{key} ({slot.get('type')})")
    return values, missing


def answer(waiting: dict) -> tuple[object, str | None]:
    """(reply, None) to one question, or (None, why it cannot be answered)."""
    kind = waiting.get("type")
    if kind == "plan_approval":
        candidates = waiting.get("candidates") or [{}]
        values, missing = plan_inputs(candidates[0])
        if missing:
            return None, "plan needs LOAD_PLAN_INPUTS for " + ", ".join(
                missing
            )
        return {"action": "approve", "index": 0, "input_values": values}, None
    if kind == "code_approval":
        return {"approve": True}, None
    if kind == "workflow_save":
        return {"approve": False}, None
    if kind == "question":
        if waiting.get("fields"):
            # structured inputs: nothing sensible to send
            return None, "question with input fields"
        options = waiting.get("options") or []
        return (options[0] if options else QUESTION_ANSWER), None
    return None, f"unknown question type {kind}"


if STEP_USERS > 0:

    class Steps(LoadTestShape):
        """STEP_USERS more users every STEP_SECONDS, up to MAX_USERS, then
        one more step at MAX_USERS and stop."""

        def tick(self):
            step = int(self.get_run_time() // STEP_SECONDS) + 1
            users = step * STEP_USERS
            if users - STEP_USERS >= MAX_USERS:
                return None
            return min(users, MAX_USERS), STEP_USERS

elif USERS > 0:

    class Fixed(LoadTestShape):
        """USERS users for RUN_SECONDS."""

        def tick(self):
            if RUN_SECONDS and self.get_run_time() >= RUN_SECONDS:
                return None
            return USERS, SPAWN_RATE


class ServiceUser(HttpUser):
    wait_time = between(WAIT_MIN, WAIT_MAX)
    if HOST:
        host = HOST  # --host on the command line still wins

    def on_start(self):
        self.client.verify = VERIFY_TLS
        self.employee = next(NEXT_ID)
        self.batches: list[str] | None = None
        self.turns = 0
        self.client.headers.update(
            {"X-Api-Key": API_KEY, "X-User-Id": self.employee}
        )
        with self.client.get(
            f"{PREFIX}/users/me", name="GET /users/me", catch_response=True
        ) as r:
            if r.status_code != 200:
                # 401: the key, 403: this id never logged in or is inactive
                r.failure(f"users/me {r.status_code}: {r.text[:200]}")
                raise StopUser()
            self.project = r.json()["default_project_id"]

    # -- light reads -------------------------------------------------------
    @task(READ_WEIGHT)
    def reads(self):
        self.client.get(f"{PREFIX}/users/me", name="GET /users/me")
        self.client.get(
            f"{PREFIX}/projects/{self.project}/sessions?limit=20",
            name="GET /projects/[id]/sessions",
        )

    # -- turns -------------------------------------------------------------
    @task(CHAT_WEIGHT)
    def chat(self):
        self.turn("chat turn", CHAT_PROMPT)

    @task(ANALYSIS_WEIGHT)
    def analysis(self):
        self.turn("analysis turn", ANALYSIS_PROMPT)

    # -- executor and batch, without the agent --------------------------------
    @task(EXECUTOR_WEIGHT)
    def execution(self):
        """One code execution sent straight to the executor."""
        started = time.perf_counter()
        body = {
            "idempotency_key": f"load-{uuid.uuid4()}",
            "lifecycle": {"operation_mode": "SINGLE"},
            "trigger": {"type": "INTERACTIVE"},
            "runtime": {"type": "JUPYTER", "profile": EXECUTOR_PROFILE},
            "operation": {
                "spec": {
                    "schema_version": "1.0",
                    "steps": [
                        {
                            "sequence": 0,
                            "payload": {
                                "type": "PYTHON_EXECUTE",
                                "source": {
                                    "type": "INLINE",
                                    "content": EXECUTOR_CODE,
                                },
                            },
                        }
                    ],
                }
            },
        }
        with self.client.post(
            f"{PREFIX}/executor/executions",
            json=body,
            headers={"X-Project-Id": self.project},
            name="POST /executor/executions",
            catch_response=True,
        ) as r:
            if r.status_code not in (200, 201, 202):
                r.failure(f"{r.status_code}: {r.text[:200]}")
                return
            data = r.json()
        execution = data.get("id") or data.get("execution_id")
        error = self.wait(
            f"{PREFIX}/executor/executions/{execution}",
            "GET /executor/executions/[id]",
            EXECUTION_DONE,
            "SUCCEEDED",
            started,
            f"{PREFIX}/executor/executions/{execution}/cancel",
        )
        self.report("executor execution", started, error)

    @task(BATCH_WEIGHT)
    def batch(self):
        """Runs one of this user's batches named ``LOAD_BATCH_NAME_PREFIX``
        now and follows the run (not the report written after it)."""
        if self.batches is None:
            r = self.client.get(
                f"{PREFIX}/batch/batches?limit=50", name="GET /batch/batches"
            )
            items = r.json().get("items", []) if r.status_code == 200 else []
            self.batches = [
                b["id"]
                for b in items
                if str(b.get("name", "")).startswith(BATCH_PREFIX)
            ]
            if not self.batches:
                print(
                    f"[locust] {self.employee}: no batch named "
                    f"{BATCH_PREFIX}*; batch runs skipped for this user"
                )
        if not self.batches:
            return
        batch = self.batches[self.turns % len(self.batches)]
        self.turns += 1
        started = time.perf_counter()
        with self.client.post(
            f"{PREFIX}/batch/batches/{batch}/runs",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            name="POST /batch/batches/[id]/runs",
            catch_response=True,
        ) as r:
            if r.status_code not in (200, 201, 202):
                r.failure(f"{r.status_code}: {r.text[:200]}")
                return
            data = r.json()
        run = data.get("id") or data.get("run_id")
        error = self.wait(
            f"{PREFIX}/batch/batches/{batch}/runs/{run}",
            "GET /batch/batches/[id]/runs/[id]",
            BATCH_RUN_DONE,
            "COMPLETED",
            started,
            f"{PREFIX}/batch/batches/{batch}/runs/{run}/cancel",
        )
        self.report("batch run", started, error)

    def wait(
        self,
        url: str,
        name: str,
        done: set[str],
        good: str,
        started: float,
        cancel_url: str,
    ) -> str | None:
        """Polls ``url`` until its status is in ``done``. Error text or
        None."""
        while True:
            if time.perf_counter() - started > RUN_TIMEOUT:
                self.client.post(
                    cancel_url,
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    name=name.replace("GET", "POST") + "/cancel",
                )
                return f"not finished in {RUN_TIMEOUT:.0f}s"
            time.sleep(POLL_SECONDS)
            r = self.client.get(url, name=name)
            if r.status_code != 200:
                return f"{name} {r.status_code}"
            state = r.json()
            status = state.get("status")
            if status in done:
                if status == good:
                    return None
                why = (
                    state.get("error")
                    or state.get("failure_reason")
                    or state.get("skip_reason")
                    or ""
                )
                return f"{status}: {str(why)[:120]}"

    def report(self, name: str, started: float, error: str | None) -> None:
        events.request.fire(
            request_type="RUN",
            name=name,
            response_time=(time.perf_counter() - started) * 1000,
            response_length=0,
            exception=Exception(error) if error else None,
            context={},
        )

    def turn(self, name: str, prompt: str):
        started = time.perf_counter()
        body = {"input": {"content": prompt}}
        if MODEL:
            body["model"] = MODEL
        with self.client.post(
            f"{PREFIX}/projects/{self.project}/sessions",
            json=body,
            name="POST /projects/[id]/sessions",
            catch_response=True,
        ) as r:
            if r.status_code != 201:
                r.failure(f"{r.status_code}: {r.text[:200]}")
                return
            data = r.json()
        session, run = data["session"]["id"], data["run"]["id"]
        error = self.follow(session, run, started)
        self.report(name, started, error)
        if DELETE_SESSIONS:
            self.client.delete(
                f"{PREFIX}/sessions/{session}", name="DELETE /sessions/[id]"
            )

    def follow(self, session: str, run: str, started: float) -> str | None:
        """Polls the run to its end, answering questions. Error text or
        None."""
        answered: set[str] = set()
        while True:
            if time.perf_counter() - started > RUN_TIMEOUT:
                self.client.post(
                    f"{PREFIX}/runs/{run}/cancel",
                    name="POST /runs/[id]/cancel",
                )
                return f"not finished in {RUN_TIMEOUT:.0f}s"
            time.sleep(POLL_SECONDS)
            r = self.client.get(f"{PREFIX}/runs/{run}", name="GET /runs/[id]")
            if r.status_code != 200:
                return f"GET /runs {r.status_code}"
            state = r.json()
            status = state["status"]
            if status in DONE:
                if status == "succeeded":
                    return None
                return f"run {status}: {str(state.get('error'))[:120]}"
            waiting = state.get("waiting") or {}
            interrupt = waiting.get("interrupt_id")
            if (
                status != "waiting_input"
                or not interrupt
                or interrupt in answered
            ):
                continue
            if len(answered) >= MAX_ANSWERS:
                self.cancel(run)
                return f"more than {MAX_ANSWERS} questions in one turn"
            value, problem = answer(waiting)
            if problem:
                self.cancel(run)
                return problem
            answered.add(interrupt)
            with self.client.post(
                f"{PREFIX}/sessions/{session}/runs",
                json={
                    "command": {
                        "resume": {"interrupt_id": interrupt, "value": value}
                    }
                },
                name=f"POST /sessions/[id]/runs ({waiting.get('type')})",
                catch_response=True,
            ) as reply:
                if reply.status_code == 202:
                    continue
                if reply.status_code == 409:
                    reply.success()  # answered meanwhile: keep polling
                    continue
                # 422: the plan has an empty required input, for example
                reply.failure(f"{reply.status_code}: {reply.text[:200]}")
                self.cancel(run)
                return f"answer refused ({reply.status_code})"

    def cancel(self, run: str) -> None:
        self.client.post(
            f"{PREFIX}/runs/{run}/cancel", name="POST /runs/[id]/cancel"
        )

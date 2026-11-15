"""Load test for pr-agentic-service, as a key caller (no SSO).

    locust -f locust/locustfile.py --host https://<host>

Every virtual user acts for one employee id (``X-Api-Key`` +
``X-User-Id``) and repeats three things: light reads, a plain chat turn,
and an analysis turn it approves by itself. A turn is followed by polling
``GET /runs/{id}`` until it ends; the whole turn is reported as its own
row ("RUN chat turn", "RUN analysis turn"). Settings come from the
environment: see README.md.
"""

import itertools
import os
import time
from pathlib import Path

from locust import HttpUser, between, events, task
from locust.exception import StopUser

HERE = Path(__file__).parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


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
RUN_TIMEOUT = float(_env("LOAD_RUN_TIMEOUT_SECONDS", "900"))
READ_WEIGHT = int(_env("LOAD_READ_WEIGHT", "6"))
CHAT_WEIGHT = int(_env("LOAD_CHAT_WEIGHT", "3"))
ANALYSIS_WEIGHT = int(_env("LOAD_ANALYSIS_WEIGHT", "1"))
DELETE_SESSIONS = _env("LOAD_DELETE_SESSIONS", "true").lower() == "true"
VERIFY_TLS = _env("LOAD_VERIFY_TLS", "true").lower() == "true"
MAX_ANSWERS = 12  # questions answered in one turn before giving up

DONE = {"succeeded", "failed", "cancelled"}


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


def answer(waiting: dict):
    """The reply to one question, or None when it cannot be answered."""
    kind = waiting.get("type")
    if kind == "plan_approval":
        return {"action": "approve", "index": 0}
    if kind == "code_approval":
        return {"approve": True}
    if kind == "workflow_save":
        return {"approve": False}
    if kind == "question":
        if waiting.get("fields"):
            return None  # structured inputs: nothing sensible to send
        options = waiting.get("options") or []
        return options[0] if options else QUESTION_ANSWER
    return None


class ServiceUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        self.client.verify = VERIFY_TLS
        self.client.headers.update(
            {"X-Api-Key": API_KEY, "X-User-Id": next(NEXT_ID)}
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
        events.request.fire(
            request_type="RUN",
            name=name,
            response_time=(time.perf_counter() - started) * 1000,
            response_length=0,
            exception=Exception(error) if error else None,
            context={},
        )
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
            value = answer(waiting)
            if value is None:
                self.cancel(run)
                return f"cannot answer a {waiting.get('type')} question"
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

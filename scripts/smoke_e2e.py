"""Local smoke test.

dev login -> analysis request -> approve plan -> executor -> report.

    uv run python scripts/smoke_e2e.py [base_url]
Needs the service (SSO_ADAPTER=dev), the executor stack and an LLM
(or scripts/mock_llm.py).
"""

import json
import sys
import threading
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
REQUEST = (
    sys.argv[2]
    if len(sys.argv) > 2
    else "NCE와 WT 데이터를 결합해서 탐색 분석해줘"
)
client = httpx.Client(base_url=BASE, timeout=30, follow_redirects=False)
client.get("/api/v1/auth/login/sso", params={"return_to": "/"})
csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
client.headers["X-CSRF-Token"] = csrf
project = client.get("/api/v1/users/me").json()["default_project_id"]
started = client.post(
    f"/api/v1/projects/{project}/sessions",
    json={"input": {"content": REQUEST}},
).json()
session, run = started["session"]["id"], started["run"]["id"]
print("session", session, "run", run)


def listen():
    with (
        httpx.Client(
            base_url=BASE, cookies=client.cookies, timeout=None
        ) as sse,
        sse.stream("GET", f"/api/v1/sessions/{session}/events") as r,
    ):
        for line in r.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["type"] != "token":
                    print(
                        "  [sse]",
                        event["type"],
                        json.dumps(event["data"], ensure_ascii=False)[:160],
                    )


threading.Thread(target=listen, daemon=True).start()
deadline = time.time() + 900
while time.time() < deadline:
    state = client.get(f"/api/v1/runs/{run}").json()
    if state["status"] == "waiting_input":
        waiting = state["waiting"]
        if waiting["type"] == "plan_approval":
            answer = {"action": "approve", "index": 0, "input_values": {}}
        elif waiting["type"] == "question":
            answer = "기본값으로 진행해줘. 데이터는 NCE, 표본 500개."
        else:
            answer = {"approve": True}
        print("HITL", waiting["type"], "->", answer)
        resume = {"interrupt_id": waiting["interrupt_id"], "value": answer}
        client.post(
            f"/api/v1/sessions/{session}/runs",
            json={"command": {"resume": resume}},
        ).raise_for_status()
    elif state["status"] in {"succeeded", "failed", "cancelled"}:
        print("RUN", state["status"], state.get("error"))
        break
    time.sleep(2)
for m in client.get(f"/api/v1/sessions/{session}/messages").json()["items"]:
    print(f"[{m['role']}] {m['content'][:300]}")

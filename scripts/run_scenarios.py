"""Runs agent scenarios against a running service and scores them.

    uv run python scripts/run_scenarios.py                      # all
    uv run python scripts/run_scenarios.py s03_lot_compare s05_fdc_drift
    uv run python scripts/run_scenarios.py --out results.json

Scenarios: catalogs/analysis_test/scenarios.yml (format at its top). Each
scenario gets its own session. Approval cards are answered automatically:
the first candidate, empty inputs filled from the scenario's ``inputs``;
questions from its ``answers``; code runs approved; workflow saves and
memory changes declined. Prints a table and writes JSON with the details.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "catalogs/analysis_test/scenarios.yml"
TERMINAL = {"succeeded", "failed", "cancelled"}


class Session:
    def __init__(self, base: str):
        self.c = httpx.Client(base_url=base + "/api/v1", timeout=60)
        self.c.get("/auth/login/sso", params={"return_to": "/"})
        csrf = self.c.get("/auth/session").json()["csrf_token"]
        self.c.headers["X-CSRF-Token"] = csrf
        self.project = self.c.get("/users/me").json()["default_project_id"]

    def new_session(self, title: str) -> str:
        r = self.c.post(
            f"/projects/{self.project}/sessions", json={"title": title}
        )
        r.raise_for_status()
        return r.json()["session"]["id"]


def _answer(waiting: dict, scenario: dict, state: dict):
    kind = waiting["type"]
    state["hitl"].append(kind)
    if kind == "plan_approval":
        candidate = waiting["candidates"][0]
        inputs = scenario.get("inputs") or {}
        given = dict(candidate.get("input_values") or {})
        missing = []
        for slot in candidate.get("input_slots") or []:
            if given.get(slot["key"]) is not None:
                continue
            if slot["param"] in inputs:
                given[slot["key"]] = inputs[slot["param"]]
            elif slot.get("required"):
                missing.append(slot["param"])
        if missing:
            state["revisions"] += 1
            if state["revisions"] > 2:
                return {"action": "cancel"}
            return {
                "action": "revise",
                "feedback": f"입력칸 {missing}의 값을 계획에 직접 정해서 "
                "다시 제안해줘",
            }
        slots = {s["key"] for s in candidate.get("input_slots") or []}
        return {
            "action": "approve",
            "index": 0,
            "input_values": {k: v for k, v in given.items() if k in slots},
        }
    if kind == "question":
        answers = scenario.get("answers") or []
        reply = (
            answers[state["answered"]]
            if state["answered"] < len(answers)
            else "기본값으로 진행해줘"
        )
        state["answered"] += 1
        fields = waiting.get("fields") or []
        return {fields[0]["key"]: reply} if len(fields) == 1 else reply
    if kind == "code_approval":
        return {"approve": True}
    return {"approve": False}  # workflow_save, memory_change


def _run_turn(s: Session, sid: str, text: str, scenario: dict, state: dict):
    run = s.c.post(f"/sessions/{sid}/runs", json={"input": {"content": text}})
    run.raise_for_status()
    run_id = run.json()["run"]["id"]
    started, cancelled = time.time(), False
    while True:
        st = s.c.get(f"/runs/{run_id}").json()
        status = st["status"]
        if scenario.get("cancel_when") == status and not cancelled:
            s.c.post(f"/runs/{run_id}/cancel")
            cancelled = True
        if status == "waiting_input":
            value = _answer(st["waiting"], scenario, state)
            s.c.post(
                f"/sessions/{sid}/runs",
                json={
                    "command": {
                        "resume": {
                            "interrupt_id": st["waiting"]["interrupt_id"],
                            "value": value,
                        }
                    }
                },
            )
        elif status in TERMINAL:
            break
        if time.time() - started > 900:
            s.c.post(f"/runs/{run_id}/cancel")
            status = "timeout"
            break
        time.sleep(2)
    return run_id, status, round(time.time() - started, 1)


def _turn_record(s: Session, sid: str, run_id: str) -> dict:
    events = s.c.get(f"/runs/{run_id}/events").json()["items"]
    calls = [e["data"]["name"] for e in events if e["type"] == "tool_call"]
    read = [
        e["data"]["args"].get("name")
        for e in events
        if e["type"] == "tool_call" and e["data"]["name"] == "read_skill"
    ]
    plan_skills, plan_tools = set(), set()
    for e in events:
        if e["type"] == "plan_approved":
            for step in e["data"]["document"]["workflow"]["steps"]:
                plan_skills.add(step["skill"])
                plan_tools.update(t["tool"] for t in step["tools"])
    reports = []
    for e in events:
        if e["type"] == "artifact" and e["data"]["kind"] == "report":
            r = s.c.get(f"/artifacts/{e['data']['artifact_id']}/content")
            if r.status_code == 200:
                reports.append(r.text)
    messages = s.c.get(f"/sessions/{sid}/messages").json()["items"]
    answer = next(
        (
            m["content"]
            for m in reversed(messages)
            if m["role"] == "assistant" and m["run_id"] == run_id
        ),
        "",
    )
    return {
        "run_id": run_id,
        "calls": calls,
        "read_skills": read,
        "plan_skills": sorted(plan_skills),
        "plan_tools": sorted(plan_tools),
        "auto_approved": any(
            e["type"] == "plan_auto_approved" for e in events
        ),
        "answer": answer,
        "report": "\n\n".join(reports),
    }


def run_scenario(s: Session, scenario: dict) -> dict:
    sid = s.new_session(f"시나리오 {scenario['id']}: {scenario['title']}")
    state = {"hitl": [], "answered": 0, "revisions": 0}
    turns, status, seconds = [], "", 0.0
    for text in scenario["turns"]:
        run_id, status, took = _run_turn(s, sid, text, scenario, state)
        seconds += took
        turns.append(_turn_record(s, sid, run_id) | {"status": status})
        if status != "succeeded":
            break
    return _score(scenario, turns, status, seconds, state, sid)


def _score(scenario, turns, status, seconds, state, sid) -> dict:
    expect = scenario.get("expect") or {}
    last = turns[-1]
    text = f"{last['answer']}\n{last['report']}"
    skills = set().union(*(t["plan_skills"] for t in turns))
    tools = set().union(*(t["plan_tools"] for t in turns))
    calls = {c for t in turns for c in t["calls"]}
    checks = {
        "status": status == expect.get("status", "succeeded"),
    }
    for fact in expect.get("facts") or []:
        checks[f"fact:{fact}"] = bool(re.search(fact, text, re.I))
    for skill in expect.get("plan_skills") or []:
        checks[f"skill:{skill}"] = skill in skills
    for tool in expect.get("plan_tools") or []:
        checks[f"tool:{tool}"] = tool in tools
    for call in expect.get("calls") or []:
        checks[f"call:{call}"] = call in calls
    if "question" in expect:
        checks["question"] = ("question" in state["hitl"]) == expect[
            "question"
        ]
    if "auto_approved" in expect:
        checks["auto_approved"] = (
            any(t["auto_approved"] for t in turns) == expect["auto_approved"]
        )
    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "session_id": sid,
        "status": status,
        "seconds": seconds,
        "passed": all(checks.values()),
        "checks": checks,
        "hitl": state["hitl"],
        "turns": turns,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--out", default="scenario-results.json")
    args = parser.parse_args()
    scenarios = yaml.safe_load(SCENARIOS.read_text("utf-8"))
    if args.ids:
        scenarios = [x for x in scenarios if x["id"] in args.ids]
    s = Session(os.environ.get("BASE_URL", "http://localhost:8080"))
    results = []
    for scenario in scenarios:
        result = run_scenario(s, scenario)
        results.append(result)
        failed = [k for k, v in result["checks"].items() if not v]
        print(
            f"{'PASS' if result['passed'] else 'FAIL'} {result['id']:<20} "
            f"{result['status']:<10} {result['seconds']:>6}s "
            f"{'missing: ' + ', '.join(failed) if failed else ''}",
            flush=True,
        )
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=1), "utf-8"
        )
    passed = sum(r["passed"] for r in results)
    print(f"{passed}/{len(results)} passed")


if __name__ == "__main__":
    main()

"""Scripted OpenAI-compatible chat server for local end-to-end runs.

Stands in for the LLM gateway.

    uv run uvicorn mock_llm:app --app-dir scripts --port 8001
    LLM_BASE_URL=http://localhost:8001/v1

It looks at the offered tools and the last message and replies with the next
step of a "load NCE -> sample -> statistics/histogram -> conditional boxplot
-> report" analysis.
It is a test double for the service plumbing, not an agent.
"""

import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads(
    (ROOT / "tests/fixtures/workflow_adaptive.example.json").read_text("utf-8")
)


def _decide(body: dict) -> tuple[str, list[dict]]:
    tools = {t["function"]["name"] for t in body.get("tools") or []}
    messages = body["messages"]
    last = messages[-1]
    content = (
        last.get("content")
        if isinstance(last.get("content"), str)
        else json.dumps(last.get("content"))
    )
    tool_name = None
    if last["role"] == "tool":
        call_id = last["tool_call_id"]
        for m in reversed(messages):
            for call in m.get("tool_calls") or []:
                if call["id"] == call_id:
                    tool_name = call["function"]["name"]

    system = str(messages[0].get("content", "")) if messages else ""
    if not tools and "프로젝트 메모리 관리자" in system:  # memory worker
        return '{"ops": []}', []
    if not tools:  # reporter
        return (
            "# 분석 리포트\n\n## 요약\n표본 통계와 분포를 확인했습니다.\n\n"
            "## 특이사항\n- (mock) 근거 기반 정리\n\n"
            "## 추가로 해볼 만한 분석\n- 공정별 비교\n- 시계열 추세",
            [],
        )
    if "start_analysis" in tools:  # main persona
        if last["role"] == "user" and "기억해" in content:
            return "", [
                _call(
                    "save_memory",
                    {
                        "topic": "preferences",
                        "text": f"- {content}",
                        "reason": "사용자 요청",
                    },
                )
            ]
        if tool_name == "save_memory":
            return "기억했습니다.", []
        if last["role"] == "user" and "분석" in content:
            return "", [
                _call(
                    "start_analysis",
                    {"task": content, "context": "NCE wide mock 데이터"},
                )
            ]
        if tool_name == "finish_analysis":
            return "분석을 마쳤습니다. 리포트와 노트북을 확인해 주세요.", []
        return (
            "안녕하세요! 데이터 분석을 도와드리는 Agent입니다. (mock LLM)",
            [],
        )
    # analyst persona
    if tool_name in (None, "start_analysis"):
        return "", [_call("read_skill", {"name": "eda_analysis"})]
    if tool_name == "read_skill":
        return "", [
            _call(
                "propose_plans",
                {
                    "candidates": [
                        {
                            "title": "NCE·WT 결합 탐색",
                            "rationale": "mock",
                            "workflow": PLAN,
                            "input_values": {
                                "0.0.data_type": "nce",
                                "0.2.data_type": "wt",
                                "0.1.transform_op": "pivot",
                                "1.0.join_columns": [
                                    "alias_lot_id",
                                    "wf_id",
                                    "x",
                                    "y",
                                ],
                                "1.1.sample_size": 500,
                            },
                        }
                    ]
                },
            )
        ]
    if tool_name == "propose_plans":
        return (
            ("", [_call("run_plan", {})])
            if "승인" in content
            else ("계획이 취소되었습니다.", [])
        )
    if tool_name == "run_plan":
        state = json.loads(content) if content.startswith("{") else {}
        if state.get("remaining_conditional_calls"):
            decisions = {
                k: {"run": True, "reason": "mock: 조건 충족"}
                for k in state["remaining_conditional_calls"]
            }
            return "", [_call("run_plan", {"decisions": decisions})]
        return "", [
            _call(
                "run_custom_code",
                {
                    "code": "print(_r_s1_t1['sampled_data'].shape)",
                    "purpose": "표본 크기 확인",
                },
            )
        ]
    if tool_name == "run_custom_code":
        return "", [
            _call(
                "write_report",
                {"title": "NCE WT 탐색 분석", "focus": "분포와 상관"},
            )
        ]
    if tool_name == "write_report":
        return "", [
            _call(
                "save_workflow",
                {
                    "name": "NCE WT 결합 탐색",
                    "user_queries": ["NCE와 WT를 결합해 탐색 분석해줘"],
                },
            )
        ]
    if tool_name == "save_workflow":
        return "", [_call("finish_analysis", {"summary": "리포트 작성 완료"})]
    return "완료했습니다.", []


def _call(name: str, args: dict) -> dict:
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }


@app.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    text, calls = _decide(body)
    base = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": body["model"],
    }

    def chunks():
        for i in range(0, len(text), 8):
            yield {
                **base,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": text[i : i + 8],
                        },
                        "finish_reason": None,
                    }
                ],
            }
        for i, call in enumerate(calls):
            yield {
                **base,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [{"index": i, **call}]},
                        "finish_reason": None,
                    }
                ],
            }
        yield {
            **base,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "tool_calls" if calls else "stop",
                }
            ],
        }

    if not body.get("stream"):
        message = {
            "role": "assistant",
            "content": text,
            **({"tool_calls": calls} if calls else {}),
        }
        return {
            **base,
            "object": "chat.completion",
            "choices": [
                {"index": 0, "message": message, "finish_reason": "stop"}
            ],
        }

    async def stream():
        for chunk in chunks():
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")

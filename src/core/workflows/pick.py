"""Which templates fit a request, when there is no embedding model.

Words of the request appearing in a template do not say it fits ("분석"
is in most of them), so the model reads every template's name, request
and example questions and names the ones that answer the request.
"""

import logging
from typing import Any

import json_repair
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

log = logging.getLogger(__name__)

# templates shown to the model at most (newest first); one call
POOL = 40
QUERIES_PER_TEMPLATE = 5

SYSTEM = (
    "당신은 데이터 분석 서비스에서 등록된 워크플로우 중 사용자 요청에 "
    "맞는 것을 고릅니다. 워크플로우마다 이름, 원래 요청, 예시 질문이 "
    "주어집니다. 요청과 분석 대상·목적이 같아서 그대로 또는 입력값만 "
    "바꿔 실행하면 요청을 해결하는 것만 고릅니다. 단어 몇 개가 겹친다고 "
    "고르지 않습니다. 맞는 것이 없으면 비워 둡니다. 잘 맞는 순서로 "
    'JSON 하나만 출력합니다: {"ids": ["<id>", ...]}'
)


def _describe(workflow: Any) -> str:
    queries = [q for q in (workflow.user_queries or []) if q]
    lines = [
        f"- id={workflow.id}",
        f"  이름: {workflow.name}",
        f"  원래 요청: {(workflow.user_request or '')[:500]}",
    ]
    if queries:
        shown = " / ".join(q[:200] for q in queries[:QUERIES_PER_TEMPLATE])
        lines.append(f"  예시 질문: {shown}")
    return "\n".join(lines)


def parse_ids(text: str) -> list[str]:
    start = text.find("{")
    if start < 0:
        return []
    try:
        value = json_repair.loads(text[start:])
    except Exception:  # noqa: BLE001
        return []
    ids = value.get("ids") if isinstance(value, dict) else None
    return [str(i) for i in ids] if isinstance(ids, list) else []


async def pick(
    model: BaseChatModel, query: str, workflows: list[Any], limit: int
) -> list[Any]:
    """The workflows the model says fit ``query``, best first."""
    if not workflows or not query.strip():
        return []
    request = f"# 사용자 요청\n{query[:2000]}\n\n# 워크플로우\n" + "\n".join(
        _describe(w) for w in workflows
    )
    response = await model.ainvoke(
        [SystemMessage(SYSTEM), HumanMessage(request)]
    )
    by_id = {w.id: w for w in workflows}
    ids = parse_ids(response.text)
    chosen: list[Any] = []
    for workflow_id in ids:
        workflow = by_id.get(workflow_id)
        if workflow is not None and workflow not in chosen:
            chosen.append(workflow)
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        log.info("workflow_pick_unknown_ids ids=%s", unknown[:10])
    return chosen[:limit]

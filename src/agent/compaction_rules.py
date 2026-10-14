"""What stays of an analysis once finish_analysis has closed it.

Kept: the hand-off (start_analysis: task and context), the analyst's
summary (finish_analysis) and the user's and main agent's messages.
Removed: every other tool call of the analysis with its result (catalog
reads, plans, executions, reports); their originals stay in the notebook,
run events, executor and catalog. The finish_analysis result gets one
line with the report/notebook ids and saved workflows instead.
"""

from collections.abc import Sequence

from langchain_core.messages import AnyMessage, ToolMessage

from agent.compaction import KEEP, REMOVE, ToolResultCompactionMiddleware

NOTE_TITLE = "[이 분석의 도구 기록은 정리됨]"
NOTED = ("리포트 게시 완료", "워크플로우 '")


def analysis_note(segment: Sequence[AnyMessage]) -> str | None:
    """Report/notebook ids and saved workflows of the analysis."""
    lines = [
        m.content.splitlines()[0]
        for m in segment
        if isinstance(m, ToolMessage)
        and isinstance(m.content, str)
        and m.content.startswith(NOTED)
    ]
    return "\n".join([NOTE_TITLE, *lines])


def finished_analysis() -> ToolResultCompactionMiddleware:
    return ToolResultCompactionMiddleware(
        start_tools={"start_analysis"},
        end_tools={"finish_analysis"},
        rules={"start_analysis": KEEP, "finish_analysis": KEEP},
        default=REMOVE,
        note=analysis_note,
    )

"""Short session titles summarised from the first exchange."""

from langchain_core.messages import HumanMessage, SystemMessage

from src.dtest.agent.llm import chat_model
from src.dtest.core.config import Settings

SYSTEM = (
    "대화 내용을 보고 채팅 목록에 표시할 제목을 만든다. "
    "한국어 명사구 하나, 25자 이내, "
    "따옴표·마침표·이모지 없이 제목만 출력한다. "
    "예: NCE 표본 기술통계·분포 분석"
)


async def summarize_title(
    settings: Settings, model: str, question: str, answer: str
) -> str | None:
    llm = chat_model(settings, model)
    response = await llm.ainvoke(
        [
            SystemMessage(SYSTEM),
            HumanMessage(
                f"사용자: {question[:1000]}\n\n답변: {answer[:1500]}"
            ),
        ]
    )
    title = (response.text).strip()
    title = (
        title.splitlines()[0].strip().strip("\"'「」『』.").strip()
        if title
        else ""
    )
    return title[:60] or None

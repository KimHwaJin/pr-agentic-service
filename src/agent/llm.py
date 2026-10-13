from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from core.config import Settings


class GatewayChatOpenAI(ChatOpenAI):
    """vLLM behind the internal gateway rejects ``tools=[]``.

    Drop the tool fields when the list is empty.
    """

    def _get_request_payload(
        self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if not payload.get("tools"):
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
            payload.pop("parallel_tool_calls", None)
        return payload


_models: dict[str, BaseChatModel] = {}


def chat_model(settings: Settings, name: str) -> BaseChatModel:
    """One client (and HTTP connection pool) per served model name.

    Shared for the whole process.
    """
    if name not in _models:
        _models[name] = _build(settings, name)
    return _models[name]


def _build(settings: Settings, name: str) -> BaseChatModel:
    extra_body: dict[str, Any] = {}
    if settings.llm_enable_thinking is not None:
        extra_body["chat_template_kwargs"] = {
            "enable_thinking": settings.llm_enable_thinking
        }
    return GatewayChatOpenAI(
        model=name,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        streaming=True,
        extra_body=extra_body or None,
    )

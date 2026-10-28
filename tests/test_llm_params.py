from src.dtest.agent.llm import request_extras
from src.dtest.api_service.schemas.users import ModelList
from src.dtest.core.config import ModelSpec, Settings


def _settings(**kwargs) -> Settings:
    return Settings(
        models=[
            ModelSpec(name="glm", default=True),
            ModelSpec(name="oss", params={"reasoning_effort": "low"}),
            ModelSpec(
                name="qwen",
                params={"chat_template_kwargs": {"enable_thinking": True}},
            ),
        ],
        **kwargs,
    )


def test_global_thinking_without_params():
    settings = _settings(llm_enable_thinking=False)
    assert request_extras(settings, "glm") == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_params_apply_to_their_model_only():
    settings = _settings(llm_enable_thinking=False)
    assert request_extras(settings, "oss") == {
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "low",
    }
    assert "reasoning_effort" not in request_extras(settings, "glm")


def test_model_params_override_global():
    settings = _settings(llm_enable_thinking=False)
    assert request_extras(settings, "qwen") == {
        "chat_template_kwargs": {"enable_thinking": True}
    }


def test_nothing_sent_by_default():
    settings = _settings(llm_enable_thinking=None)
    assert request_extras(settings, "glm") == {}
    assert request_extras(settings, "unknown") == {}


def test_params_not_exposed_to_clients():
    items = ModelList(items=_settings().models).model_dump(mode="json")
    assert all("params" not in m for m in items["items"])

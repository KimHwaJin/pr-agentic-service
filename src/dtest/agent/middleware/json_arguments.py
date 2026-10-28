import json

import json_repair
from langchain.agents.middleware import AgentMiddleware


class JsonArgumentsMiddleware(AgentMiddleware):
    """Decodes nested arguments that arrive as JSON strings.

    Some served models (vLLM tool parsers) send nested object/array
    arguments as JSON strings. Decode them before validation instead of
    letting the model retry the same call.
    """

    async def awrap_tool_call(self, request, handler):
        schema = getattr(request.tool, "tool_call_schema", None)
        properties = (
            schema.model_json_schema().get("properties", {}) if schema else {}
        )
        args = request.tool_call.get("args") or {}
        fixed = {}
        for name, value in args.items():
            if isinstance(value, str) and _structured(
                properties.get(name, {})
            ):
                try:
                    fixed[name] = json.loads(value)
                except ValueError:
                    repaired = json_repair.loads(
                        value
                    )  # unbalanced braces etc.
                    if isinstance(repaired, (dict, list)):
                        fixed[name] = repaired
        if fixed:
            request = request.override(
                tool_call={**request.tool_call, "args": {**args, **fixed}}
            )
        return await handler(request)


def _structured(prop: dict) -> bool:
    options = prop.get("anyOf", [prop])
    return any(option.get("type") in {"object", "array"} for option in options)

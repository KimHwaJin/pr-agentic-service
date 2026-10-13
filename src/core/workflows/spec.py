"""Workflow 1.0 (docs/specs/workflow-1.0).

Structural + semantic validation and call helpers.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from core.assets import SkillCatalog, ToolCatalog

_SCHEMA = Draft202012Validator(
    json.loads(
        (Path(__file__).parent / "workflow_schema_1.0.json").read_text("utf-8")
    )
)


@dataclass(frozen=True)
class Call:
    step_index: int
    tool_index: int
    skill: str
    tool: str
    execution: str
    arguments: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.step_index}.{self.tool_index}"

    @property
    def var(self) -> str:
        return f"_r_s{self.step_index}_t{self.tool_index}"


def calls(document: dict[str, Any]) -> list[Call]:
    return [
        Call(
            si,
            ti,
            step["skill"],
            tool["tool"],
            tool["execution"],
            tool.get("arguments", {}),
        )
        for si, step in enumerate(document["workflow"]["steps"])
        for ti, tool in enumerate(step["tools"])
    ]


def execution_mode(document: dict[str, Any]) -> str:
    return (
        "adaptive"
        if any(c.execution == "conditional" for c in calls(document))
        else "static"
    )


def normalize(document: dict[str, Any]) -> dict[str, Any]:
    """Server-owned field.

    execution_mode follows the tools' execution values.
    """
    document = json.loads(json.dumps(document))
    document["workflow"]["execution_mode"] = execution_mode(document)
    return document


def validate(
    document: dict[str, Any], skills: SkillCatalog, tools: ToolCatalog
) -> list[str]:
    """Returns human-readable problems; empty means valid."""
    errors = [
        f"{'/'.join(map(str, e.path)) or '$'}: {e.message}"
        for e in _SCHEMA.iter_errors(document)
    ]
    if errors:
        return errors
    seen: dict[str, Call] = {}
    for call in calls(document):
        where = f"steps[{call.step_index}].tools[{call.tool_index}]"
        skill = skills.skills.get(call.skill)
        tool = tools.tools.get(call.tool)
        if skill is None:
            errors.append(f"{where}: unknown skill '{call.skill}'")
        elif rule := next(
            (t for t in skill.tools if t.tool == call.tool), None
        ):
            if rule.execution != call.execution:
                errors.append(
                    f"{where}: '{call.tool}' must be '{rule.execution}' "
                    f"per skill '{call.skill}'"
                )
        else:
            errors.append(
                f"{where}: tool '{call.tool}' does not belong to "
                f"skill '{call.skill}'"
            )
        if tool is None:
            errors.append(f"{where}: unknown tool '{call.tool}'")
            seen[call.key] = call
            continue
        params = {p.name: p for p in tool.params}
        for name in call.arguments:
            if name not in params:
                errors.append(
                    f"{where}: '{call.tool}' has no parameter '{name}'"
                )
        for param in params.values():
            if param.required and param.name not in call.arguments:
                errors.append(
                    f"{where}: required parameter '{param.name}' is missing"
                )
        for name, arg in call.arguments.items():
            if arg["source"] != "tool_output":
                continue
            ref = seen.get(f"{arg['step_index']}.{arg['tool_index']}")
            if ref is None:
                errors.append(
                    f"{where}.{name}: tool_output must reference "
                    "an earlier call"
                )
                continue
            producer = tools.tools.get(ref.tool)
            if producer and arg["output"] not in producer.outputs:
                errors.append(
                    f"{where}.{name}: '{ref.tool}' has no output "
                    f"'{arg['output']}' ({list(producer.outputs)})"
                )
            if (
                ref.execution == "conditional"
                and call.execution != "conditional"
            ):
                errors.append(
                    f"{where}.{name}: an always-run call cannot depend on "
                    f"conditional call {ref.key}"
                )
        seen[call.key] = call
    return errors


def input_slots(
    document: dict[str, Any], tools: ToolCatalog
) -> list[dict[str, Any]]:
    """Every ``source: input`` argument.

    These are what the user (or the question) has to provide.
    """
    slots = []
    for call in calls(document):
        tool = tools.tools.get(call.tool)
        params = {p.name: p for p in tool.params} if tool else {}
        for name, arg in call.arguments.items():
            if arg["source"] == "input":
                param = params.get(name)
                slots.append(
                    {
                        "key": f"{call.key}.{name}",
                        "tool": call.tool,
                        "param": name,
                        "type": param.annotation if param else None,
                        # Workflow 1.0: source=input means the user
                        # provides the value, so it is required even when
                        # the tool itself has a default.
                        "required": True,
                    }
                )
    return slots

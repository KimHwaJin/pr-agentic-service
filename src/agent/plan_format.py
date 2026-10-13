"""Compact plan format the model writes.

The server converts it to a Workflow 1.0 document. Deeply nested Workflow
JSON is where served models break (unbalanced braces, invented keys). The
model writes a flat call list instead:

    calls = [
      {"skill": "data_load", "tool": "extract_data",
       "args": {"data_type": "$input", "limit": 5000}},
      {"skill": "data_load", "tool": "transform_nce",
       "args": {"data": "@0.data"}},
    ]

args values: "$input" (ask the user / input form), "@<call>.<output>" (an
earlier call's output), anything else is a literal. Consecutive calls of one
skill become one Workflow step; each tool's always/conditional comes from
the skill's Tool list.
"""

import json
import re
from typing import Any

from core.assets import SkillCatalog
from core.workflows import spec

_REF = re.compile(r"^@(\d+)\.([A-Za-z_][\w]*)$")
AGENT_ACTOR = {"type": "AGENT", "id": "analyst"}


class PlanFormatError(ValueError):
    pass


def to_workflow(
    calls: list[dict[str, Any]],
    *,
    name: str,
    user_request: str,
    skills: SkillCatalog,
) -> tuple[dict, list[str]]:
    """Returns (Workflow 1.0 document, call keys).

    The call keys list holds the workflow call key "<step>.<tool>" for each
    call index.
    """
    steps: list[dict[str, Any]] = []
    keys: list[str] = []
    for index, call in enumerate(calls):
        if (
            not isinstance(call, dict)
            or not call.get("skill")
            or not call.get("tool")
        ):
            raise PlanFormatError(f"calls[{index}] needs 'skill' and 'tool'")
        if not steps or steps[-1]["skill"] != call["skill"]:
            steps.append({"skill": call["skill"], "tools": []})
        skill = skills.skills.get(call["skill"])
        rule = (
            next((t for t in skill.tools if t.tool == call["tool"]), None)
            if skill
            else None
        )
        arguments = {
            param: _argument(value, index, keys, param)
            for param, value in (call.get("args") or {}).items()
        }
        steps[-1]["tools"].append(
            {
                "tool": call["tool"],
                "execution": rule.execution if rule else "always",
                "arguments": arguments,
            }
        )
        keys.append(f"{len(steps) - 1}.{len(steps[-1]['tools']) - 1}")
    document = {
        "workflow_version": "1.0",
        "workflow": {
            "actor": AGENT_ACTOR,
            "name": name,
            "user_request": user_request,
            "execution_mode": "static",
            "allow_immediate_execution": False,
            "steps": steps,
        },
    }
    return spec.normalize(document), keys


def _argument(
    value: Any, index: int, keys: list[str], param: str
) -> dict[str, Any]:
    if value == "$input":
        return {"source": "input"}
    if isinstance(value, str) and (match := _REF.match(value)):
        ref = int(match.group(1))
        if ref >= index:
            raise PlanFormatError(
                f"calls[{index}].args.{param}: "
                f"'@{ref}' must point to an earlier call"
            )
        step_index, tool_index = (int(x) for x in keys[ref].split("."))
        return {
            "source": "tool_output",
            "step_index": step_index,
            "tool_index": tool_index,
            "output": match.group(2),
        }
    return {"source": "literal", "value": value}


def input_keys(values: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Prefilled inputs "<call>.<param>" -> "<step>.<tool>.<param>"."""
    out = {}
    for key, value in values.items():
        head, _, param = key.partition(".")
        if head.isdigit() and int(head) < len(keys):
            out[f"{keys[int(head)]}.{param}"] = value
    return out


def describe(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The reverse view for the model: a template as a compact call list."""
    calls, index_of = [], {}
    for si, step in enumerate(document["workflow"]["steps"]):
        for ti, tool in enumerate(step["tools"]):
            index_of[(si, ti)] = len(calls)
            args = {}
            for param, arg in tool.get("arguments", {}).items():
                if arg["source"] == "input":
                    args[param] = "$input"
                elif arg["source"] == "tool_output":
                    ref = index_of[(arg["step_index"], arg["tool_index"])]
                    args[param] = f"@{ref}.{arg['output']}"
                else:
                    args[param] = arg["value"]
            calls.append(
                {
                    "skill": step["skill"],
                    "tool": tool["tool"],
                    "execution": tool["execution"],
                    "args": args,
                }
            )
    return calls


def apply_overrides(
    document: dict[str, Any],
    input_values: dict[str, Any],
    overrides: dict[str, Any],
) -> tuple[dict, dict]:
    """Applies user edits from the approval screen.

    An input key fills the input; any other parameter becomes a fixed value.
    """
    document = json.loads(json.dumps(document))
    values = dict(input_values)
    steps = document["workflow"]["steps"]
    for key, value in overrides.items():
        try:
            si, ti, param = key.split(".", 2)
            call = steps[int(si)]["tools"][int(ti)]
        except (ValueError, IndexError):
            continue
        arg = call.get("arguments", {}).get(param)
        if arg and arg["source"] == "input":
            values[key] = value
        elif not arg or arg["source"] == "literal":
            call.setdefault("arguments", {})[param] = {
                "source": "literal",
                "value": value,
            }
    return document, values

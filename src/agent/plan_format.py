"""Compact plan format the model writes, converted to a Workflow 1.0 document on the server.

Deeply nested Workflow JSON is where served models break (unbalanced braces, invented keys).
The model writes a flat call list instead:

    calls = [
      {"skill": "data_load", "tool": "extract_data", "args": {"data_type": "$input", "limit": 5000}},
      {"skill": "data_load", "tool": "transform_nce", "args": {"data": "@0.data"}},
    ]

args values: "$input" (ask the user / input form), "@<call>.<output>" (an earlier call's output),
anything else is a literal. Consecutive calls of one skill become one Workflow step; each tool's
always/conditional comes from the skill's Tool list.
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
    calls: list[dict[str, Any]], *, name: str, user_request: str, skills: SkillCatalog
) -> tuple[dict, list[str]]:
    """Returns (Workflow 1.0 document, workflow call key "<step>.<tool>" for each call index)."""
    steps: list[dict[str, Any]] = []
    keys: list[str] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict) or not call.get("skill") or not call.get("tool"):
            raise PlanFormatError(f"calls[{index}] needs 'skill' and 'tool'")
        if not steps or steps[-1]["skill"] != call["skill"]:
            steps.append({"skill": call["skill"], "tools": []})
        skill = skills.skills.get(call["skill"])
        rule = next((t for t in skill.tools if t.tool == call["tool"]), None) if skill else None
        arguments = {param: _argument(value, index, keys, param) for param, value in (call.get("args") or {}).items()}
        steps[-1]["tools"].append(
            {"tool": call["tool"], "execution": rule.execution if rule else "always", "arguments": arguments}
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


def _argument(value: Any, index: int, keys: list[str], param: str) -> dict[str, Any]:
    if value == "$input":
        return {"source": "input"}
    if isinstance(value, str) and (match := _REF.match(value)):
        ref = int(match.group(1))
        if ref >= index:
            raise PlanFormatError(f"calls[{index}].args.{param}: '@{ref}' must point to an earlier call")
        step_index, tool_index = (int(x) for x in keys[ref].split("."))
        return {"source": "tool_output", "step_index": step_index, "tool_index": tool_index, "output": match.group(2)}
    return {"source": "literal", "value": value}


def input_keys(values: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Prefilled inputs "<call>.<param>" -> internal "<step>.<tool>.<param>"."""
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
                    args[param] = f"@{index_of[(arg['step_index'], arg['tool_index'])]}.{arg['output']}"
                else:
                    args[param] = arg["value"]
            calls.append({"skill": step["skill"], "tool": tool["tool"], "execution": tool["execution"], "args": args})
    return calls


def review(document: dict[str, Any], input_values: dict[str, Any], skills: SkillCatalog, tools) -> list[dict[str, Any]]:
    """What the approval screen shows per call: skill, tool and every parameter with where its value comes from.

    source: literal (decided by the agent), input (the user fills it; prefilled when the request said it),
    tool_output (an earlier call's result) or default (left to the tool's default).
    """
    flat = spec.calls(document)
    number = {c.key: i for i, c in enumerate(flat)}
    views = []
    for i, call in enumerate(flat):
        tool = tools.tools.get(call.tool)
        skill = skills.skills.get(call.skill)
        rule = next((t for t in skill.tools if t.tool == call.tool), None) if skill else None
        params = []
        for p in tool.params if tool else ():
            arg = call.arguments.get(p.name)
            view = {
                "name": p.name,
                "type": p.annotation,
                "required": p.required,
                "doc": tool.param_docs.get(p.name, ""),
                "key": f"{call.key}.{p.name}",
            }
            if arg is None:
                view |= {"source": "default", "value": None, "default": p.default}
            elif arg["source"] == "literal":
                view |= {"source": "literal", "value": arg["value"]}
            elif arg["source"] == "input":
                view |= {"source": "input", "value": input_values.get(view["key"]), "required": True}
            else:
                ref = f"{arg['step_index']}.{arg['tool_index']}"
                view |= {
                    "source": "tool_output",
                    "ref": {
                        "call": number.get(ref),
                        "tool": flat[number[ref]].tool if ref in number else None,
                        "output": arg["output"],
                    },
                }
            params.append(view)
        views.append(
            {
                "index": i,
                "key": call.key,
                "skill": call.skill,
                "skill_description": skill.description if skill else "",
                "tool": call.tool,
                "summary": tool.summary if tool else "",
                "execution": call.execution,
                "condition": rule.condition if rule and call.execution == "conditional" else None,
                "params": params,
            }
        )
    return views


def apply_overrides(
    document: dict[str, Any], input_values: dict[str, Any], overrides: dict[str, Any]
) -> tuple[dict, dict]:
    """User edits on the approval screen: an input key fills the input, any other parameter becomes a fixed value."""
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
            call.setdefault("arguments", {})[param] = {"source": "literal", "value": value}
    return document, values

"""Readable views of a Workflow 1.0 document.

They are derived from the skill/tool catalogs. The stored document is never
changed; these views only add what people need to read it.
"""

from typing import Any

from core.assets import SkillCatalog, ToolCatalog
from core.workflows import spec


def steps_summary(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Skill order with the tools of each skill (for lists and cards)."""
    return [
        {
            "skill": step["skill"],
            "tools": [
                {"tool": t["tool"], "execution": t["execution"]}
                for t in step["tools"]
            ],
        }
        for step in document.get("workflow", {}).get("steps", [])
    ]


def call_views(
    document: dict[str, Any],
    input_values: dict[str, Any],
    skills: SkillCatalog,
    tools: ToolCatalog,
) -> list[dict[str, Any]]:
    """Readable view of a Workflow 1.0 document per call.

    Used by the plan approval screen and workflow detail: skill, tool and
    every parameter with where its value comes from.

    source: literal (decided by the agent), input (the user fills it;
    prefilled when the request said it), tool_output (an earlier call's
    result) or default (left to the tool's default).
    """
    flat = spec.calls(document)
    number = {c.key: i for i, c in enumerate(flat)}
    views = []
    for i, call in enumerate(flat):
        tool = tools.tools.get(call.tool)
        skill = skills.skills.get(call.skill)
        rule = (
            next((t for t in skill.tools if t.tool == call.tool), None)
            if skill
            else None
        )
        params = []
        docs = tool.param_docs if tool else {}
        for p in tool.params if tool else ():
            arg = call.arguments.get(p.name)
            view: dict[str, Any] = {
                "name": p.name,
                "type": p.annotation,
                "required": p.required,
                "doc": docs.get(p.name, ""),
                "key": f"{call.key}.{p.name}",
            }
            if arg is None:
                view |= {
                    "source": "default",
                    "value": None,
                    "default": p.default,
                }
            elif arg["source"] == "literal":
                view |= {"source": "literal", "value": arg["value"]}
            elif arg["source"] == "input":
                view |= {
                    "source": "input",
                    "value": input_values.get(view["key"]),
                    "required": True,
                }
            else:
                ref = f"{arg['step_index']}.{arg['tool_index']}"
                view |= {
                    "source": "tool_output",
                    "ref": {
                        "call": number.get(ref),
                        "tool": flat[number[ref]].tool
                        if ref in number
                        else None,
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
                "condition": rule.condition
                if rule and call.execution == "conditional"
                else None,
                "params": params,
            }
        )
    return views

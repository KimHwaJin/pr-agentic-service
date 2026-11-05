"""The analysis skills and tools a workflow can name.

The same parsed catalog the agent and workflow validation use (files under
the skill/tool roots and CATALOG_EXTENSIONS, reloaded when they change); no
database. Tool code is never returned, only signatures and docs.
"""

from typing import Any

from fastapi import APIRouter

from src.dtest.api_service.deps import ServicesDep, UserOrServiceDep
from src.dtest.api_service.errors import ApiError
from src.dtest.api_service.schemas.catalog import (
    Catalog,
    CatalogSkill,
    CatalogSkillDetail,
)
from src.dtest.core.assets import Skill, ToolCatalog

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _tool(rule, tools: ToolCatalog, detail: bool) -> dict[str, Any]:
    tool = tools.tools.get(rule.tool)
    broken = None
    docs = tool.param_docs if tool else {}
    if tool is None:
        broken = tools.broken.get(rule.tool) or "tool file not found"
    item = {
        "name": rule.tool,
        "execution": rule.execution,
        "condition": rule.condition,
        "condition_tool": rule.condition_tool,
        "role": rule.role,
        "summary": tool.summary if tool else "",
        "signature": tool.signature if tool else None,
        "params": [
            {
                "name": p.name,
                "type": p.annotation,
                "required": p.required,
                "default": p.default,
                "doc": docs.get(p.name, ""),
            }
            for p in (tool.params if tool else ())
        ],
        "outputs": list(tool.outputs) if tool else [],
        "broken": broken,
    }
    if detail:
        item["docstring"] = tool.docstring if tool else ""
    return item


def _skill(skill: Skill, tools: ToolCatalog, detail: bool) -> dict[str, Any]:
    item = {
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "tools": [_tool(r, tools, detail) for r in skill.tools],
    }
    if detail:
        item["body"] = skill.body
    return item


def _matches(skill: dict[str, Any], q: str) -> bool:
    text = " ".join(
        [skill["name"], skill["description"]]
        + [f"{t['name']} {t['summary']} {t['role']}" for t in skill["tools"]]
    )
    return q.lower() in text.lower()


@router.get("", response_model=Catalog)
async def get_catalog(
    services: ServicesDep, _user: UserOrServiceDep, q: str | None = None
):
    """Every analysis skill with its tools in full: how each tool runs
    (always/conditional), its parameters and its output names.

    ``q`` keeps the skills whose name, description, or one of whose tools
    (name, summary, role) contains it.
    """
    tools = services.tool_catalog()
    skills = [
        _skill(s, tools, False)
        for s in sorted(
            services.skills("analysis").skills.values(), key=lambda s: s.name
        )
    ]
    if q and q.strip():
        skills = [s for s in skills if _matches(s, q.strip())]
    return Catalog(skills=[CatalogSkill.model_validate(s) for s in skills])


@router.get("/skills/{name}", response_model=CatalogSkillDetail)
async def get_catalog_skill(
    name: str, services: ServicesDep, _user: UserOrServiceDep
):
    """One skill with its markdown body and each tool's full docstring."""
    skill = services.skills("analysis").skills.get(name)
    if skill is None:
        raise ApiError(404, "not_found", f"skill '{name}' not found")
    return CatalogSkillDetail.model_validate(
        _skill(skill, services.tool_catalog(), True)
    )

"""The analysis skills and tools a workflow can name.

The same parsed catalog the agent and workflow validation use (files under
the skill/tool roots and CATALOG_EXTENSIONS, reloaded when they change); no
database. Lists are light and paged so the catalog can grow to any size;
details come one skill or tool at a time. Tool code is never returned.
"""

import base64
from typing import Any

from fastapi import APIRouter, HTTPException

from api_service import pagination
from api_service.deps import ServicesDep, UserOrServiceDep
from api_service.errors import ApiError
from api_service.schemas.catalog import (
    CatalogSkillDetail,
    CatalogSkillPage,
    CatalogToolDetail,
    CatalogToolPage,
)
from core.assets import Skill, SkillTool, ToolCatalog

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _encode(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode()).decode()


def _decode(cursor: str | None) -> str | None:
    if not cursor:
        return None
    try:
        key = base64.b64decode(cursor, altchars=b"-_", validate=True)
        if not key:
            raise ValueError(cursor)
        return key.decode()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "Invalid cursor.") from None


def _page(rows: list[tuple[str, Any]], cursor: str | None, limit: int):
    """rows: (sort key, item) in key order; keyset after the cursor."""
    after = _decode(cursor)
    rest = [r for r in rows if after is None or r[0] > after]
    page = rest[:limit]
    more = len(rest) > limit
    return [item for _, item in page], _encode(page[-1][0]) if more else None


def _has(q: str | None, *texts: str) -> bool:
    return not q or q.lower() in " ".join(texts).lower()


def _skills(services) -> list[Skill]:
    return sorted(
        services.skills("analysis").skills.values(), key=lambda s: s.name
    )


def _skill(skill: Skill) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "tool_count": len(skill.tools),
    }


def _tool(skill: Skill, rule: SkillTool, tools: ToolCatalog) -> dict:
    tool = tools.tools.get(rule.tool)
    return {
        "skill": skill.name,
        "name": rule.tool,
        "execution": rule.execution,
        "summary": tool.summary if tool else "",
        "role": rule.role,
        "outputs": list(tool.outputs) if tool else [],
        "broken": None
        if tool
        else tools.broken.get(rule.tool) or "tool file not found",
    }


@router.get("/skills", response_model=CatalogSkillPage)
async def list_catalog_skills(
    services: ServicesDep,
    _user: UserOrServiceDep,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = pagination.Limit,
):
    """Analysis skills by name: name, description and tool count.

    ``q`` matches the skill's name or description.
    """
    q = (q or "").strip()
    rows = [
        (s.name, _skill(s))
        for s in _skills(services)
        if _has(q, s.name, s.description)
    ]
    items, next_cursor = _page(rows, cursor, limit)
    return {"items": items, "next_cursor": next_cursor}


@router.get("/tools", response_model=CatalogToolPage)
async def list_catalog_tools(
    services: ServicesDep,
    _user: UserOrServiceDep,
    skill: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = pagination.Limit,
):
    """Tools as the skills list them, each with its skill.

    ``skill``: that skill's tools in its table order. Without it, every
    skill's (by skill name), so ``q`` searches tools across skills; ``q``
    matches the tool's name, first docstring line or role.
    """
    q = (q or "").strip()
    tools = services.tool_catalog()
    skills = _skills(services)
    if skill is not None:
        skills = [s for s in skills if s.name == skill]
        if not skills:
            raise ApiError(404, "not_found", f"skill '{skill}' not found")
    rows = []
    for s in skills:
        for i, rule in enumerate(s.tools):
            item = _tool(s, rule, tools)
            if _has(q, item["name"], item["summary"], item["role"]):
                # skill names sort; the index keeps the table order
                rows.append((f"{s.name}\t{i:06d}", item))
    items, next_cursor = _page(rows, cursor, limit)
    return {"items": items, "next_cursor": next_cursor}


@router.get("/skills/{name}", response_model=CatalogSkillDetail)
async def get_catalog_skill(
    name: str, services: ServicesDep, _user: UserOrServiceDep
):
    """One skill with its markdown body (its tools: /catalog/tools)."""
    skill = services.skills("analysis").skills.get(name)
    if skill is None:
        raise ApiError(404, "not_found", f"skill '{name}' not found")
    return {**_skill(skill), "body": skill.body}


@router.get("/tools/{name}", response_model=CatalogToolDetail)
async def get_catalog_tool(
    name: str,
    skill: str,
    services: ServicesDep,
    _user: UserOrServiceDep,
):
    """One tool as ``skill`` lists it: run rule and condition, parameters
    (required, default, doc), outputs and the full docstring."""
    found = services.skills("analysis").skills.get(skill)
    rule = (
        next((r for r in found.tools if r.tool == name), None)
        if found
        else None
    )
    if found is None or rule is None:
        raise ApiError(
            404, "not_found", f"tool '{name}' not found in skill '{skill}'"
        )
    tools = services.tool_catalog()
    tool = tools.tools.get(name)
    docs = tool.param_docs if tool else {}
    return {
        **_tool(found, rule, tools),
        "condition": rule.condition,
        "condition_tool": rule.condition_tool,
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
        "docstring": tool.docstring if tool else "",
    }

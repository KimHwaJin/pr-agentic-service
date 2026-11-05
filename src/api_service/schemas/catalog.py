"""Analysis skills and tools a workflow can use (read-only)."""

from pydantic import Field

from api_service.schemas.base import Model


class CatalogParam(Model):
    name: str
    type: str | None = Field(description="type hint as written, if any")
    required: bool = Field(description="no default: a workflow must set it")
    default: str | None = Field(description="the default, as source text")
    doc: str = Field(description="the docstring's Args line")


class CatalogTool(Model):
    name: str = Field(description="tools[].tool")
    execution: str = Field(description="tools[].execution: always|conditional")
    condition: str = Field(description="when it runs (the skill's table)")
    condition_tool: str | None
    role: str
    summary: str = Field(description="first docstring line")
    signature: str | None
    params: list[CatalogParam]
    outputs: list[str] = Field(description="names for tool_output.output")
    broken: str | None = Field(
        description="why the tool cannot be used (missing or failing file)"
    )


class CatalogSkill(Model):
    name: str = Field(description="steps[].skill")
    description: str
    category: str
    tools: list[CatalogTool]


class Catalog(Model):
    skills: list[CatalogSkill]


class CatalogToolDetail(CatalogTool):
    docstring: str


class CatalogSkillDetail(CatalogSkill):
    body: str = Field(description="the skill's markdown, frontmatter removed")
    tools: list[CatalogToolDetail]  # type: ignore[assignment]

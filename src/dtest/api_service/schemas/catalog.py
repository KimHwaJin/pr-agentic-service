"""Analysis skills and tools a workflow can use (read-only)."""

from pydantic import Field

from src.dtest.api_service.schemas.base import Model


class CatalogSkill(Model):
    name: str = Field(description="steps[].skill")
    description: str
    category: str
    tool_count: int


class CatalogSkillPage(Model):
    items: list[CatalogSkill]
    next_cursor: str | None


class CatalogTool(Model):
    """A tool as one skill lists it (its run rule comes from that skill)."""

    skill: str = Field(description="steps[].skill")
    name: str = Field(description="tools[].tool")
    execution: str = Field(description="tools[].execution: always|conditional")
    summary: str = Field(description="first docstring line")
    role: str
    outputs: list[str] = Field(description="names for tool_output.output")
    broken: str | None = Field(
        description="why the tool cannot be used (missing or failing file)"
    )


class CatalogToolPage(Model):
    items: list[CatalogTool]
    next_cursor: str | None


class CatalogParam(Model):
    name: str
    type: str | None = Field(description="type hint as written, if any")
    required: bool = Field(description="no default: a workflow must set it")
    default: str | None = Field(description="the default, as source text")
    doc: str = Field(description="the docstring's Args line")


class CatalogToolDetail(CatalogTool):
    condition: str = Field(description="when it runs (the skill's table)")
    condition_tool: str | None
    signature: str | None
    params: list[CatalogParam]
    docstring: str


class CatalogSkillDetail(CatalogSkill):
    body: str = Field(description="the skill's markdown, frontmatter removed")

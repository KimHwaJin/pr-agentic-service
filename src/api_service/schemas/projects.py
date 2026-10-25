"""Projects and project memory."""

from datetime import datetime

from pydantic import Field, computed_field

from api_service.schemas.base import Model
from core.config import get_settings
from core.memory.service import Category


class ProjectCreate(Model):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    system_prompt: str = Field("", max_length=8000)
    code_level: int | None = Field(None, ge=1, le=4)


class ProjectUpdate(Model):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = Field(None, max_length=8000)
    code_level: int | None = Field(None, ge=1, le=4)


class ProjectRead(Model):
    id: str
    name: str
    description: str
    system_prompt: str
    code_level: int | None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def effective_code_level(self) -> int:
        """The level that applies: this project's, else the service default."""
        return self.code_level or get_settings().default_code_level


class MemoryCreate(Model):
    category: Category
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class MemoryUpdate(Model):
    expected_version: int
    category: Category | None = None
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = Field(None, min_length=1)

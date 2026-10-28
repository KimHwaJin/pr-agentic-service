"""Users, the signed-in user and the model catalog."""

from typing import Literal

from src.dtest.api_service.schemas.base import Model
from src.dtest.core.config import ModelSpec


class UserRead(Model):
    id: str
    employee_id: str
    name: str
    english_name: str | None
    department: str | None
    email: str | None
    role: str
    is_active: bool


class UserBrief(Model):
    """Who an id is, for pages that show user ids (executions)."""

    id: str
    employee_id: str
    name: str
    department: str | None


class ModelList(Model):
    items: list[ModelSpec]


class Me(Model):
    user: UserRead
    default_project_id: str | None
    # local dev login only: POST /auth/dev/role switches user <-> admin
    can_switch_role: bool = False


class UserAdminUpdate(Model):
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None

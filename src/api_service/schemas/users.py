"""Users, the signed-in user and the model catalog."""

from typing import Literal

from pydantic import Field

from api_service.schemas.base import Model
from core.config import ModelSpec


class UserRead(Model):
    id: str
    employee_id: str
    name: str
    english_name: str | None
    department: str | None
    email: str | None
    role: str
    is_active: bool


class AdminUserRead(UserRead):
    """The admin user list: a deactivated user's batches not yet turned
    off at pr-batch (the worker retries until it hears)."""

    batches_disable_pending: bool = False


class UserBrief(Model):
    """Who an id is, for pages that show user ids (executions)."""

    id: str
    employee_id: str
    name: str
    department: str | None


class ModelList(Model):
    items: list[ModelSpec]


class MePermissions(Model):
    """What this login may open; a client shows menus and tabs by these."""

    system: bool = Field(
        False, description="시스템 화면 (관리자 API: 사용자, runtime, 정비)"
    )
    all_executions: bool = Field(
        False, description="모든 사용자의 실행 보기 (사용자 필터)"
    )
    execution_internals: bool = Field(
        False, description="실행의 진단·시도(attempts) 탭"
    )


class Me(Model):
    user: UserRead
    default_project_id: str | None
    # local dev login only: POST /auth/dev/role switches user <-> admin
    can_switch_role: bool = False
    permissions: MePermissions = Field(default_factory=MePermissions)


class UserAdminUpdate(Model):
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None

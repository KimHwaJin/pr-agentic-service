import importlib
from functools import partial
from typing import Protocol

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from src.dtest.api_service.auth.sdk import (
    Employee,
    SdkFactory,
    login_url,
    verify_employee,
)
from src.dtest.core.config import Settings


class SsoAdapter(Protocol):
    async def verify(self, request: Request) -> Employee | None: ...

    async def login_url(self, request: Request, callback_url: str) -> str: ...


class CompanyAdapter:
    """Runs the synchronous corporate SDK in a thread pool."""

    def __init__(self, sdk_factory: SdkFactory):
        self._verify = partial(verify_employee, sdk_factory)
        self._login_url = partial(login_url, sdk_factory)

    async def verify(self, request: Request) -> Employee | None:
        return await run_in_threadpool(self._verify, request)

    async def login_url(self, request: Request, callback_url: str) -> str:
        return await run_in_threadpool(self._login_url, request, callback_url)


class DevAdapter:
    """Local development only (guarded by Settings).

    Every visitor is the dev employee.
    """

    def __init__(self, settings: Settings):
        self.employee = Employee(
            settings.dev_employee_id, settings.dev_employee_name
        )

    async def verify(self, request: Request) -> Employee | None:
        return self.employee

    async def login_url(self, request: Request, callback_url: str) -> str:
        return callback_url


def load_adapter(settings: Settings) -> SsoAdapter:
    if settings.sso_adapter == "dev":
        return DevAdapter(settings)
    if not settings.sso_adapter_factory:
        raise ValueError(
            "SSO_ADAPTER_FACTORY (module:function) is required for "
            "SSO_ADAPTER=company"
        )
    module, name = settings.sso_adapter_factory.split(":", 1)
    sdk_factory: SdkFactory = getattr(importlib.import_module(module), name)
    return CompanyAdapter(sdk_factory)

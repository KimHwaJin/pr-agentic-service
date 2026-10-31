"""Artifact lookups answer 404/502, never 500."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException

from src.dtest.api_service.errors import ApiError
from src.dtest.api_service.services.access import owned_artifact
from src.dtest.core.executor.client import ExecutorError


def _services(artifact=None, error=None):
    async def get_artifact(artifact_id):
        if error:
            raise error
        return artifact

    executor = SimpleNamespace(artifact=get_artifact)
    return cast(Any, SimpleNamespace(executor=executor))


def _call(services):
    return asyncio.run(owned_artifact(services, SimpleNamespace(id="u"), "a1"))


def test_an_artifact_without_its_execution_is_not_found():
    with pytest.raises(HTTPException) as missing:
        _call(_services(artifact={"artifact_id": "a1"}))
    assert missing.value.status_code == 404


@pytest.mark.parametrize(
    "error", [ExecutorError(503, "down"), httpx.ConnectError("refused")]
)
def test_an_unreachable_executor_is_a_502(error):
    with pytest.raises(ApiError) as down:
        _call(_services(error=error))
    assert down.value.status == 502

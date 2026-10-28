import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from src.dtest.api_service.routers import workflows
from src.dtest.api_service.schemas.workflows import WorkflowUpdate
from src.dtest.core.workflows.service import WorkflowError

USER = cast(Any, SimpleNamespace(id="u-1", role="user"))


class _Workflows:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    async def update(self, workflow_id, user_id, *, expected_revision, **ch):
        self.calls.append((workflow_id, user_id, expected_revision, ch))
        if self.error:
            raise self.error
        return SimpleNamespace(id=workflow_id)


def _update(monkeypatch, body: dict, error=None):
    validated = []

    def validate(services, document):
        validated.append(document)
        return {**document, "checked": True}

    monkeypatch.setattr(workflows, "_validated", validate)
    service = _Workflows(error)
    services = cast(Any, SimpleNamespace(workflows=service))
    result = asyncio.run(
        workflows.update_workflow(
            "w-1", WorkflowUpdate.model_validate(body), services, USER
        )
    )
    return result, service.calls, validated


def test_only_sent_fields_change(monkeypatch):
    _, calls, validated = _update(
        monkeypatch, {"expected_revision": 3, "tags": ["a"]}
    )
    assert calls == [("w-1", "u-1", 3, {"tags": ["a"]})]
    assert validated == []  # no document, nothing to validate


def test_a_new_document_is_validated_first(monkeypatch):
    _, calls, validated = _update(
        monkeypatch,
        {"expected_revision": 1, "document": {"workflow": {"name": "n"}}},
    )
    assert validated == [{"workflow": {"name": "n"}}]
    assert calls[0][3]["document"]["checked"] is True


@pytest.mark.parametrize("status", [403, 404, 409])
def test_service_refusals_keep_their_status(monkeypatch, status):
    with pytest.raises(HTTPException) as refused:
        _update(
            monkeypatch,
            {"expected_revision": 1, "tags": []},
            WorkflowError(status, "no"),
        )
    assert refused.value.status_code == status


def test_validation_errors_are_listed():
    error = workflows._error(WorkflowError(422, "invalid", ["a", "b"]))
    assert error.detail == {"message": "invalid", "errors": ["a", "b"]}

"""Small guards: SSE cursors and models removed while a run waited."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from api_service.sse import event_stream
from core.config import Settings
from worker.scheduler import RunScheduler


def test_a_non_numeric_last_event_id_is_refused_up_front():
    events = SimpleNamespace(listen_to=lambda channel: pytest.fail("listened"))
    with pytest.raises(HTTPException) as refused:
        event_stream(
            cast(Any, None), cast(Any, events), "c", cast(Any, None), "abc"
        )
    assert refused.value.status_code == 422


def test_a_removed_model_falls_back_to_the_default():
    settings = Settings()
    rows = {
        "session": SimpleNamespace(code_level=None),
        "project": SimpleNamespace(code_level=None, system_prompt=None),
    }

    async def get_row(db, model, row_id):
        return rows[
            "session" if model.__name__ == "ChatSession" else "project"
        ]

    class Db:
        def sessions(self):
            class Ctx:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, *exc):
                    return None

            return Ctx()

    import worker.scheduler as module

    services = SimpleNamespace(settings=settings, db=Db())
    scheduler = RunScheduler(cast(Any, services), cast(Any, None), "pod")
    run = SimpleNamespace(
        id="r1",
        session_id="s1",
        project_id="p1",
        user_id="u1",
        model="gone-model",
        input={"text": "hi"},
    )
    original = module.get_row
    module.get_row = get_row
    try:
        ctx = asyncio.run(scheduler._context(cast(Any, run)))
    finally:
        module.get_row = original
    assert ctx.model == settings.default_model.name

"""psycopg needs a selector loop; uvicorn picks Proactor on Windows."""

import asyncio
import sys

import uvicorn
import uvicorn.loops.asyncio as loops

from src.dtest import winloop


def test_uvicorn_gets_the_selector_loop_on_windows(monkeypatch):
    policies = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        loops, "asyncio_loop_factory", loops.asyncio_loop_factory
    )
    monkeypatch.setattr(
        asyncio,
        "WindowsSelectorEventLoopPolicy",
        lambda: "selector",
        raising=False,
    )
    monkeypatch.setattr(asyncio, "set_event_loop_policy", policies.append)
    monkeypatch.setitem(sys.modules, "uvloop", None)  # not on Windows
    winloop.use_selector_loop()
    assert policies == ["selector"]
    for loop in ("auto", "asyncio"):
        config = uvicorn.Config(lambda scope, receive, send: None, loop=loop)
        assert config.get_loop_factory() is asyncio.SelectorEventLoop


def test_nothing_changes_elsewhere(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    before = loops.asyncio_loop_factory
    winloop.use_selector_loop()
    assert loops.asyncio_loop_factory is before

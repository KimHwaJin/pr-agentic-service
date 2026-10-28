"""Selector event loop on Windows.

psycopg's async connections (the pool and SQLAlchemy's async engine) do not
run on the ProactorEventLoop, Windows' default, and uvicorn 0.36+ picks
Proactor on Windows itself (``uvicorn.loops.asyncio``), ignoring the event
loop policy. The gaia template calls ``uvicorn.run()`` without a ``loop``
argument, so ``use_selector_loop()`` must run before that call: ``attach``
does it. Elsewhere it does nothing (Linux containers use selectors anyway).
"""

import asyncio
import sys


def use_selector_loop() -> None:
    if sys.platform != "win32":
        return
    # plain asyncio.run and uvicorn before 0.36 follow the policy
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        import uvicorn.loops.asyncio as loops
    except ImportError:
        return

    # uvicorn looks this up when it starts (loop "auto" and "asyncio")
    def selector_loop_factory(use_subprocess: bool = False):
        return asyncio.SelectorEventLoop

    loops.asyncio_loop_factory = selector_loop_factory

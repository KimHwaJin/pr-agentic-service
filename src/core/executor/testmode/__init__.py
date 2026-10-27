"""Executor I/O without a shared PV (``EXECUTOR_IO_MODE=api``).

FOR TEST ENVIRONMENTS ONLY; production runs with the shared PV ("pv",
the default) and never loads this package. It exists for setups where the
executor runs elsewhere (Kubernetes) and this service cannot mount its
volumes (a developer's machine):

- ``InlineExecutorClient`` sends each PATH step as an INLINE source read
  from this service's own copy of the file, so the executor never looks
  for it on its input volume.
- ``NotebookResultStorage`` reads step outputs and code from the
  executor notebook API instead of the result volume.

Code files, ``code_sources`` rows, linking and purging stay as they are.
Not covered: chat images (the session outputs route still reads the
volume).

Removal: delete this package and ``tests/testmode/``, the
``executor_io_mode`` setting in core/config.py and its branch in
core/bootstrap.py.
"""

from core.config import Settings
from core.executor.testmode.client import InlineExecutorClient
from core.executor.testmode.storage import NotebookResultStorage

__all__ = ["InlineExecutorClient", "NotebookResultStorage", "build"]


def build(
    settings: Settings,
) -> tuple[InlineExecutorClient, NotebookResultStorage]:
    """The executor client and storage of ``EXECUTOR_IO_MODE=api``."""
    storage = NotebookResultStorage(
        settings.storage_root,
        settings.storage_executor_path,
        settings.executor_result_root,
        base_url=settings.executor_base_url,
        timeout=settings.executor_timeout_seconds,
    )
    client = InlineExecutorClient(
        settings.executor_base_url,
        settings.executor_timeout_seconds,
        settings.executor_tenant_id,
        storage,
    )
    return client, storage

"""Links that open executor results in the team's JupyterLab server.

JupyterLab URL layout: ``{base}/lab/workspaces/{workspace}/tree/{path}``.
Each user gets their own named workspace so opening a notebook never
rearranges someone else's Lab layout.
``relative_path`` is the artifact's path on the Jupyter shared storage
(executor ``storage.relative_path``).
"""

import re
from urllib.parse import quote

from src.dtest.core.config import Settings


def lab_url(
    settings: Settings, relative_path: str | None, user_id: str
) -> str | None:
    if not settings.notebook_lab_base_url or not relative_path:
        return None
    workspace = re.sub(
        r"[^A-Za-z0-9_-]",
        "-",
        f"{settings.notebook_lab_workspace_prefix}{user_id}",
    )
    path = "/".join(
        p
        for p in (
            settings.notebook_lab_path_prefix.strip("/"),
            relative_path.lstrip("/"),
        )
        if p
    )
    base = settings.notebook_lab_base_url.rstrip("/")
    return f"{base}/lab/workspaces/{workspace}/tree/{quote(path)}"

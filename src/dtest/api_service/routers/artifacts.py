"""Executor artifacts (report .md, notebook .ipynb) for the frontend.

Proxy + landing page.
"""

import json
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

from src.dtest.api_service.deps import ServicesDep, UserDep
from src.dtest.api_service.services.access import owned_artifact
from src.dtest.core.notebook_links import lab_url

router = APIRouter(tags=["artifacts"])


@router.get("/api/v1/artifacts/{artifact_id}")
async def artifact_detail(
    artifact_id: str, services: ServicesDep, user: UserDep
):
    """Executor artifact metadata plus ``view_url`` (rendered page).

    For notebooks also ``lab_url`` (open in JupyterLab).
    """
    artifact = await owned_artifact(services, user, artifact_id)
    return {
        **artifact,
        "view_url": f"/view/artifacts/{artifact_id}",
        "lab_url": _lab_url(services, user, artifact),
    }


def _lab_url(services, user, artifact: dict) -> str | None:
    if artifact["type"] != "NOTEBOOK":
        return None
    return lab_url(
        services.settings,
        artifact["storage"].get("relative_path"),
        user.id,
    )


@router.get("/api/v1/artifacts/{artifact_id}/content")
async def artifact_content(
    artifact_id: str, services: ServicesDep, user: UserDep
):
    artifact = await owned_artifact(services, user, artifact_id)
    response, body = await services.executor.stream_artifact(artifact_id)
    media = artifact["storage"].get("media_type") or response.headers.get(
        "content-type", "application/octet-stream"
    )

    async def relay():
        try:
            async for chunk in body:
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        relay(),
        media_type=media,
        headers={
            "Content-Disposition": content_disposition(
                "inline"
                if media.split(";")[0] in INLINE_TYPES
                else "attachment",
                artifact["name"],
            ),
            # analysis output is untrusted: never sniffed, never scripted on
            # this origin (an html or svg file cannot run with our cookie)
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


# shown in the browser; anything else (html, svg, ...) is downloaded
INLINE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/csv",
    "text/markdown",
    "application/json",
    "application/x-ipynb+json",
}


def content_disposition(kind: str, name: str) -> str:
    """RFC 6266 header; ``filename*`` carries non-ASCII (Korean) names."""
    fallback = name.encode("ascii", "replace").decode().replace('"', "_")
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"


@router.get("/view/artifacts/{artifact_id}", response_class=HTMLResponse)
async def artifact_view(
    artifact_id: str, services: ServicesDep, user: UserDep
):
    """Landing page linked from chat and the system view.

    Renders reports (.md), notebooks, images, CSV tables and text files;
    anything else gets a download link.
    """
    artifact = await owned_artifact(services, user, artifact_id)
    kind = _view_kind(artifact)
    lab = _lab_url(services, user, artifact)
    lab_button = (
        '<a class="btn primary" target="_blank" rel="noopener" '
        f'href="{escape(lab)}">JupyterLab에서 열기</a>'
        if lab
        else ""
    )
    return render_view(
        title=(artifact.get("metadata") or {}).get("title")
        or artifact["name"],
        badge=artifact["type"],
        lab_button=lab_button,
        content=f"/api/v1/artifacts/{escape(artifact_id)}/content",
        kind=kind,
    )


def render_view(
    *,
    title: str,
    badge: str,
    content: str,
    kind: str,
    lab_button: str = "",
    cells: list[dict] | None = None,
) -> str:
    """The landing page for one file.

    ``content`` is where the page fetches it from. ``cells`` (batch scripts
    only) marks each notebook cell as a Step or skipped.
    """
    marks = json.dumps(cells).replace("<", "\\u003c") if cells else "null"
    return (
        VIEW.replace("__TITLE__", escape(title))
        .replace("__BADGE__", escape(badge))
        .replace("__LAB__", lab_button)
        .replace("__CONTENT__", content)
        .replace("__KIND__", kind)
        .replace("__CELLS__", marks)
    )


def _view_kind(artifact: dict) -> str:
    """How the landing page draws it: by media type, then file name."""
    media = (artifact.get("storage") or {}).get("media_type") or ""
    name = artifact.get("name", "").lower()
    if artifact["type"] == "NOTEBOOK" or name.endswith(".ipynb"):
        return "notebook"
    if media.startswith("image/") or name.endswith(IMAGE_SUFFIXES):
        return "image"
    if media == "text/csv" or name.endswith((".csv", ".tsv")):
        return "csv"
    if media == "text/markdown" or name.endswith(".md"):
        return "markdown"
    if (
        media.startswith("text/")
        or media == "application/json"
        or (name.endswith((".txt", ".log", ".json", ".py")))
    ):
        return "text"
    return "download"


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


VIEW = (
    Path(__file__).parent.parent / "templates" / "artifact_view.html"
).read_text(encoding="utf-8")

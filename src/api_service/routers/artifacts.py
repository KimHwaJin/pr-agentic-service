"""Executor artifacts (report .md, notebook .ipynb) for the frontend.

Proxy + landing page.
"""

from html import escape
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

from api_service.deps import ServicesDep, UserDep
from api_service.services.access import owned_artifact
from core.notebook_links import lab_url

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
            "Content-Disposition": f'inline; filename="{artifact["name"]}"'
        },
    )


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
    return (
        VIEW.replace(
            "__TITLE__",
            escape(
                (artifact.get("metadata") or {}).get("title")
                or artifact["name"]
            ),
        )
        .replace("__BADGE__", escape(artifact["type"]))
        .replace("__LAB__", lab_button)
        .replace("__ID__", escape(artifact_id))
        .replace("__KIND__", kind)
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

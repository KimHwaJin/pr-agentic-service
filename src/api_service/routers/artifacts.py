"""Executor artifacts (report .md, notebook .ipynb) for the frontend.

Proxy + landing page.
"""

from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from api_service.deps import ServicesDep, UserDep, session_for
from core.executor.client import ExecutorError
from core.notebook_links import lab_url

router = APIRouter(tags=["artifacts"])


async def _owned_artifact(services, user, artifact_id: str) -> dict:
    try:
        artifact = await services.executor.artifact(artifact_id)
        execution = await services.executor.get(
            artifact["produced_by"]["execution_id"]
        )
    except ExecutorError:
        raise HTTPException(404, "Artifact not found.") from None
    session_id = execution["context"].get("session_id")
    if not session_id:
        raise HTTPException(404, "Artifact not found.")
    await session_for(services, user, session_id)
    return artifact


@router.get("/api/v1/artifacts/{artifact_id}")
async def artifact_detail(
    artifact_id: str, services: ServicesDep, user: UserDep
):
    """Executor artifact metadata plus ``view_url`` (rendered page).

    For notebooks also ``lab_url`` (open in JupyterLab).
    """
    artifact = await _owned_artifact(services, user, artifact_id)
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
        user.employee_id,
    )


@router.get("/api/v1/artifacts/{artifact_id}/content")
async def artifact_content(
    artifact_id: str, services: ServicesDep, user: UserDep
):
    artifact = await _owned_artifact(services, user, artifact_id)
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
    """Landing page linked from chat.

    Renders a report (.md) or a notebook (.ipynb).
    """
    artifact = await _owned_artifact(services, user, artifact_id)
    notebook = artifact["type"] == "NOTEBOOK"
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
        .replace("__BADGE__", "NOTEBOOK" if notebook else "REPORT")
        .replace("__LAB__", lab_button)
        .replace("__ID__", escape(artifact_id))
        .replace("__KIND__", "notebook" if notebook else "markdown")
    )


VIEW = (
    Path(__file__).parent.parent / "templates" / "artifact_view.html"
).read_text(encoding="utf-8")

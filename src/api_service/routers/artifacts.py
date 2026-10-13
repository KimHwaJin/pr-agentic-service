"""Executor artifacts (report .md, notebook .ipynb) for the frontend: proxy + landing page."""

from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from api_service.deps import ServicesDep, UserDep, session_for
from core.executor.client import ExecutorError
from core.notebook_links import lab_url

router = APIRouter(tags=["artifacts"])


async def _owned_artifact(services, user, artifact_id: str) -> dict:
    try:
        artifact = await services.executor.artifact(artifact_id)
        execution = await services.executor.get(artifact["produced_by"]["execution_id"])
    except ExecutorError:
        raise HTTPException(404, "Artifact not found.") from None
    session_id = execution["context"].get("session_id")
    if not session_id:
        raise HTTPException(404, "Artifact not found.")
    await session_for(services, user, session_id)
    return artifact


@router.get("/api/v1/artifacts/{artifact_id}")
async def artifact_detail(artifact_id: str, services: ServicesDep, user: UserDep):
    """Executor artifact metadata plus ``view_url`` (rendered page) and ``lab_url`` (open in JupyterLab)."""
    artifact = await _owned_artifact(services, user, artifact_id)
    return {
        **artifact,
        "view_url": f"/view/artifacts/{artifact_id}",
        "lab_url": lab_url(services.settings, artifact["storage"].get("relative_path"), user.employee_id),
    }


@router.get("/api/v1/artifacts/{artifact_id}/content")
async def artifact_content(artifact_id: str, services: ServicesDep, user: UserDep):
    artifact = await _owned_artifact(services, user, artifact_id)
    response, body = await services.executor.stream_artifact(artifact_id)
    media = artifact["storage"].get("media_type") or response.headers.get("content-type", "application/octet-stream")

    async def relay():
        try:
            async for chunk in body:
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        relay(), media_type=media, headers={"Content-Disposition": f'inline; filename="{artifact["name"]}"'}
    )


@router.get("/view/artifacts/{artifact_id}", response_class=HTMLResponse)
async def artifact_view(artifact_id: str, services: ServicesDep, user: UserDep):
    """Landing page linked from chat: renders a report (.md) or a notebook (.ipynb)."""
    artifact = await _owned_artifact(services, user, artifact_id)
    kind = "notebook" if artifact["type"] == "NOTEBOOK" else "markdown"
    return (
        VIEW.replace("__TITLE__", escape(artifact["name"]))
        .replace("__ID__", escape(artifact_id))
        .replace("__KIND__", kind)
    )


VIEW = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<style>body{font-family:system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;line-height:1.6;color:#1f2328}
pre{background:#f6f8fa;padding:12px;overflow:auto;border-radius:6px}table{border-collapse:collapse}td,th{border:1px solid #d0d7de;padding:4px 8px}
.cell{margin:16px 0}.out{border-left:3px solid #d0d7de;padding-left:12px}img{max-width:100%}.bar a{margin-right:12px}</style></head>
<body><div class="bar"><a href="/api/v1/artifacts/__ID__/content" download>다운로드</a></div><h1>__TITLE__</h1><div id="doc">불러오는 중…</div>
<script>
const doc = document.getElementById('doc');
const txt = s => Array.isArray(s) ? s.join('') : (s || '');
const esc = s => s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
fetch('/api/v1/artifacts/__ID__/content', {credentials: 'include'}).then(r => r.text()).then(body => {
  if ('__KIND__' !== 'notebook') { doc.innerHTML = marked.parse(esc(body)); return; }
  const nb = JSON.parse(body); let html = '';
  for (const cell of nb.cells) {
    if (cell.cell_type === 'markdown') { html += `<div class="cell">${marked.parse(esc(txt(cell.source)))}</div>`; continue; }
    html += `<div class="cell"><pre>${esc(txt(cell.source))}</pre><div class="out">`;
    for (const o of cell.outputs || []) {
      const d = o.data || {};
      if (d['image/png']) html += `<img src="data:image/png;base64,${txt(d['image/png'])}">`;
      else if (d['text/plain']) html += `<pre>${esc(txt(d['text/plain']))}</pre>`;
      else if (o.text) html += `<pre>${esc(txt(o.text))}</pre>`;
      else if (o.traceback) html += `<pre>${esc(o.traceback.join('\\n').replace(/\\x1b\\[[0-9;]*m/g, ''))}</pre>`;
    }
    html += '</div></div>';
  }
  doc.innerHTML = html;
}).catch(e => doc.textContent = '불러오지 못했습니다: ' + e);
</script></body></html>"""

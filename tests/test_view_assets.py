"""The view pages load their libraries from this service, not a CDN."""

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_service.app import mount_api
from core.config import Settings

TEMPLATE = (
    Path(__file__).parents[1] / "src/api_service/templates/artifact_view.html"
)


def test_view_page_libraries_are_served_here():
    app = FastAPI()
    mount_api(app, Settings())
    client = TestClient(app)
    html = TEMPLATE.read_text("utf-8")
    assert "https://" not in html.split("<style>")[0]
    for url in re.findall(r'(?:src|href)="(/view/assets/[^"]+)"', html):
        response = client.get(url)
        assert response.status_code == 200, url
        assert len(response.content) > 1000

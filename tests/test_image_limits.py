"""Images are refused by pixel count before they are decoded."""

import base64
import io

import pytest
from PIL import Image

from core import images


def _png(width: int, height: int) -> str:
    out = io.BytesIO()
    Image.new("L", (width, height)).save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def test_a_huge_canvas_is_refused(monkeypatch):
    monkeypatch.setattr(images, "MAX_PIXELS", 100 * 100)
    with pytest.raises(images.ImageError, match="pixels"):
        images.prepare(_png(101, 100), "image/png", 10_000_000)


def test_a_normal_image_passes():
    prepared = images.prepare(_png(64, 32), "image/png", 10_000_000)
    assert (prepared.width, prepared.height) == (64, 32)

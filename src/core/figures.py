"""Figures of executed steps (plots) shown to a vision model.

A step's manifest names its image outputs by path on the shared result
volume (``SharedStorage.read_step_outputs`` -> ``images``). They reach the
model only for a model whose ``INPUT`` has ``image``, at most as many as the
setting of that use (AGENT_TOOL_IMAGES, REPORT_MAX_IMAGES,
BATCH_REPORT_MAX_IMAGES) and the model's MAX_IMAGES allow. A text model gets
nothing, so its requests stay exactly as they were.
"""

import base64
import logging
from dataclasses import dataclass
from typing import Any

from core.config import Settings
from core.executor.storage import SharedStorage
from core.images import ImageError, fit_file

log = logging.getLogger(__name__)

# a step drawing many figures does not crowd out the others
PER_STEP = 2


@dataclass(frozen=True)
class Figure:
    label: str  # e.g. "Step 3 eda_analysis/boxplot_eda 그림 1"
    base64: str
    mime_type: str


def limit(settings: Settings, model: str | None, configured: int) -> int:
    """How many figures this model call may carry (0: none)."""
    spec = settings.model(model)
    if spec is None or not spec.vision:
        return 0
    return max(0, min(configured, spec.max_images))


def pick(
    steps: list[tuple[str, list[str]]], count: int
) -> list[tuple[str, str]]:
    """(label, path) of at most ``count`` figures, spread over the steps.

    ``steps`` is (step label, image paths) in step order. Every step's first
    figure comes before any step's second one, and a step gives at most
    PER_STEP.
    """
    chosen: list[tuple[str, str]] = []
    for k in range(PER_STEP):
        for label, paths in steps:
            if len(chosen) >= count:
                return chosen
            if k < len(paths):
                chosen.append((f"{label} 그림 {k + 1}", paths[k]))
    return chosen


def load(
    storage: SharedStorage, chosen: list[tuple[str, str]]
) -> list[Figure]:
    """Read and shrink the figures; one that cannot be read is left out."""
    figures = []
    for label, path in chosen:
        try:
            prepared = fit_file(storage.resolve_result(path).read_bytes())
        except (OSError, ValueError, ImageError) as exc:
            log.warning("figure_unreadable path=%s error=%s", path, exc)
            continue
        figures.append(
            Figure(
                label,
                base64.b64encode(prepared.data).decode(),
                prepared.mime_type,
            )
        )
    return figures


def blocks(figures: list[Figure]) -> list[dict[str, Any]]:
    """LangChain content blocks: each figure after a line naming it."""
    out: list[dict[str, Any]] = []
    for figure in figures:
        out.append({"type": "text", "text": f"[{figure.label}]"})
        out.append(
            {
                "type": "image",
                "base64": figure.base64,
                "mime_type": figure.mime_type,
            }
        )
    return out

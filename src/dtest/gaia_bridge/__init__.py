"""This service as a gaia workflow (``src/workflows/dtest/analyst.py``).

Everything gaia-workflow specific lives here; the API, agent and worker do
not know about it. ``entry`` hands the running services to ``runtime``.
"""

from src.dtest.gaia_bridge.graph import build_graph

__all__ = ["build_graph"]

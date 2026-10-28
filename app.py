import sys
from pathlib import Path

src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from gaia.core import GaiaService  # noqa: E402

if __name__ == "__main__":
    gaia_service = GaiaService()
    # pr-agentic-service (src/dtest): routes and startup/shutdown, before
    # main() starts serving (src/dtest/entry.py)
    from src.dtest.entry import attach

    attach(gaia_service.app)
    gaia_service.main()

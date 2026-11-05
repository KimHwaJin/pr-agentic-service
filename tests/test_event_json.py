import json
import math

from core.events import json_safe


def test_nan_and_inf_become_null_at_any_depth():
    data = {
        "results": [
            {"observations": [{"describe": {"std": [math.nan, 1.5]}}]},
            (math.inf, -math.inf, 2),
        ],
        "error": None,
        "ok": True,
    }
    safe = json_safe(data)
    assert safe == {
        "results": [
            {"observations": [{"describe": {"std": [None, 1.5]}}]},
            [None, None, 2],
        ],
        "error": None,
        "ok": True,
    }
    json.dumps(safe, allow_nan=False)  # what Postgres jsonb accepts

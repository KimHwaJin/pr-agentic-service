from typing import Any, cast

from src.dtest.core.bootstrap import _alive, checkpoint_pool
from src.dtest.core.config import Settings


def test_lent_connections_are_checked():
    # a connection dropped by the network while idle is replaced, not lent
    pool = checkpoint_pool(Settings())
    assert pool._check is _alive


def test_idle_connections_send_tcp_keepalive(monkeypatch):
    monkeypatch.setenv("DB_KEEPALIVE_IDLE_SECONDS", "45")
    kwargs = cast(dict[str, Any], checkpoint_pool(Settings()).kwargs)
    assert kwargs["keepalives"] == 1
    assert kwargs["keepalives_idle"] == 45

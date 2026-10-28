"""The running services, for code the gaia template calls.

The template imports workflow modules (and builds their graphs) before the
app starts, so the bridge cannot be handed the services; DtestLifespan
puts them here at startup and takes them away at shutdown.
"""

from src.dtest.core.services import Services

_services: Services | None = None


def set_services(services: Services | None) -> None:
    global _services
    _services = services


def current() -> Services | None:
    return _services

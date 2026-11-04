from src.dtest.core.config import Settings


def test_console_default_follows_env(monkeypatch):
    s = Settings()
    assert s.web_console_enabled is None
    assert s.console_enabled is True  # local
    s._env = "prd"
    assert s.console_enabled is False
    s._env = "dev"
    assert s.console_enabled is True


def test_console_setting_wins():
    s = Settings(web_console_enabled=True)
    s._env = "prd"
    assert s.console_enabled is True
    s = Settings(web_console_enabled=False)
    assert s.console_enabled is False


def _service(**settings):
    from src.dtest.api_service.auth.service import SsoService

    s = Settings(
        public_api_origin="https://api.example",
        frontend_origin="https://front.example",
        **settings,
    )
    return SsoService(s, None, None, None), s


def test_console_login_returns_to_the_api_host():
    import pytest
    from fastapi import HTTPException

    sso, s = _service(web_console_enabled=True)
    assert sso._destination("/dev/", "") == "https://api.example/dev/"
    assert sso._destination("/", "") == "https://front.example/"
    off, _ = _service(web_console_enabled=False)
    with pytest.raises(HTTPException):
        off._destination("/dev/", "")
    assert off._destination("/", "") == "https://front.example/"

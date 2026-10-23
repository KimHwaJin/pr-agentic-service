import pytest

from core import config
from core.config import Settings


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)  # no .env
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    (tmp_path / "config.yml").write_text(
        "redis_namespace: local-ns\nbatch_base_url: http://local:8100\n"
    )
    return tmp_path


def test_without_app_env_only_config_yml_is_read(root):
    settings = Settings()
    assert settings.env == "local"
    assert settings.redis_namespace == "local-ns"


def test_app_env_file_wins_over_config_yml(root, monkeypatch):
    (root / "config.stg.yml").write_text(
        "batch_base_url: http://stg:8100\nsso_adapter: company\n"
        "cookie_secure: true\n"
    )
    monkeypatch.setenv("APP_ENV", "stg")
    settings = Settings()
    assert settings.env == "stg"
    assert settings.batch_base_url == "http://stg:8100"
    assert settings.redis_namespace == "local-ns"  # from config.yml


def test_environment_variables_win_over_files(root, monkeypatch):
    monkeypatch.setenv("REDIS_NAMESPACE", "from-env")
    assert Settings().redis_namespace == "from-env"


def test_app_env_needs_its_file(root, monkeypatch):
    monkeypatch.setenv("APP_ENV", "prd")
    with pytest.raises(ValueError, match="config.prd.yml"):
        Settings()


def test_unknown_app_env_is_refused(root, monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    with pytest.raises(ValueError, match="APP_ENV must be one of"):
        Settings()


def test_a_pod_without_app_env_does_not_start(root, monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    with pytest.raises(ValueError, match="APP_ENV is not set"):
        Settings()

import pytest
import yaml

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
        "cookie_secure: true\nexecutor_api_key: exe\nbatch_api_key: bat\n"
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


def test_keys_are_case_insensitive(root):
    (root / "config.yml").write_text(
        "REDIS_NAMESPACE: upper\nmodels:\n"
        "  - NAME: m-upper\n    DEFAULT: true\n"
        "    PARAMS: {reasoning_effort: low}\n"
        "  - name: m-lower\n"
    )
    settings = Settings()
    assert settings.redis_namespace == "upper"
    assert [m.name for m in settings.models] == ["m-upper", "m-lower"]
    assert settings.default_model.params == {"reasoning_effort": "low"}


PER_ENV_KEYS = {
    "database_url",
    "redis_url",
    "public_api_origin",
    "frontend_origin",
    "cors_origins",
    "cookie_secure",
    "admin_employee_ids",
    "llm_api_key",
    "models",
    "executor_base_url",
    "executor_api_key",
    "executor_admin_api_key",
    "batch_base_url",
    "batch_api_key",
}


def _keys(path):
    return {k.lower() for k in yaml.safe_load(path.read_text())}


def test_config_files_split_every_setting():
    # config.yml holds every key but the per-environment ones, which live
    # only in config.{dev,stg,prd}.yml.
    shared = _keys(config.ROOT / "config.yml")
    assert shared == set(Settings.model_fields) - PER_ENV_KEYS
    for env in config.APP_ENVS:
        assert _keys(config.ROOT / f"config.{env}.yml") == PER_ENV_KEYS


def test_relative_paths_are_under_the_repo_root(root):
    (root / "config.yml").write_text(
        "SKILLS_ROOT: x/skills\nSTORAGE_ROOT: /abs/storage\n"
    )
    settings = Settings()
    assert settings.skills_root == root / "x/skills"
    assert str(settings.storage_root) == "/abs/storage"


def test_settings_files_are_read_as_utf8_on_any_locale(root):
    # Windows reads files as cp949 unless told otherwise; ours carry Korean
    (root / "config.yml").write_text(
        "dev_employee_name: 개발자\n", encoding="utf-8"
    )
    (root / ".env").write_text(
        "# 한글 주석\nDEV_EMPLOYEE_ID=사번1\n", encoding="utf-8"
    )
    assert Settings.model_config.get("env_file_encoding") == "utf-8"
    sources = Settings.settings_customise_sources(
        Settings,
        *(None,) * 4,  # type: ignore[arg-type]
    )
    assert [s.yaml_file_encoding for s in sources[3:]] == ["utf-8"]
    settings = Settings()
    assert settings.dev_employee_name == "개발자"
    assert settings.dev_employee_id == "사번1"


def test_settings_load_under_a_cp949_locale(root):
    # the Windows failure itself, where the host has a CP949 locale
    import os
    import subprocess
    import sys

    (root / "config.yml").write_text(
        "dev_employee_name: 개발자\n", encoding="utf-8"
    )
    (root / ".env").write_text("# 한글 주석\n", encoding="utf-8")
    env = {**os.environ, "LC_ALL": "ko_KR.CP949", "PYTHONUTF8": "0"}
    code = (
        "import locale, sys\n"
        "if locale.getpreferredencoding(False).lower() != 'cp949':\n"
        "    sys.exit(3)\n"
        "from core import config\n"
        "from pathlib import Path\n"
        "config.ROOT = Path.cwd()\n"
        "assert config.Settings().dev_employee_name == '개발자'\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=root, env=env, capture_output=True
    )
    if done.returncode == 3:
        pytest.skip("no CP949 locale on this host")
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


def test_stg_needs_our_service_keys(root, monkeypatch):
    (root / "config.stg.yml").write_text(
        "sso_adapter: company\ncookie_secure: true\n"
    )
    monkeypatch.setenv("APP_ENV", "stg")
    with pytest.raises(ValueError, match="EXECUTOR_API_KEY and BATCH_API_KEY"):
        Settings()


def test_header_mode_only_in_local_and_dev(root, monkeypatch):
    assert Settings(auth_mode="header").auth_mode == "header"  # local
    (root / "config.prd.yml").write_text(
        "sso_adapter: company\ncookie_secure: true\n"
        "executor_api_key: exe\nbatch_api_key: bat\nauth_mode: header\n"
    )
    monkeypatch.setenv("APP_ENV", "prd")
    with pytest.raises(ValueError, match="AUTH_MODE=header"):
        Settings()

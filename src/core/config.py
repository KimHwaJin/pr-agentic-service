"""Service settings.

Sources, highest first: environment variables, ``.env``,
``config.{APP_ENV}.yml`` (one deployment environment), ``config.yml``
(values shared by every environment), field defaults; both files are at the
repo root and baked into the image. ``APP_ENV`` (dev | stg | prd) comes from
the environment or ``.env``; left empty, the service runs as ``local`` on
config.yml plus environment/.env values. Keys are case-insensitive in every
source (``REDIS_URL`` or ``redis_url``; the config files use upper case).
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field, PrivateAttr, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

ROOT = Path(__file__).resolve().parents[2]


APP_ENVS = ("dev", "stg", "prd")
# executor stream names a tenant_id may not take
RESERVED_TENANT_IDS = frozenset({"dlq", "work"})


def app_env() -> str | None:
    """The deployment environment, or None for a local run."""
    env = os.environ.get("APP_ENV") or dotenv_values(".env").get("APP_ENV")
    if env and env not in APP_ENVS:
        raise ValueError(f"APP_ENV must be one of {', '.join(APP_ENVS)}.")
    return env or None


def config_files() -> list[Path]:
    """YAML settings files, highest precedence first."""
    env = app_env()
    files = [ROOT / f"config.{env}.yml"] if env else []
    common = ROOT / "config.yml"
    if common.is_file():
        files.append(common)
    return files


class ModelSpec(BaseModel):
    """One chat model offered to users (config ``models``)."""

    name: str  # served model name on the gateway = API "model" value
    label: str | None = None  # display name; the UI falls back to name
    default: bool = False
    input: list[Literal["text", "image"]] = ["text"]
    max_images: int = Field(0, ge=0, le=32)
    # Extra request body fields for this model only (e.g. reasoning_effort,
    # chat_template_kwargs). Server-side; never sent to clients.
    params: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _any_case_keys(cls, data: Any) -> Any:
        # Config keys are case-insensitive (NAME or name); params stay as is.
        if isinstance(data, dict):
            return {
                k.lower() if isinstance(k, str) else k: v
                for k, v in data.items()
            }
        return data

    @property
    def vision(self) -> bool:
        return "image" in self.input


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        files = [
            YamlConfigSettingsSource(settings_cls, yaml_file=path)
            for path in config_files()
        ]
        return init_settings, env_settings, dotenv_settings, *files

    # APP_ENV, or local when it is empty (not a settings key).
    _env: Literal["local", "dev", "stg", "prd"] = PrivateAttr("local")
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = []

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/agentic"
    )
    redis_url: str = "redis://localhost:6379/0"
    redis_namespace: str = "agentic"
    db_pool_size: int = 10
    auto_migrate: bool = True

    # SSO. "dev" returns a fixed employee and is refused outside env=local.
    sso_adapter: Literal["dev", "company"] = "dev"
    sso_adapter_factory: str = ""  # module:factory returning a SyncSdk factory
    public_api_origin: str = "http://localhost:8080"
    frontend_origin: str = "http://localhost:8080"
    sso_allowed_origins: list[str] = []
    sso_allowed_return_roots: list[str] = ["/"]
    session_cookie_name: str = "agentic_session"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_ttl_seconds: int = Field(1800, ge=60, le=86400)
    login_flow_ttl_seconds: int = Field(300, ge=60, le=1800)
    sso_call_timeout_seconds: float = 10.0
    dev_employee_id: str = "dev0001"
    dev_employee_name: str = "개발자"
    admin_employee_ids: list[str] = []

    # LLM gateway (OpenAI compatible, vLLM).
    llm_base_url: str = "http://localhost:8001/v1"
    llm_api_key: str = "EMPTY"
    # Offered chat models; exactly one has default: true.
    models: list[ModelSpec] = [ModelSpec(name="default", default=True)]
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 120.0
    llm_enable_thinking: bool | None = None

    embedding_provider: Literal["none", "openai", "mock"] = "none"
    embedding_base_url: str = ""
    embedding_api_key: str = "EMPTY"
    embedding_model: str = ""
    embedding_dims: int = 1024

    # Executor.
    executor_base_url: str = "http://localhost:8000"
    # The system that receives this service's executor events: sent as
    # tenant_id with every submission and with batches registered through
    # pr-batch, so their events come to <executor_event_stream>.<tenant>.
    # The same in every environment (config.yml); a local run against a
    # shared executor can change it to keep its events apart.
    executor_tenant_id: str = Field(
        "pr-agentic", pattern=r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$"
    )
    # This service's folder on the executor input PV (INPUT_STORAGE_ROOT):
    # the local mount, and the same folder relative to INPUT_STORAGE_ROOT.
    # Code sent to the executor lives under <root>/sources/.
    storage_root: Path = ROOT / ".local/shared/agentic"
    storage_executor_path: str = "agentic"
    # local mount of the executor's SHARED_STORAGE_ROOT (results)
    executor_result_root: Path = ROOT / ".local/shared"
    # the executor's REDIS_EVENT_STREAM: shared stream and tenant prefix
    executor_event_stream: str = "executor.events"
    # Also read the shared stream, for executions submitted without a
    # tenant (before this service and pr-batch sent one). Turn off once
    # those have finished.
    executor_read_shared_stream: bool = True
    # a run still waiting this long asks the executor for its event
    executor_event_recovery_seconds: float = 120
    executor_runtime_profile: str = "default"
    executor_operation_wait_seconds: int = Field(1800, ge=30)
    executor_step_timeout_seconds: int | None = None
    executor_timeout_seconds: float = 30.0

    # JupyterLab link for executor notebooks/reports (empty = no link).
    notebook_lab_base_url: str = ""
    notebook_lab_path_prefix: str = (
        ""  # Lab root -> Jupyter shared storage root, if they differ
    )
    notebook_lab_workspace_prefix: str = "agentic-"

    # Agent assets.
    prompts_root: Path = ROOT / "src/agent/prompts"
    skills_root: Path = ROOT / "assets/skills"
    tools_root: Path = ROOT / "assets/tools"
    knowledge_root: Path = ROOT / "assets/knowledge"
    # Extra catalogs on top of the three roots above, in order: each holds
    # skills/, tools/ and knowledge/ (any may be missing). A later catalog
    # replaces a skill, tool or knowledge entry of the same name. Removing
    # an entry here restores the base catalog.
    catalog_extensions: list[Path] = []

    def executor_event_streams(self) -> list[str]:
        """Streams the executor event consumer reads, tenant first."""
        streams = [f"{self.executor_event_stream}.{self.executor_tenant_id}"]
        if self.executor_read_shared_stream:
            streams.append(self.executor_event_stream)
        return streams

    def catalog_roots(self, kind: str) -> list[Path]:
        """Base root and extension roots for skills | tools | knowledge."""
        base = {
            "skills": self.skills_root,
            "tools": self.tools_root,
            "knowledge": self.knowledge_root,
        }[kind]
        return [base] + [
            (ext if ext.is_absolute() else ROOT / ext) / kind
            for ext in self.catalog_extensions
        ]

    default_code_level: int = Field(3, ge=1, le=4)
    plan_candidates: int = Field(5, ge=1, le=10)
    workflow_similarity: float = 0.93
    agent_recursion_limit: int = 200
    agent_model_call_limit: int = (
        40  # per turn; stops a model that keeps repeating a failing call
    )
    # Shrink tool results of an analysis once finish_analysis closes it.
    agent_compact_finished_analysis: bool = True
    # Conversation summarization starts past this many estimated tokens
    # (LangChain's 4 chars = 1 token; our Korean history is ~2 chars per
    # real token, so 30000 is ~120k chars, ~55k real tokens: about 40% of a
    # 128k window such as gpt-oss-120b). Half of it is kept after a summary.
    agent_summary_trigger_tokens: int = 30000
    agent_summary_max_chars: int = 6000  # length asked of the summary

    # Project memory.
    memory_item_max_chars: int = 1000
    memory_total_max_chars: int = 30000
    memory_prompt_max_chars: int = 12000
    memory_prompt_items: int = 8

    # Run scheduler.
    run_concurrency: int = Field(
        32, ge=1
    )  # turns are I/O bound (LLM, executor)
    run_lease_seconds: int = Field(60, ge=10)
    run_poll_seconds: float = 5.0  # fallback only; runs are woken over Redis

    # Retention of transport data.
    run_event_retention_days: int = 30
    executor_inbox_retention_days: int = 7
    # code files are only needed until the executor snapshots them
    code_source_retention_days: int = 7
    # images of deleted sessions; run idempotency keys
    image_retention_days: int = 7
    run_request_retention_days: int = 1

    # Images sent with a turn (vision models only).
    image_max_bytes: int = 10 * 1024 * 1024
    image_max_total_bytes: int = 20 * 1024 * 1024
    image_context_turns: int = (
        3  # images of the last N user turns reach the model
    )

    # pr-batch.
    batch_base_url: str = "http://localhost:8100"
    # PEM RSA private key the pr-batch team hands out (RS256; pr-batch
    # verifies with the public half). Relative paths are under the repo
    # root. Empty = the integration is off.
    batch_jwt_private_key_file: str = ""
    batch_jwt_issuer: str = "batch-client"
    batch_jwt_audience: str = "batch-service"
    # Add executor_tenant_id to batches registered through the gateway, so
    # their executions report to this service. Turn on once pr-batch
    # accepts tenant_id (it rejects unknown fields).
    batch_send_tenant_id: bool = False
    # Reports of successful BATCH executions (worker.batch_reports).
    # empty = the default model
    batch_report_model: str = ""
    # how long COLLECTING waits for the executor's notebook projection
    batch_report_collect_timeout_seconds: int = 1800
    batch_report_poll_seconds: float = 10
    # previous runs' summaries the agent reads (memory per batch)
    batch_report_memory_runs: int = Field(5, ge=0, le=50)
    batch_report_model_call_limit: int = 20

    @model_validator(mode="after")
    def _guard(self) -> "Settings":
        self._env = app_env() or "local"
        if self.env != "local":
            path = ROOT / f"config.{self.env}.yml"
            if not path.is_file():
                raise ValueError(f"APP_ENV={self.env} needs {path}")
        if self.sso_adapter == "dev" and self.env != "local":
            raise ValueError(
                "SSO_ADAPTER=dev is only allowed locally (no APP_ENV)"
            )
        if self.env in {"stg", "prd"} and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true outside local/dev")
        if self.embedding_provider == "openai" and not (
            self.embedding_base_url and self.embedding_model
        ):
            raise ValueError(
                "EMBEDDING_PROVIDER=openai needs EMBEDDING_BASE_URL and "
                "EMBEDDING_MODEL"
            )
        if self.executor_tenant_id in RESERVED_TENANT_IDS:
            raise ValueError(
                f"EXECUTOR_TENANT_ID {self.executor_tenant_id!r} is reserved"
            )
        names = [m.name for m in self.models]
        if len(set(names)) != len(names):
            raise ValueError("models: duplicate name")
        if sum(m.default for m in self.models) != 1:
            raise ValueError("models: exactly one model needs default: true")
        if self.env == "local" and os.environ.get("KUBERNETES_SERVICE_HOST"):
            raise ValueError("APP_ENV is not set for this pod")
        return self

    @property
    def env(self) -> Literal["local", "dev", "stg", "prd"]:
        return self._env

    @property
    def default_model(self) -> ModelSpec:
        return next(m for m in self.models if m.default)

    def model(self, name: str | None) -> ModelSpec | None:
        """The configured model by name (None -> the default)."""
        if name is None:
            return self.default_model
        return next((m for m in self.models if m.name == name), None)

    @property
    def psycopg_url(self) -> str:
        return self.database_url.replace(
            "postgresql+psycopg://", "postgresql://"
        )

    @property
    def embedding_space(self) -> str:
        """Vectors from different models/dims never mix in search."""
        model = (
            "mock-ngram"
            if self.embedding_provider == "mock"
            else self.embedding_model
        )
        return f"{model}:{self.embedding_dims}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

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
from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# ROOT: the repo root (config*.yml, logger.yml; relative paths in settings
# are under it). DTEST_ROOT: this service's folder in the template's src/.
ROOT = Path(__file__).resolve().parents[3]
DTEST_ROOT = ROOT / "src/dtest"


APP_ENVS = ("dev", "stg", "prd")
# executor stream names a tenant_id may not take
RESERVED_TENANT_IDS = frozenset({"dlq", "work"})


def app_env() -> str | None:
    """The deployment environment, or None for a local run."""
    env = os.environ.get("APP_ENV") or dotenv_values(
        ".env", encoding="utf-8"
    ).get("APP_ENV")
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
    # utf-8 files (Korean comments): never the locale's code page (cp949)
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

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
            YamlConfigSettingsSource(
                settings_cls, yaml_file=path, yaml_file_encoding="utf-8"
            )
            for path in config_files()
        ]
        return init_settings, env_settings, dotenv_settings, *files

    # APP_ENV, or local when it is empty (not a settings key).
    _env: Literal["local", "dev", "stg", "prd"] = PrivateAttr("local")
    cors_origins: list[str] = []

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/agentic"
    )
    redis_url: str = "redis://localhost:6379/0"
    redis_namespace: str = "agentic"
    # app-table pool (+ the same overflow); measured peak use is the burst
    # of run creation, idle while turns run (docs/load-design.md)
    db_pool_size: int = 5
    # psycopg pool of the LangGraph checkpointer and store: every graph
    # step of every running turn (RUN_CONCURRENCY) writes through it
    checkpoint_pool_size: int = Field(16, ge=2)
    # how long a checkpoint write waits for a free connection
    checkpoint_pool_timeout_seconds: float = Field(30.0, gt=0)
    auto_migrate: bool = True
    # Swagger UI, ReDoc and /openapi.json. Off unless turned on: the internal
    # network rules forbid them even on the dev environment.
    docs_enabled: bool = False

    # SSO. "dev" returns a fixed employee and is refused outside env=local.
    sso_adapter: Literal["dev", "idp"] = "dev"
    sso_adapter_factory: str = ""  # module:factory returning a SyncSdk factory
    public_api_origin: str = "http://localhost:8080"
    frontend_origin: str = "http://localhost:8080"
    sso_allowed_origins: list[str] = []
    sso_allowed_return_roots: list[str] = ["/"]
    session_cookie_name: str = "agentic_session"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # Login sessions slide: idle this long ends one, activity extends it,
    # up to session_max_seconds after the login.
    session_ttl_seconds: int = Field(1800, ge=60, le=86400)
    session_max_seconds: int = Field(43200, ge=300, le=7 * 86400)
    login_flow_ttl_seconds: int = Field(300, ge=60, le=1800)
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

    # Service-to-service auth (docs/specs/service-auth.md).
    # api_key: callers other than the browser send X-Api-Key (a key of
    # api_clients) and X-User-Id. header: X-User-Id is trusted without a
    # key (local/dev only, for testers).
    auth_mode: Literal["api_key", "header"] = "api_key"
    # how long a verified caller key is cached (revocation delay)
    api_client_cache_seconds: float = Field(60, ge=0, le=300)

    # Executor.
    executor_base_url: str = "http://localhost:8000"
    # Our key at the executor (X-Api-Key, a relay key). Empty only against
    # an executor in header mode (local/dev).
    executor_api_key: str = ""
    # The operator key of the executor's runtime and maintenance APIs, for
    # the 시스템 page; empty = those pages answer 503.
    executor_admin_api_key: str = ""
    # The executor tenant of this service (the default tenant of our key):
    # the events of our executions and of the batches registered through
    # us come to <executor_event_stream>.<tenant>. The same in every
    # environment (config.yml); a local run against a shared executor can
    # change it to keep its events apart. Executor and pr-batch list it in
    # our key's allowed_tenants.
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
    # the executor's REDIS_EVENT_STREAM (prefix of the tenant streams)
    executor_event_stream: str = "executor.events"
    # a run still waiting this long asks the executor for its event
    executor_event_recovery_seconds: float = 120
    executor_runtime_profile: str = "default"
    executor_operation_wait_seconds: int = Field(1800, ge=30)
    executor_step_timeout_seconds: int | None = None
    executor_timeout_seconds: float = 30.0
    # "api": no shared PV with the executor (test environments only; see
    # core/executor/testmode). Code goes INLINE, results come from the
    # executor notebook API.
    executor_io_mode: Literal["pv", "api"] = "pv"

    # JupyterLab link for executor notebooks/reports (empty = no link).
    notebook_lab_base_url: str = ""
    notebook_lab_path_prefix: str = (
        ""  # Lab root -> Jupyter shared storage root, if they differ
    )
    notebook_lab_workspace_prefix: str = "agentic-"

    # Agent assets.
    skills_root: Path = DTEST_ROOT / "assets/skills"
    tools_root: Path = DTEST_ROOT / "assets/tools"
    knowledge_root: Path = DTEST_ROOT / "assets/knowledge"
    # Extra catalogs on top of the three roots above, in order: each holds
    # skills/, tools/ and knowledge/ (any may be missing). A later catalog
    # replaces a skill, tool or knowledge entry of the same name. Removing
    # an entry here restores the base catalog.
    catalog_extensions: list[Path] = []

    @field_validator(
        "storage_root",
        "executor_result_root",
        "skills_root",
        "tools_root",
        "knowledge_root",
    )
    @classmethod
    def _under_root(cls, path: Path) -> Path:
        # Relative paths in config files are under the repo root, not cwd.
        return path if path.is_absolute() else ROOT / path

    @property
    def executor_tenant_stream(self) -> str:
        """The stream the executor publishes our executions' events to."""
        return f"{self.executor_event_stream}.{self.executor_tenant_id}"

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
    # who may promote a candidate workflow to a template for every user:
    # its author, or administrators only (any workflow)
    workflow_promotion: Literal["author", "admin"] = "author"
    agent_recursion_limit: int = 200
    agent_model_call_limit: int = (
        40  # per turn; stops a model that keeps repeating a failing call
    )
    # a tool failing with the same error this many times in a row in one
    # turn is not run again; the model explains the error instead
    agent_tool_failure_limit: int = Field(3, ge=1)
    # model calls of the report agent writing an analysis report inside a
    # chat turn (the user waits; batch reports have their own limit)
    report_model_call_limit: int = Field(8, ge=2)
    # Shrink tool results of an analysis once finish_analysis closes it.
    agent_compact_finished_analysis: bool = True
    # Conversation summarization starts past this many estimated tokens
    # (LangChain's 4 chars = 1 token; our Korean history is ~2 chars per
    # real token, so 30000 is ~120k chars, ~55k real tokens: about 40% of a
    # 128k window such as gpt-oss-120b). Half of it is kept after a summary.
    agent_summary_trigger_tokens: int = 30000
    agent_summary_max_chars: int = 6000  # length asked of the summary

    # Project memory: up to 6 topics per project (editable), each a short
    # Markdown body with its own limit, all of it in every prompt. The
    # topics' limits of one project add up to at most this; the default
    # four topics take 2200.
    memory_total_max_chars: int = Field(2200, ge=2200, le=20000)
    # Background extraction of what the user said (worker.memory): a
    # project is processed once its chats are quiet this long or after
    # this many finished turns. Turns are counted even while disabled.
    memory_worker_enabled: bool = True
    memory_worker_quiet_seconds: float = Field(180, ge=0)
    memory_worker_max_turns: int = Field(5, ge=1)
    # chat text per LLM call (chars / 4); the rest waits for the next call
    memory_worker_max_input_tokens: int = Field(8000, ge=500)
    memory_worker_concurrency: int = Field(1, ge=1)

    # Run scheduler.
    run_concurrency: int = Field(
        32, ge=1
    )  # turns are I/O bound (LLM, executor)
    # turns of one user running at once across pods (0: no limit)
    run_user_concurrency: int = Field(4, ge=0)
    run_lease_seconds: int = Field(60, ge=10)
    run_poll_seconds: float = 5.0  # fallback only; runs are woken over Redis
    # claims without reaching a pause before a run is failed (crash loops)
    run_max_attempts: int = Field(5, ge=1)

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
    # request bodies larger than this (Content-Length) are refused with 413
    # before they are read; the ingress should have its own limit too
    request_max_bytes: int = 32 * 1024 * 1024
    image_context_turns: int = (
        3  # images of the last N user turns reach the model
    )

    # pr-batch.
    batch_base_url: str = "http://localhost:8100"
    # Our key at pr-batch (X-Api-Key; a relay key with admin, for
    # disable-by-owner). Empty only against pr-batch in header mode.
    batch_api_key: str = ""
    # Reports of successful BATCH executions (worker.batch_reports).
    # empty = the default model
    batch_report_model: str = ""
    # how long COLLECTING waits for the executor's notebook projection
    batch_report_collect_timeout_seconds: int = 1800
    batch_report_poll_seconds: float = 10
    # previous runs' summaries the agent reads (memory per batch)
    batch_report_memory_runs: int = Field(5, ge=0, le=50)
    batch_report_model_call_limit: int = 20
    # batch report jobs one pod writes at once (each a series of LLM calls)
    batch_report_concurrency: int = Field(4, ge=1)
    # Recovery of reports whose execution.completed never reached us: every
    # interval, our successful BATCH executions of the lookback without a
    # job get one. A retention of report jobs must keep them longer than
    # the lookback, or recovery writes deleted reports again.
    batch_report_recovery_interval_seconds: float = Field(600, ge=60)
    batch_report_recovery_lookback_days: int = Field(14, ge=1, le=90)

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
        if self.session_max_seconds < self.session_ttl_seconds:
            raise ValueError(
                "SESSION_MAX_SECONDS must be at least SESSION_TTL_SECONDS"
            )
        if self.executor_io_mode == "api" and self.env in {"stg", "prd"}:
            raise ValueError("EXECUTOR_IO_MODE=api is for test environments")
        if self.auth_mode == "header" and self.env not in {"local", "dev"}:
            raise ValueError("AUTH_MODE=header is only allowed in local/dev")
        if self.env in {"stg", "prd"} and not (
            self.executor_api_key and self.batch_api_key
        ):
            raise ValueError(
                "EXECUTOR_API_KEY and BATCH_API_KEY are required in stg/prd"
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

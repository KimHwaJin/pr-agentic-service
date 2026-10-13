from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["local", "dev", "stg", "prd"] = "local"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = []

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/agentic"
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
    llm_models: dict[str, str] = {"default": "default"}  # alias -> served model name
    llm_default_alias: str = "default"
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 120.0
    llm_enable_thinking: bool | None = None

    embedding_base_url: str = ""
    embedding_api_key: str = "EMPTY"
    embedding_model: str = ""
    embedding_dims: int = 1024

    # Executor.
    executor_base_url: str = "http://localhost:8000"
    executor_input_root: Path = ROOT / ".local/shared"  # local mount of INPUT_STORAGE_ROOT
    executor_result_root: Path = ROOT / ".local/shared"  # local mount of SHARED_STORAGE_ROOT
    executor_input_subdir: str = "agentic"
    executor_event_stream: str = "executor.events"
    executor_runtime_profile: str = "default"
    executor_operation_wait_seconds: int = Field(1800, ge=30)
    executor_step_timeout_seconds: int | None = None
    executor_timeout_seconds: float = 30.0

    # Agent assets.
    prompts_root: Path = ROOT / "src/agent/prompts"
    skills_root: Path = ROOT / "assets/skills"
    tools_root: Path = ROOT / "assets/tools"
    knowledge_root: Path = ROOT / "assets/knowledge"
    default_code_level: int = Field(3, ge=1, le=4)
    plan_candidates: int = Field(5, ge=1, le=10)
    workflow_similarity: float = 0.93
    agent_recursion_limit: int = 200

    # Project memory.
    memory_item_max_chars: int = 1000
    memory_total_max_chars: int = 30000
    memory_prompt_max_chars: int = 12000
    memory_prompt_items: int = 8

    # Run scheduler.
    run_concurrency: int = Field(32, ge=1)  # turns are I/O bound (LLM, executor)
    run_lease_seconds: int = Field(60, ge=10)
    run_poll_seconds: float = 5.0  # fallback only; runs are woken over Redis

    # Retention of transport data.
    run_event_retention_days: int = 30
    executor_inbox_retention_days: int = 7

    # pr-batch.
    batch_base_url: str = "http://localhost:8100"
    batch_jwt_secret: str = ""  # we sign: iss=agentic, aud=pr-batch
    batch_jwt_issuer: str = "prj_re"
    batch_report_jwt_secret: str = ""  # pr-batch signs: iss=pr-batch, aud=prj_re-report

    @model_validator(mode="after")
    def _guard(self) -> "Settings":
        if self.sso_adapter == "dev" and self.env != "local":
            raise ValueError("SSO_ADAPTER=dev is only allowed with ENV=local")
        if self.env in {"stg", "prd"} and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true outside local/dev")
        if self.llm_default_alias not in self.llm_models:
            raise ValueError("LLM_DEFAULT_ALIAS must be a key of LLM_MODELS")
        return self

    @property
    def psycopg_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.embedding_base_url and self.embedding_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()

from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from redis.asyncio import Redis

from core.assets import AssetLoader, SkillCatalog, ToolCatalog
from core.config import Settings
from core.db import Database
from core.events import EventBus
from core.executor.client import ExecutorClient
from core.executor.storage import SharedStorage
from core.memory.service import ProjectMemory
from core.workflows.service import WorkflowService


@dataclass
class Services:
    """Process-wide singletons created in the app lifespan."""

    settings: Settings
    db: Database
    redis: Redis
    events: EventBus
    executor: ExecutorClient
    storage: SharedStorage
    memory: ProjectMemory
    workflows: WorkflowService
    embedder: Embeddings | None
    analysis_skills: AssetLoader  # -> SkillCatalog
    knowledge: AssetLoader  # -> SkillCatalog
    tools: AssetLoader  # -> ToolCatalog

    def skills(self, root: str) -> SkillCatalog:
        return {"analysis": self.analysis_skills, "knowledge": self.knowledge}[
            root
        ].get()

    def tool_catalog(self) -> ToolCatalog:
        return self.tools.get()

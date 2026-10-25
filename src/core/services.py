from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langgraph.checkpoint.base import BaseCheckpointSaver
from redis.asyncio import Redis

from core.assets import AssetLoader, SkillCatalog, ToolCatalog
from core.config import Settings
from core.db import Database
from core.events import EventBus
from core.executor.client import ExecutorClient
from core.executor.sources import CodeSources
from core.executor.storage import SharedStorage
from core.images import Images
from core.memory.service import ProjectMemory
from core.workflows.service import WorkflowService

# Store namespace prefix of a run's replay guards (agent.tools.analysis._once)
TOOL_EFFECTS = "tool_effects"


@dataclass
class Services:
    """Process-wide singletons created in the app lifespan."""

    settings: Settings
    db: Database
    redis: Redis
    events: EventBus
    executor: ExecutorClient
    storage: SharedStorage
    code_sources: CodeSources
    images: Images
    memory: ProjectMemory
    workflows: WorkflowService
    embedder: Embeddings | None
    # LangGraph checkpoints; thread id = session id
    checkpointer: BaseCheckpointSaver
    analysis_skills: AssetLoader  # -> SkillCatalog
    knowledge: AssetLoader  # -> SkillCatalog
    tools: AssetLoader  # -> ToolCatalog

    def skills(self, root: str) -> SkillCatalog:
        return {"analysis": self.analysis_skills, "knowledge": self.knowledge}[
            root
        ].get()

    def tool_catalog(self) -> ToolCatalog:
        return self.tools.get()

    async def forget_tool_effects(self, run_id: str) -> None:
        """Drop a run's replay guards once it is over (any terminal state)."""
        store = self.memory.store
        namespace = (TOOL_EFFECTS, run_id)
        for item in await store.asearch(namespace, limit=1000):
            await store.adelete(namespace, item.key)

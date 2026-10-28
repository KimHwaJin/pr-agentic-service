"""Middleware of the agent graph, in the order graph.py stacks them.

- persona: two personas in one graph (prompt, tools, memory, images,
  stall recovery)
- json_arguments: nested arguments that arrive as JSON strings
- tool_failures: stops a tool failing the same way again and again
- compaction: generic; trims the tool traffic of finished segments
  (our rules: compaction_rules)
- summarization: LangChain's summary with progress events
"""

from src.dtest.agent.middleware.compaction import (
    ToolResultCompactionMiddleware,
)
from src.dtest.agent.middleware.json_arguments import JsonArgumentsMiddleware
from src.dtest.agent.middleware.persona import PersonaMiddleware
from src.dtest.agent.middleware.summarization import (
    ReportingSummarizationMiddleware,
)
from src.dtest.agent.middleware.tool_failures import ToolFailureLimitMiddleware

__all__ = [
    "JsonArgumentsMiddleware",
    "PersonaMiddleware",
    "ReportingSummarizationMiddleware",
    "ToolFailureLimitMiddleware",
    "ToolResultCompactionMiddleware",
]

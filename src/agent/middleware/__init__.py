"""Middleware of the agent graph, in the order graph.py stacks them.

- persona: two personas in one graph (prompt, tools, memory, images,
  stall recovery)
- json_arguments: nested arguments that arrive as JSON strings
- compaction: generic; trims the tool traffic of finished segments
  (our rules: compaction_rules)
- summarization: LangChain's summary with progress events
"""

from agent.middleware.compaction import ToolResultCompactionMiddleware
from agent.middleware.json_arguments import JsonArgumentsMiddleware
from agent.middleware.persona import PersonaMiddleware
from agent.middleware.summarization import ReportingSummarizationMiddleware

__all__ = [
    "JsonArgumentsMiddleware",
    "PersonaMiddleware",
    "ReportingSummarizationMiddleware",
    "ToolResultCompactionMiddleware",
]

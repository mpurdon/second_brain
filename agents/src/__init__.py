"""Second Brain AI Agents."""

__version__ = "0.1.0"

from .router import RouterAgent, create_router_agent
from .ingestion import IngestionAgent, create_ingestion_agent
from .query import QueryAgent, create_query_agent

__all__ = [
    "__version__",
    # Router Agent
    "RouterAgent",
    "create_router_agent",
    # Ingestion Agent
    "IngestionAgent",
    "create_ingestion_agent",
    # Query Agent
    "QueryAgent",
    "create_query_agent",
]

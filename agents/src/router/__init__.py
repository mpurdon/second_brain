"""Router Agent - Entry point for Second Brain agent system."""

from .agent import RouterAgent, create_router_agent
from .prompts import ROUTER_SYSTEM_PROMPT

__all__ = [
    "RouterAgent",
    "create_router_agent",
    "ROUTER_SYSTEM_PROMPT",
]

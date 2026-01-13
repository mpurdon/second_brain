"""Query Agent - Answers questions from the knowledge base."""

from .agent import QueryAgent, create_query_agent
from .prompts import QUERY_SYSTEM_PROMPT

__all__ = [
    "QueryAgent",
    "create_query_agent",
    "QUERY_SYSTEM_PROMPT",
]

"""Taxonomy Agent - Manages tags and classification evolution."""

from .agent import create_taxonomy_agent, TaxonomyAgentProcessor
from .prompts import TAXONOMY_AGENT_PROMPT

__all__ = [
    "create_taxonomy_agent",
    "TaxonomyAgentProcessor",
    "TAXONOMY_AGENT_PROMPT",
]

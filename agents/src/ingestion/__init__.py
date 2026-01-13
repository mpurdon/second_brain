"""Ingestion Agent - Processes and stores new facts."""

from .agent import IngestionAgent, create_ingestion_agent
from .prompts import INGESTION_SYSTEM_PROMPT

__all__ = [
    "IngestionAgent",
    "create_ingestion_agent",
    "INGESTION_SYSTEM_PROMPT",
]

"""Scheduler Agent - Generates briefings and proactive notifications."""

from .agent import create_scheduler_agent, SchedulerAgentProcessor
from .prompts import SCHEDULER_AGENT_PROMPT

__all__ = [
    "create_scheduler_agent",
    "SchedulerAgentProcessor",
    "SCHEDULER_AGENT_PROMPT",
]

"""Shared utilities and tools for agents."""

from .config import Settings, get_settings
from .database import (
    get_connection,
    execute_query,
    execute_one,
    execute_scalar,
    execute_command,
    run_async,
)
from .models import (
    Fact,
    FactCreate,
    Entity,
    EntityCreate,
    EntityLocation,
    CalendarEvent,
    SearchResult,
)

__all__ = [
    # Config
    "Settings",
    "get_settings",
    # Database
    "get_connection",
    "execute_query",
    "execute_one",
    "execute_scalar",
    "execute_command",
    "run_async",
    # Models
    "Fact",
    "FactCreate",
    "Entity",
    "EntityCreate",
    "EntityLocation",
    "CalendarEvent",
    "SearchResult",
]

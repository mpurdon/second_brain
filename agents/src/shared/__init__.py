"""Shared utilities and tools for agents."""

from .config import Settings, get_settings
from .database import (
    DatabasePool,
    get_connection,
    execute_query,
    execute_one,
    execute_scalar,
    execute_command,
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
    "DatabasePool",
    "get_connection",
    "execute_query",
    "execute_one",
    "execute_scalar",
    "execute_command",
    # Models
    "Fact",
    "FactCreate",
    "Entity",
    "EntityCreate",
    "EntityLocation",
    "CalendarEvent",
    "SearchResult",
]

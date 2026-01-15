"""Strands SDK tools for Second Brain agents."""

from .database import fact_store, fact_search
from .vector_search import semantic_search, generate_embedding, store_fact_embedding
from .entities import entity_search, entity_create, entity_get_details, entity_link_to_fact
from .geographic import (
    proximity_search,
    geocode_address,
    store_entity_location,
    calculate_distance,
)
from .calendar import (
    calendar_get_events,
    calendar_get_events_with_context,
    calendar_sync,
    calendar_create_event,
)
from .taxonomy import (
    tag_cooccurrence_analysis,
    untagged_facts_analysis,
    tag_hierarchy_analysis,
    suggest_tags_for_fact,
    propose_taxonomy_changes,
)
from .scheduler import (
    get_today_events,
    get_upcoming_birthdays,
    get_active_reminders,
    get_entity_context,
    queue_notification,
    save_briefing,
    mark_reminder_triggered,
)

__all__ = [
    # Database tools
    "fact_store",
    "fact_search",
    # Vector search tools
    "semantic_search",
    "generate_embedding",
    "store_fact_embedding",
    # Entity tools
    "entity_search",
    "entity_create",
    "entity_get_details",
    "entity_link_to_fact",
    # Geographic tools
    "proximity_search",
    "geocode_address",
    "store_entity_location",
    "calculate_distance",
    # Calendar tools
    "calendar_get_events",
    "calendar_get_events_with_context",
    "calendar_sync",
    "calendar_create_event",
    # Taxonomy tools
    "tag_cooccurrence_analysis",
    "untagged_facts_analysis",
    "tag_hierarchy_analysis",
    "suggest_tags_for_fact",
    "propose_taxonomy_changes",
    # Scheduler tools
    "get_today_events",
    "get_upcoming_birthdays",
    "get_active_reminders",
    "get_entity_context",
    "queue_notification",
    "save_briefing",
    "mark_reminder_triggered",
]

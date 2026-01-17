"""Calendar tools for event management and sync."""

# asyncio import removed
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from strands import tool

from ..database import execute_command, execute_one, execute_query, run_async


@tool
def calendar_get_events(
    user_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days_ahead: int = 7,
    include_all_day: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Get calendar events for a user.

    Use this tool to retrieve upcoming calendar events. By default returns
    events for the next 7 days.

    Args:
        user_id: UUID of the user.
        start_date: Optional start date (YYYY-MM-DD). Defaults to today.
        end_date: Optional end date (YYYY-MM-DD). Defaults to start + days_ahead.
        days_ahead: Number of days to look ahead if end_date not specified.
        include_all_day: Whether to include all-day events (default True).
        limit: Maximum number of events to return.

    Returns:
        Dictionary with list of calendar events.
    """
    async def _get_events() -> dict[str, Any]:
        # Parse dates
        if start_date:
            start = datetime.fromisoformat(start_date)
        else:
            start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if end_date:
            end = datetime.fromisoformat(end_date)
        else:
            end = start + timedelta(days=days_ahead)

        # Build query
        all_day_filter = "" if include_all_day else "AND NOT all_day"

        query = f"""
            SELECT
                ce.id,
                ce.title,
                ce.description,
                ce.location,
                ce.start_time,
                ce.end_time,
                ce.all_day,
                ce.visibility_tier,
                ce.external_provider,
                ce.is_recurring
            FROM calendar_events ce
            WHERE ce.user_id = $1
            AND ce.start_time >= $2
            AND ce.start_time < $3
            {all_day_filter}
            ORDER BY ce.start_time ASC
            LIMIT $4
        """

        results = await execute_query(query, UUID(user_id), start, end, limit)

        events = [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "description": row["description"],
                "location": row["location"],
                "start_time": row["start_time"].isoformat(),
                "end_time": row["end_time"].isoformat(),
                "all_day": row["all_day"],
                "visibility_tier": row["visibility_tier"],
                "provider": row["external_provider"],
                "is_recurring": row["is_recurring"],
            }
            for row in results
        ]

        return {
            "status": "success",
            "date_range": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "count": len(events),
            "events": events,
        }

    return run_async(_get_events())


@tool
def calendar_get_events_with_context(
    user_id: str,
    date: str | None = None,
) -> dict[str, Any]:
    """Get calendar events with related context from the knowledge base.

    Use this tool for morning briefings or meeting prep. Returns events
    along with relevant facts about attendees and related entities.

    Args:
        user_id: UUID of the user.
        date: The date to get events for (YYYY-MM-DD). Defaults to today.

    Returns:
        Dictionary with events and related context.
    """
    async def _get_with_context() -> dict[str, Any]:
        if date:
            target_date = datetime.fromisoformat(date)
        else:
            target_date = datetime.now()

        start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        # Get events for the day
        events_query = """
            SELECT
                ce.id,
                ce.title,
                ce.description,
                ce.location,
                ce.start_time,
                ce.end_time,
                ce.all_day
            FROM calendar_events ce
            WHERE ce.user_id = $1
            AND ce.start_time >= $2
            AND ce.start_time < $3
            ORDER BY ce.start_time ASC
        """

        events = await execute_query(events_query, UUID(user_id), start, end)

        enriched_events = []
        for event in events:
            event_id = event["id"]

            # Get attendees with entity links
            attendees = await execute_query(
                """
                SELECT
                    cea.display_name,
                    cea.email,
                    cea.response_status,
                    e.id as entity_id,
                    e.name as entity_name
                FROM calendar_event_attendees cea
                LEFT JOIN entities e ON e.id = cea.entity_id
                WHERE cea.event_id = $1
                """,
                event_id,
            )

            # Get relevant facts about attendees
            attendee_facts = []
            for attendee in attendees:
                if attendee["entity_id"]:
                    facts = await execute_query(
                        """
                        SELECT f.content, f.importance
                        FROM facts f
                        WHERE f.about_entity_id = $1
                        AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
                        ORDER BY f.importance DESC, f.recorded_at DESC
                        LIMIT 3
                        """,
                        attendee["entity_id"],
                    )
                    if facts:
                        attendee_facts.append({
                            "entity_name": attendee["entity_name"],
                            "facts": [f["content"] for f in facts],
                        })

            enriched_events.append({
                "id": str(event["id"]),
                "title": event["title"],
                "description": event["description"],
                "location": event["location"],
                "start_time": event["start_time"].isoformat(),
                "end_time": event["end_time"].isoformat(),
                "all_day": event["all_day"],
                "attendees": [
                    {
                        "name": a["display_name"] or a["email"],
                        "status": a["response_status"],
                        "entity_id": str(a["entity_id"]) if a["entity_id"] else None,
                    }
                    for a in attendees
                ],
                "attendee_context": attendee_facts,
            })

        return {
            "status": "success",
            "date": target_date.date().isoformat(),
            "count": len(enriched_events),
            "events": enriched_events,
        }

    return run_async(_get_with_context())


@tool
def calendar_sync(
    user_id: str,
    provider: str = "google",
) -> dict[str, Any]:
    """Trigger a calendar sync for a user.

    Use this tool to refresh calendar data from an external provider.
    The actual sync is performed asynchronously.

    Args:
        user_id: UUID of the user.
        provider: Calendar provider to sync (google, outlook).

    Returns:
        Dictionary with sync status.
    """
    # Note: This would typically trigger an async job via EventBridge or SQS
    # For now, return a placeholder indicating the sync was requested

    return {
        "status": "pending",
        "message": f"Calendar sync requested for {provider}",
        "user_id": user_id,
        "provider": provider,
        "note": "Full sync implementation requires OAuth token refresh and API calls",
    }


@tool
def calendar_create_event(
    user_id: str,
    title: str,
    start_time: str,
    end_time: str,
    description: str | None = None,
    location: str | None = None,
    all_day: bool = False,
    visibility_tier: int = 3,
) -> dict[str, Any]:
    """Create a new calendar event.

    Use this tool to add an event to the user's calendar.

    Args:
        user_id: UUID of the user.
        title: Event title.
        start_time: Start time in ISO format.
        end_time: End time in ISO format.
        description: Optional event description.
        location: Optional event location.
        all_day: Whether this is an all-day event.
        visibility_tier: Access tier 1-4 (default 3).

    Returns:
        Dictionary with the created event details.
    """
    async def _create() -> dict[str, Any]:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)

        result = await execute_one(
            """
            INSERT INTO calendar_events (
                user_id, title, description, location,
                start_time, end_time, all_day, visibility_tier
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, created_at
            """,
            UUID(user_id),
            title,
            description,
            location,
            start,
            end,
            all_day,
            visibility_tier,
        )

        if not result:
            return {"status": "error", "message": "Failed to create event"}

        return {
            "status": "success",
            "event_id": str(result["id"]),
            "title": title,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "created_at": result["created_at"].isoformat(),
        }

    return run_async(_create())

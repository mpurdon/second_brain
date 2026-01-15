"""Scheduler tools for briefings, reminders, and notifications."""

import asyncio
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from strands import tool

from ..database import execute_command, execute_one, execute_query


@tool
def get_today_events(
    user_id: str,
    date_str: str | None = None,
) -> dict[str, Any]:
    """Get calendar events for today or a specific date.

    Args:
        user_id: UUID of the user.
        date_str: Optional date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Dictionary with list of events.
    """
    async def _get_events() -> dict[str, Any]:
        target_date = date.fromisoformat(date_str) if date_str else date.today()
        next_date = target_date + timedelta(days=1)

        # Query calendar events from facts or dedicated calendar table
        events = await execute_query(
            """
            SELECT f.id, f.content, f.metadata, f.recorded_at
            FROM facts f
            WHERE f.owner_id = $1
            AND f.source_type = 'calendar'
            AND (f.metadata->>'event_date')::date = $2
            ORDER BY (f.metadata->>'start_time')::time
            """,
            UUID(user_id),
            target_date,
        )

        return {
            "status": "success",
            "date": target_date.isoformat(),
            "count": len(events),
            "events": [
                {
                    "id": str(e["id"]),
                    "content": e["content"],
                    "metadata": dict(e["metadata"]) if e["metadata"] else {},
                }
                for e in events
            ],
        }

    return asyncio.get_event_loop().run_until_complete(_get_events())


@tool
def get_upcoming_birthdays(
    user_id: str,
    days_ahead: int = 7,
) -> dict[str, Any]:
    """Get upcoming birthdays and anniversaries.

    Args:
        user_id: UUID of the user.
        days_ahead: Number of days to look ahead.

    Returns:
        Dictionary with list of upcoming occasions.
    """
    async def _get_birthdays() -> dict[str, Any]:
        today = date.today()

        # Query entities with birthday/anniversary attributes
        occasions = await execute_query(
            """
            SELECT e.id, e.name, e.entity_type::text,
                   ea.attribute_name, ea.attribute_value
            FROM entities e
            JOIN entity_attributes ea ON ea.entity_id = e.id
            WHERE e.owner_id = $1
            AND ea.attribute_name IN ('birthday', 'anniversary')
            AND (
                -- Match month and day within the next N days
                TO_DATE(
                    EXTRACT(YEAR FROM CURRENT_DATE)::text || '-' ||
                    SUBSTRING(ea.attribute_value FROM 6 FOR 5),
                    'YYYY-MM-DD'
                ) BETWEEN CURRENT_DATE AND CURRENT_DATE + $2
                OR
                -- Also check next year for year-end wrap
                TO_DATE(
                    (EXTRACT(YEAR FROM CURRENT_DATE) + 1)::text || '-' ||
                    SUBSTRING(ea.attribute_value FROM 6 FOR 5),
                    'YYYY-MM-DD'
                ) BETWEEN CURRENT_DATE AND CURRENT_DATE + $2
            )
            ORDER BY
                EXTRACT(MONTH FROM ea.attribute_value::date),
                EXTRACT(DAY FROM ea.attribute_value::date)
            """,
            UUID(user_id),
            days_ahead,
        )

        return {
            "status": "success",
            "days_ahead": days_ahead,
            "count": len(occasions),
            "occasions": [
                {
                    "entity_id": str(o["id"]),
                    "name": o["name"],
                    "entity_type": o["entity_type"],
                    "occasion_type": o["attribute_name"],
                    "date": o["attribute_value"],
                }
                for o in occasions
            ],
        }

    return asyncio.get_event_loop().run_until_complete(_get_birthdays())


@tool
def get_active_reminders(
    user_id: str,
    include_future: bool = False,
) -> dict[str, Any]:
    """Get active reminders for the user.

    Args:
        user_id: UUID of the user.
        include_future: Whether to include reminders not yet due.

    Returns:
        Dictionary with list of reminders.
    """
    async def _get_reminders() -> dict[str, Any]:
        if include_future:
            condition = "r.status IN ('active', 'snoozed')"
        else:
            condition = "r.status = 'active' AND r.next_trigger_at <= NOW()"

        reminders = await execute_query(
            f"""
            SELECT r.id, r.title, r.description, r.trigger_type::text,
                   r.next_trigger_at, r.priority, r.tags,
                   e.name as related_entity_name
            FROM reminders r
            LEFT JOIN entities e ON e.id = r.related_entity_id
            WHERE r.user_id = $1
            AND {condition}
            ORDER BY r.priority DESC, r.next_trigger_at ASC
            LIMIT 50
            """,
            UUID(user_id),
        )

        return {
            "status": "success",
            "count": len(reminders),
            "reminders": [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "description": r["description"],
                    "trigger_type": r["trigger_type"],
                    "next_trigger_at": r["next_trigger_at"].isoformat() if r["next_trigger_at"] else None,
                    "priority": r["priority"],
                    "tags": list(r["tags"]) if r["tags"] else [],
                    "related_entity": r["related_entity_name"],
                }
                for r in reminders
            ],
        }

    return asyncio.get_event_loop().run_until_complete(_get_reminders())


@tool
def get_entity_context(
    user_id: str,
    entity_names: list[str],
) -> dict[str, Any]:
    """Get context about entities (people, organizations) from knowledge base.

    Use this to get background information about people the user is meeting.

    Args:
        user_id: UUID of the user.
        entity_names: List of entity names to look up.

    Returns:
        Dictionary with entity information and related facts.
    """
    async def _get_context() -> dict[str, Any]:
        contexts = []

        for name in entity_names:
            # Find matching entity
            entity = await execute_one(
                """
                SELECT e.id, e.name, e.entity_type::text, e.description,
                       e.metadata, e.aliases
                FROM entities e
                WHERE e.owner_id = $1
                AND (e.name ILIKE $2 OR $2 = ANY(e.aliases))
                LIMIT 1
                """,
                UUID(user_id),
                f"%{name}%",
            )

            if entity:
                # Get recent facts about this entity
                facts = await execute_query(
                    """
                    SELECT f.content, f.importance, f.recorded_at
                    FROM facts f
                    WHERE f.about_entity_id = $1
                    ORDER BY f.importance DESC, f.recorded_at DESC
                    LIMIT 5
                    """,
                    entity["id"],
                )

                # Get attributes
                attributes = await execute_query(
                    """
                    SELECT attribute_name, attribute_value
                    FROM entity_attributes
                    WHERE entity_id = $1
                    AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
                    """,
                    entity["id"],
                )

                contexts.append({
                    "name": entity["name"],
                    "entity_type": entity["entity_type"],
                    "description": entity["description"],
                    "attributes": {a["attribute_name"]: a["attribute_value"] for a in attributes},
                    "recent_facts": [
                        {
                            "content": f["content"],
                            "importance": f["importance"],
                            "recorded_at": f["recorded_at"].isoformat(),
                        }
                        for f in facts
                    ],
                })
            else:
                contexts.append({
                    "name": name,
                    "entity_type": None,
                    "description": f"No information found for {name}",
                    "attributes": {},
                    "recent_facts": [],
                })

        return {
            "status": "success",
            "count": len(contexts),
            "entities": contexts,
        }

    return asyncio.get_event_loop().run_until_complete(_get_context())


@tool
def queue_notification(
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    channel: str = "push",
    reminder_id: str | None = None,
    scheduled_at: str | None = None,
) -> dict[str, Any]:
    """Queue a notification for delivery.

    Args:
        user_id: UUID of the user.
        notification_type: Type (reminder, briefing, calendar, birthday, proactive, system).
        title: Notification title.
        body: Notification body text.
        channel: Delivery channel (push, email, discord, alexa).
        reminder_id: Optional related reminder ID.
        scheduled_at: Optional scheduled time (ISO format). Defaults to now.

    Returns:
        Dictionary with queued notification ID.
    """
    async def _queue() -> dict[str, Any]:
        scheduled = datetime.fromisoformat(scheduled_at) if scheduled_at else datetime.utcnow()
        reminder_uuid = UUID(reminder_id) if reminder_id else None

        result = await execute_one(
            """
            INSERT INTO notifications (
                user_id, notification_type, title, body, channel,
                reminder_id, scheduled_at
            ) VALUES ($1, $2::notification_type, $3, $4, $5::notification_channel, $6, $7)
            RETURNING id
            """,
            UUID(user_id),
            notification_type,
            title,
            body,
            channel,
            reminder_uuid,
            scheduled,
        )

        return {
            "status": "success",
            "notification_id": str(result["id"]),
            "scheduled_at": scheduled.isoformat(),
        }

    return asyncio.get_event_loop().run_until_complete(_queue())


@tool
def save_briefing(
    user_id: str,
    briefing_type: str,
    content: str,
    events_count: int = 0,
    reminders_count: int = 0,
    birthdays_count: int = 0,
    facts_count: int = 0,
) -> dict[str, Any]:
    """Save a generated briefing to history.

    Args:
        user_id: UUID of the user.
        briefing_type: Type of briefing (morning, evening, meeting_prep).
        content: The generated briefing content.
        events_count: Number of events included.
        reminders_count: Number of reminders included.
        birthdays_count: Number of birthdays included.
        facts_count: Number of facts included.

    Returns:
        Dictionary with briefing ID.
    """
    async def _save() -> dict[str, Any]:
        result = await execute_one(
            """
            INSERT INTO briefing_history (
                user_id, briefing_type, content,
                included_events, included_reminders,
                included_birthdays, included_facts
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, generated_at
            """,
            UUID(user_id),
            briefing_type,
            content,
            events_count,
            reminders_count,
            birthdays_count,
            facts_count,
        )

        return {
            "status": "success",
            "briefing_id": str(result["id"]),
            "generated_at": result["generated_at"].isoformat(),
        }

    return asyncio.get_event_loop().run_until_complete(_save())


@tool
def mark_reminder_triggered(
    reminder_id: str,
) -> dict[str, Any]:
    """Mark a reminder as triggered after evaluation.

    Args:
        reminder_id: UUID of the reminder.

    Returns:
        Dictionary with status.
    """
    async def _mark() -> dict[str, Any]:
        result = await execute_one(
            """
            UPDATE reminders
            SET status = CASE
                    WHEN trigger_type = 'recurring' THEN 'active'
                    ELSE 'triggered'
                END,
                last_triggered_at = NOW(),
                next_trigger_at = CASE
                    WHEN trigger_type = 'recurring' THEN
                        calculate_next_trigger(trigger_type, trigger_config, NOW())
                    ELSE NULL
                END
            WHERE id = $1
            RETURNING id, status::text, next_trigger_at
            """,
            UUID(reminder_id),
        )

        if not result:
            return {"status": "error", "message": "Reminder not found"}

        return {
            "status": "success",
            "reminder_id": reminder_id,
            "new_status": result["status"],
            "next_trigger_at": result["next_trigger_at"].isoformat() if result["next_trigger_at"] else None,
        }

    return asyncio.get_event_loop().run_until_complete(_mark())

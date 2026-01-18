"""Annual milestone detection and calendar event creation.

Automatically creates recurring calendar events for birthdays, death anniversaries,
wedding anniversaries, and other annual milestones.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from .database import execute_one, execute_query, run_async


# Milestone patterns to detect
MILESTONE_PATTERNS = {
    # Birthday patterns
    "birthday": [
        # "Name was born on Date" or "Name born on Date" (single name, not capturing "was")
        r"^(\w+)\s+(?:was\s+)?born\s+(?:on\s+)?(.+)",
        # "First Last was born on Date"
        r"^(\w+\s+\w+)\s+was\s+born\s+(?:on\s+)?(.+)",
        r"(\w+(?:\s+\w+)?)'s\s+birthday\s+is\s+(.+)",
        r"birthday[:\s]+(\w+(?:\s+\w+)?)\s+(?:on\s+)?(.+)",
        # Handle LLM-reformulated facts like "Tom is my brother, born on December 25"
        r"^(\w+)\s+is\s+(?:my|the|a)\s+\w+,?\s*born\s+(?:on\s+)?(.+)",
        # Handle "Name, born on Date" format
        r"^(\w+),\s*born\s+(?:on\s+)?(.+)",
    ],
    # Death/memorial patterns
    "memorial": [
        r"(\w+(?:\s+\w+)?)\s+(?:passed away|died)\s+(?:on\s+)?(.+)",
        r"(\w+(?:\s+\w+)?)\s+(?:passed away|died)\s+(?:in\s+)?(\d{4})",
    ],
    # Wedding anniversary patterns
    "anniversary": [
        r"(\w+(?:\s+\w+)?)\s+(?:and\s+)?(\w+(?:\s+\w+)?)\s+(?:got\s+)?married\s+(?:on\s+)?(.+)",
        r"(?:wedding|marriage)\s+anniversary[:\s]+(.+)",
        r"(\w+(?:\s+\w+)?)\s+(?:and\s+)?(\w+(?:\s+\w+)?)'s\s+anniversary\s+is\s+(.+)",
    ],
}

# Month name to number mapping
MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def parse_date_from_text(text: str) -> tuple[int | None, int | None, int | None]:
    """Parse month, day, and optionally year from text.

    Args:
        text: Text containing a date (e.g., "May 6, 2017", "September 20th")

    Returns:
        Tuple of (month, day, year) where any can be None if not found.
    """
    text = text.lower().strip()

    # Pattern: "Month Day, Year" or "Month Day Year" or "Month Day"
    for month_name, month_num in MONTH_MAP.items():
        # Match "May 6, 2017" or "May 6th, 2017" or "May 6"
        pattern = rf"\b{month_name}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?"
        match = re.search(pattern, text)
        if match:
            day = int(match.group(1))
            year = int(match.group(2)) if match.group(2) else None
            return month_num, day, year

    # Pattern: "MM/DD/YYYY" or "MM-DD-YYYY"
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = int(match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return month, day, year

    # Pattern: "YYYY-MM-DD"
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return month, day, year

    return None, None, None


def detect_milestone(content: str, fact_type: str | None = None) -> dict | None:
    """Detect if a fact contains an annual milestone.

    Args:
        content: The fact content to analyze.
        fact_type: Optional fact type hint from LLM extraction.

    Returns:
        Dictionary with milestone details or None if not a milestone.
    """
    content_lower = content.lower()

    # Check for birthday indicators
    if any(kw in content_lower for kw in ["born", "birthday"]):
        for pattern in MILESTONE_PATTERNS["birthday"]:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                groups = match.groups()
                entity_name = groups[0].strip()
                date_text = groups[1].strip() if len(groups) > 1 else ""

                month, day, year = parse_date_from_text(date_text)
                if month and day:
                    return {
                        "type": "birthday",
                        "entity_name": entity_name,
                        "month": month,
                        "day": day,
                        "year": year,
                        "title": f"{entity_name}'s Birthday",
                        "description": f"Annual birthday celebration for {entity_name}",
                    }

    # Check for death/memorial indicators
    if any(kw in content_lower for kw in ["passed away", "died", "death"]):
        for pattern in MILESTONE_PATTERNS["memorial"]:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                groups = match.groups()
                entity_name = groups[0].strip()
                date_text = groups[1].strip() if len(groups) > 1 else ""

                month, day, year = parse_date_from_text(date_text)
                # For deaths, we might only have a year - skip if no month/day
                if month and day:
                    return {
                        "type": "memorial",
                        "entity_name": entity_name,
                        "month": month,
                        "day": day,
                        "year": year,
                        "title": f"Remembering {entity_name}",
                        "description": f"Memorial anniversary for {entity_name}",
                    }

    # Check for wedding/anniversary indicators
    if any(kw in content_lower for kw in ["married", "wedding", "anniversary"]):
        for pattern in MILESTONE_PATTERNS["anniversary"]:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                groups = match.groups()
                # Could be one or two names depending on pattern
                if len(groups) >= 3:
                    name1 = groups[0].strip()
                    name2 = groups[1].strip()
                    date_text = groups[2].strip()
                    title = f"{name1} & {name2}'s Anniversary"
                else:
                    date_text = groups[0].strip()
                    title = "Wedding Anniversary"

                month, day, year = parse_date_from_text(date_text)
                if month and day:
                    return {
                        "type": "anniversary",
                        "month": month,
                        "day": day,
                        "year": year,
                        "title": title,
                        "description": "Annual wedding anniversary celebration",
                    }

    return None


async def create_annual_calendar_event(
    user_id: str,
    milestone: dict,
    entity_id: str | None = None,
    fact_id: str | None = None,
) -> dict:
    """Create a recurring annual calendar event for a milestone.

    Args:
        user_id: The user's database ID.
        milestone: Milestone details from detect_milestone().
        entity_id: Optional entity ID to link.
        fact_id: Optional fact ID that triggered this.

    Returns:
        Dictionary with creation result.
    """
    month = milestone["month"]
    day = milestone["day"]
    title = milestone["title"]
    description = milestone.get("description", "")
    milestone_type = milestone["type"]

    # Calculate the next occurrence of this date
    today = date.today()
    this_year_date = date(today.year, month, day)

    if this_year_date < today:
        # Already passed this year, schedule for next year
        next_occurrence = date(today.year + 1, month, day)
    else:
        next_occurrence = this_year_date

    # Create datetime for all-day event (midnight to midnight)
    start_time = datetime.combine(next_occurrence, datetime.min.time())
    end_time = start_time + timedelta(days=1)

    # RRULE for annual recurrence
    recurrence_rule = f"FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={day}"

    try:
        # Check if this event already exists (avoid duplicates)
        existing = await execute_one(
            """
            SELECT id FROM calendar_events
            WHERE user_id = $1
            AND title = $2
            AND is_recurring = true
            AND recurrence_rule LIKE '%FREQ=YEARLY%'
            """,
            UUID(user_id),
            title,
        )

        if existing:
            return {
                "status": "exists",
                "event_id": str(existing["id"]),
                "message": f"Annual event '{title}' already exists",
            }

        # Create the recurring event
        result = await execute_one(
            """
            INSERT INTO calendar_events (
                user_id, title, description,
                start_time, end_time, all_day,
                is_recurring, recurrence_rule,
                visibility_tier
            )
            VALUES ($1, $2, $3, $4, $5, true, true, $6, 3)
            RETURNING id, created_at
            """,
            UUID(user_id),
            title,
            description,
            start_time,
            end_time,
            recurrence_rule,
        )

        if not result:
            return {"status": "error", "message": "Failed to create calendar event"}

        event_id = str(result["id"])

        # Note: Reminder creation skipped as it uses a different schema now.
        # The calendar event with recurrence_rule handles the annual reminder.

        return {
            "status": "success",
            "event_id": event_id,
            "title": title,
            "next_occurrence": next_occurrence.isoformat(),
            "recurrence": "annual",
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def create_milestone_event_sync(
    user_id: str,
    milestone: dict,
    entity_id: str | None = None,
    fact_id: str | None = None,
) -> dict:
    """Synchronous wrapper for create_annual_calendar_event."""
    return run_async(create_annual_calendar_event(user_id, milestone, entity_id, fact_id))

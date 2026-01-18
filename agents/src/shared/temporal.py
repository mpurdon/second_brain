"""Temporal expression parsing for Second Brain.

Converts natural language time expressions like "this weekend", "next Friday",
"tomorrow" into actual dates.
"""

import re
from datetime import date, datetime, timedelta
from typing import Tuple


# Day name to weekday number (Monday=0, Sunday=6)
DAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

# Month name to number
MONTH_NAMES = {
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


def parse_temporal_expression(text: str, reference_date: date | None = None) -> dict:
    """Parse temporal expressions from text.

    Args:
        text: Text containing temporal expressions
        reference_date: Reference date for relative expressions (defaults to today)

    Returns:
        Dictionary with:
        - valid_from: Start date (date object or None)
        - valid_to: End date (date object or None)
        - temporal_text: The matched temporal expression
        - is_ongoing: Whether this is an ongoing state (no end date)
    """
    if reference_date is None:
        reference_date = date.today()

    text_lower = text.lower()
    result = {
        "valid_from": None,
        "valid_to": None,
        "temporal_text": None,
        "is_ongoing": False,
    }

    # Pattern: "this weekend"
    if "this weekend" in text_lower:
        # Find the coming Saturday
        days_until_saturday = (5 - reference_date.weekday()) % 7
        if days_until_saturday == 0 and reference_date.weekday() == 5:
            # Today is Saturday
            saturday = reference_date
        else:
            saturday = reference_date + timedelta(days=days_until_saturday)
        sunday = saturday + timedelta(days=1)
        result["valid_from"] = saturday
        result["valid_to"] = sunday
        result["temporal_text"] = "this weekend"
        return result

    # Pattern: "next weekend"
    if "next weekend" in text_lower:
        days_until_saturday = (5 - reference_date.weekday()) % 7
        if days_until_saturday == 0:
            days_until_saturday = 7
        saturday = reference_date + timedelta(days=days_until_saturday + 7)
        sunday = saturday + timedelta(days=1)
        result["valid_from"] = saturday
        result["valid_to"] = sunday
        result["temporal_text"] = "next weekend"
        return result

    # Pattern: "today"
    if re.search(r"\btoday\b", text_lower):
        result["valid_from"] = reference_date
        result["valid_to"] = reference_date
        result["temporal_text"] = "today"
        return result

    # Pattern: "tomorrow"
    if re.search(r"\btomorrow\b", text_lower):
        tomorrow = reference_date + timedelta(days=1)
        result["valid_from"] = tomorrow
        result["valid_to"] = tomorrow
        result["temporal_text"] = "tomorrow"
        return result

    # Pattern: "yesterday"
    if re.search(r"\byesterday\b", text_lower):
        yesterday = reference_date - timedelta(days=1)
        result["valid_from"] = yesterday
        result["valid_to"] = yesterday
        result["temporal_text"] = "yesterday"
        return result

    # Pattern: "this week"
    if "this week" in text_lower:
        # Start of week (Monday)
        days_since_monday = reference_date.weekday()
        monday = reference_date - timedelta(days=days_since_monday)
        sunday = monday + timedelta(days=6)
        result["valid_from"] = monday
        result["valid_to"] = sunday
        result["temporal_text"] = "this week"
        return result

    # Pattern: "next week"
    if "next week" in text_lower:
        days_until_monday = (7 - reference_date.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        monday = reference_date + timedelta(days=days_until_monday)
        sunday = monday + timedelta(days=6)
        result["valid_from"] = monday
        result["valid_to"] = sunday
        result["temporal_text"] = "next week"
        return result

    # Pattern: "this/next [day name]" e.g., "this Friday", "next Tuesday"
    for day_name, day_num in DAY_NAMES.items():
        # "this [day]"
        match = re.search(rf"\bthis\s+{day_name}\b", text_lower)
        if match:
            days_ahead = (day_num - reference_date.weekday()) % 7
            target_date = reference_date + timedelta(days=days_ahead)
            result["valid_from"] = target_date
            result["valid_to"] = target_date
            result["temporal_text"] = f"this {day_name}"
            return result

        # "next [day]"
        match = re.search(rf"\bnext\s+{day_name}\b", text_lower)
        if match:
            days_ahead = (day_num - reference_date.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target_date = reference_date + timedelta(days=days_ahead + 7)
            result["valid_from"] = target_date
            result["valid_to"] = target_date
            result["temporal_text"] = f"next {day_name}"
            return result

        # "on [day]" - assumes this week or next occurrence
        match = re.search(rf"\bon\s+{day_name}\b", text_lower)
        if match:
            days_ahead = (day_num - reference_date.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next occurrence if today
            target_date = reference_date + timedelta(days=days_ahead)
            result["valid_from"] = target_date
            result["valid_to"] = target_date
            result["temporal_text"] = f"on {day_name}"
            return result

    # Pattern: "from [date] to [date]" or "[date] - [date]" or "[date]-[date]"
    # e.g., "January 18-19", "Jan 18 to Jan 20", "from Jan 18 to 19"
    date_range_patterns = [
        # "January 18-19" or "January 18 - 19"
        r"(" + "|".join(MONTH_NAMES.keys()) + r")\s+(\d{1,2})\s*[-–]\s*(\d{1,2})(?:,?\s*(\d{4}))?",
        # "Jan 18 to Jan 19" or "January 18 to 19"
        r"(" + "|".join(MONTH_NAMES.keys()) + r")\s+(\d{1,2})\s+to\s+(?:(" + "|".join(MONTH_NAMES.keys()) + r")\s+)?(\d{1,2})(?:,?\s*(\d{4}))?",
        # "from January 18 to 19"
        r"from\s+(" + "|".join(MONTH_NAMES.keys()) + r")\s+(\d{1,2})\s+to\s+(\d{1,2})(?:,?\s*(\d{4}))?",
    ]

    for pattern in date_range_patterns:
        match = re.search(pattern, text_lower)
        if match:
            groups = match.groups()
            month_name = groups[0]
            month = MONTH_NAMES.get(month_name)
            start_day = int(groups[1])

            # Determine end day and potentially different end month
            if len(groups) >= 4 and groups[2] and groups[2] in MONTH_NAMES:
                end_month = MONTH_NAMES.get(groups[2])
                end_day = int(groups[3])
            else:
                end_month = month
                end_day = int(groups[2]) if groups[2] and groups[2].isdigit() else start_day

            # Year
            year = reference_date.year
            for g in groups:
                if g and len(g) == 4 and g.isdigit():
                    year = int(g)
                    break

            try:
                result["valid_from"] = date(year, month, start_day)
                result["valid_to"] = date(year, end_month, end_day)
                result["temporal_text"] = match.group(0)
                return result
            except ValueError:
                pass  # Invalid date, continue

    # Pattern: "[Month] [day]" single date
    single_date_pattern = r"\b(" + "|".join(MONTH_NAMES.keys()) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\b"
    match = re.search(single_date_pattern, text_lower)
    if match:
        month_name = match.group(1)
        month = MONTH_NAMES.get(month_name)
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else reference_date.year

        try:
            target_date = date(year, month, day)
            result["valid_from"] = target_date
            result["valid_to"] = target_date
            result["temporal_text"] = match.group(0)
            return result
        except ValueError:
            pass

    # Pattern: "in [X] days/weeks/months"
    match = re.search(r"in\s+(\d+)\s+(day|days|week|weeks|month|months)", text_lower)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if "day" in unit:
            target_date = reference_date + timedelta(days=amount)
        elif "week" in unit:
            target_date = reference_date + timedelta(weeks=amount)
        elif "month" in unit:
            # Approximate month as 30 days
            target_date = reference_date + timedelta(days=amount * 30)
        result["valid_from"] = target_date
        result["valid_to"] = target_date
        result["temporal_text"] = match.group(0)
        return result

    # Pattern: "[X] days/weeks ago"
    match = re.search(r"(\d+)\s+(day|days|week|weeks)\s+ago", text_lower)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if "day" in unit:
            target_date = reference_date - timedelta(days=amount)
        elif "week" in unit:
            target_date = reference_date - timedelta(weeks=amount)
        result["valid_from"] = target_date
        result["valid_to"] = target_date
        result["temporal_text"] = match.group(0)
        return result

    # Pattern: Check for ongoing states (no end date implied)
    ongoing_patterns = [
        r"\bis\s+away\b",
        r"\bis\s+on\s+vacation\b",
        r"\bis\s+traveling\b",
        r"\bis\s+visiting\b",
        r"\buntil\b",
    ]
    for pattern in ongoing_patterns:
        if re.search(pattern, text_lower):
            result["is_ongoing"] = True
            break

    return result


def resolve_temporal_in_fact(content: str, reference_date: date | None = None) -> Tuple[str, date | None, date | None]:
    """Resolve temporal expressions in a fact and return updated content with dates.

    Args:
        content: The fact content
        reference_date: Reference date for relative expressions

    Returns:
        Tuple of (updated_content, valid_from, valid_to)
        The content may be updated to include the actual dates for clarity.
    """
    if reference_date is None:
        reference_date = date.today()

    parsed = parse_temporal_expression(content, reference_date)

    if parsed["valid_from"] is None:
        return content, None, None

    valid_from = parsed["valid_from"]
    valid_to = parsed["valid_to"]

    # Optionally update content to include actual dates
    # e.g., "Erin is away this weekend" -> "Erin is away this weekend (Jan 18-19, 2026)"
    if parsed["temporal_text"]:
        # Format dates nicely
        if valid_from == valid_to:
            date_str = valid_from.strftime("%b %d, %Y")
        else:
            if valid_from.month == valid_to.month and valid_from.year == valid_to.year:
                date_str = f"{valid_from.strftime('%b %d')}-{valid_to.day}, {valid_from.year}"
            else:
                date_str = f"{valid_from.strftime('%b %d')} - {valid_to.strftime('%b %d, %Y')}"

        # Add date annotation if not already present
        if not re.search(r"\(\w+\s+\d+", content):
            content = content.rstrip(".") + f" ({date_str})"

    return content, valid_from, valid_to

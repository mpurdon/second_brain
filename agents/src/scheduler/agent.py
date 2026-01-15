"""Scheduler Agent - Generates briefings and proactive notifications."""

from datetime import date, datetime
from typing import Any

from strands import Agent

from .prompts import (
    SCHEDULER_AGENT_PROMPT,
    MORNING_BRIEFING_PROMPT,
    EVENING_SUMMARY_PROMPT,
    MEETING_PREP_PROMPT,
)
from ..shared.tools.scheduler import (
    get_today_events,
    get_upcoming_birthdays,
    get_active_reminders,
    get_entity_context,
    queue_notification,
    save_briefing,
    mark_reminder_triggered,
)
from ..shared.tools.calendar import calendar_get_events
from ..shared.tools.database import fact_search
from ..shared.config import BEDROCK_MODELS


def create_scheduler_agent(model_id: str | None = None) -> Agent:
    """Create a Scheduler Agent for briefings and notifications.

    The Scheduler Agent specializes in:
    - Morning briefing generation
    - Evening summary generation
    - Meeting preparation notes
    - Reminder trigger evaluation
    - Notification queuing

    Args:
        model_id: Optional Bedrock model ID. Defaults to Sonnet.

    Returns:
        Configured Scheduler Agent instance.
    """
    return Agent(
        model_id=model_id or BEDROCK_MODELS["sonnet"],
        system_prompt=SCHEDULER_AGENT_PROMPT,
        tools=[
            get_today_events,
            get_upcoming_birthdays,
            get_active_reminders,
            get_entity_context,
            queue_notification,
            save_briefing,
            mark_reminder_triggered,
            calendar_get_events,
            fact_search,
        ],
    )


class SchedulerAgentProcessor:
    """Processor for scheduled tasks and briefing generation."""

    def __init__(self, model_id: str | None = None):
        """Initialize the Scheduler Agent processor.

        Args:
            model_id: Optional Bedrock model ID.
        """
        self.agent = create_scheduler_agent(model_id)

    def generate_morning_briefing(
        self,
        user_id: str,
        family_ids: list[str] | None = None,
        timezone: str = "America/New_York",
        target_date: str | None = None,
    ) -> dict[str, Any]:
        """Generate a comprehensive morning briefing.

        Args:
            user_id: UUID of the user.
            family_ids: Optional list of family IDs.
            timezone: User's timezone.
            target_date: Optional date (YYYY-MM-DD). Defaults to today.

        Returns:
            Dictionary with the morning briefing.
        """
        briefing_date = target_date or date.today().isoformat()

        prompt = MORNING_BRIEFING_PROMPT.format(
            date=briefing_date,
            timezone=timezone,
        )

        prompt += f"""

User ID: {user_id}
Family IDs: {family_ids or []}

Steps to generate the briefing:
1. Use get_today_events to get calendar events
2. Use get_upcoming_birthdays to find birthdays in next 7 days
3. Use get_active_reminders to get due reminders
4. For each meeting attendee, use get_entity_context to get background
5. Use fact_search to find relevant facts for today's activities
6. Compile everything into a scannable morning briefing
7. Use save_briefing to store the generated content
"""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "family_ids": family_ids,
                "operation": "morning_briefing",
            },
        )

        return {
            "status": "success",
            "date": briefing_date,
            "briefing": result.message if hasattr(result, "message") else str(result),
            "type": "morning",
        }

    def generate_evening_summary(
        self,
        user_id: str,
        family_ids: list[str] | None = None,
        timezone: str = "America/New_York",
        target_date: str | None = None,
    ) -> dict[str, Any]:
        """Generate an evening summary.

        Args:
            user_id: UUID of the user.
            family_ids: Optional list of family IDs.
            timezone: User's timezone.
            target_date: Optional date (YYYY-MM-DD). Defaults to today.

        Returns:
            Dictionary with the evening summary.
        """
        summary_date = target_date or date.today().isoformat()

        prompt = EVENING_SUMMARY_PROMPT.format(
            date=summary_date,
            timezone=timezone,
        )

        prompt += f"""

User ID: {user_id}

Steps:
1. Review today's events
2. Check for any pending reminders
3. Preview tomorrow's schedule
4. Compile into a brief summary
5. Save the briefing
"""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "family_ids": family_ids,
                "operation": "evening_summary",
            },
        )

        return {
            "status": "success",
            "date": summary_date,
            "summary": result.message if hasattr(result, "message") else str(result),
            "type": "evening",
        }

    def generate_meeting_prep(
        self,
        user_id: str,
        meeting_title: str,
        meeting_time: str,
        attendees: list[str],
        family_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate meeting preparation notes.

        Args:
            user_id: UUID of the user.
            meeting_title: Title of the meeting.
            meeting_time: Time of the meeting.
            attendees: List of attendee names.
            family_ids: Optional list of family IDs.

        Returns:
            Dictionary with meeting prep notes.
        """
        prompt = MEETING_PREP_PROMPT.format(
            meeting_title=meeting_title,
            meeting_time=meeting_time,
            attendees=", ".join(attendees),
        )

        prompt += f"""

User ID: {user_id}

For each attendee, use get_entity_context to find:
- Their background and role
- Recent interactions
- Relevant facts
- Any pending items

Create actionable meeting prep notes.
"""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "family_ids": family_ids,
                "operation": "meeting_prep",
            },
        )

        return {
            "status": "success",
            "meeting": meeting_title,
            "prep": result.message if hasattr(result, "message") else str(result),
            "type": "meeting_prep",
        }

    def evaluate_reminders(
        self,
        user_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Evaluate pending reminders and trigger notifications.

        Args:
            user_id: UUID of the user.
            limit: Maximum reminders to evaluate.

        Returns:
            Dictionary with evaluation results.
        """
        prompt = f"""Evaluate pending reminders for user {user_id}.

Steps:
1. Use get_active_reminders to get reminders due now
2. For each reminder:
   - Check if it should trigger based on conditions
   - If yes, use queue_notification to queue the notification
   - Use mark_reminder_triggered to update the reminder status
3. Return a summary of what was processed

Limit: {limit} reminders
"""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "operation": "evaluate_reminders",
            },
        )

        return {
            "status": "success",
            "evaluation": result.message if hasattr(result, "message") else str(result),
        }

    def process(
        self,
        operation: str,
        user_id: str,
        family_ids: list[str] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Process a scheduler operation.

        Args:
            operation: Operation type (morning_briefing, evening_summary, meeting_prep, evaluate_reminders).
            user_id: UUID of the user.
            family_ids: Optional list of family IDs.
            **kwargs: Additional operation-specific arguments.

        Returns:
            Dictionary with the result.
        """
        if operation == "morning_briefing":
            return self.generate_morning_briefing(
                user_id=user_id,
                family_ids=family_ids,
                timezone=kwargs.get("timezone", "America/New_York"),
                target_date=kwargs.get("target_date"),
            )
        elif operation == "evening_summary":
            return self.generate_evening_summary(
                user_id=user_id,
                family_ids=family_ids,
                timezone=kwargs.get("timezone", "America/New_York"),
                target_date=kwargs.get("target_date"),
            )
        elif operation == "meeting_prep":
            return self.generate_meeting_prep(
                user_id=user_id,
                family_ids=family_ids,
                meeting_title=kwargs.get("meeting_title", "Meeting"),
                meeting_time=kwargs.get("meeting_time", ""),
                attendees=kwargs.get("attendees", []),
            )
        elif operation == "evaluate_reminders":
            return self.evaluate_reminders(
                user_id=user_id,
                limit=kwargs.get("limit", 50),
            )
        else:
            return {
                "status": "error",
                "message": f"Unknown operation: {operation}",
            }

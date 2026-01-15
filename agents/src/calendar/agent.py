"""Calendar Agent - Handles calendar queries and operations."""

from strands import Agent

from .prompts import CALENDAR_AGENT_PROMPT
from ..shared.tools.calendar import (
    calendar_get_events,
    calendar_get_events_with_context,
    calendar_sync,
    calendar_create_event,
)


def create_calendar_agent(model_id: str | None = None) -> Agent:
    """Create a Calendar Agent for handling calendar operations.

    The Calendar Agent specializes in:
    - Querying upcoming events and schedules
    - Providing meeting context with attendee information
    - Creating new calendar events
    - Triggering calendar syncs with external providers

    Args:
        model_id: Optional Bedrock model ID. Defaults to Claude 3.5 Sonnet.

    Returns:
        Configured Calendar Agent instance.
    """
    return Agent(
        model_id=model_id or "anthropic.claude-3-5-sonnet-20241022-v2:0",
        system_prompt=CALENDAR_AGENT_PROMPT,
        tools=[
            calendar_get_events,
            calendar_get_events_with_context,
            calendar_sync,
            calendar_create_event,
        ],
    )


class CalendarAgentProcessor:
    """Processor for calendar-related requests."""

    def __init__(self, model_id: str | None = None):
        """Initialize the Calendar Agent processor.

        Args:
            model_id: Optional Bedrock model ID.
        """
        self.agent = create_calendar_agent(model_id)

    def get_schedule(
        self,
        user_id: str,
        date: str | None = None,
        days_ahead: int = 7,
    ) -> dict:
        """Get a user's schedule.

        Args:
            user_id: UUID of the user.
            date: Optional start date (YYYY-MM-DD).
            days_ahead: Number of days to look ahead.

        Returns:
            Dictionary with schedule information.
        """
        prompt = f"Get my schedule for the next {days_ahead} days"
        if date:
            prompt = f"Get my schedule starting from {date}"

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "operation": "get_schedule",
            },
        )

        return {
            "status": "success",
            "response": result.message if hasattr(result, "message") else str(result),
        }

    def get_meeting_prep(
        self,
        user_id: str,
        date: str | None = None,
    ) -> dict:
        """Get meeting preparation with context.

        Args:
            user_id: UUID of the user.
            date: Optional date (YYYY-MM-DD). Defaults to today.

        Returns:
            Dictionary with meeting prep information.
        """
        prompt = "Give me a briefing on my meetings today with context about the attendees"
        if date:
            prompt = f"Give me a briefing on my meetings on {date} with context about the attendees"

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "operation": "meeting_prep",
            },
        )

        return {
            "status": "success",
            "response": result.message if hasattr(result, "message") else str(result),
        }

    def create_event(
        self,
        user_id: str,
        title: str,
        start_time: str,
        end_time: str,
        description: str | None = None,
        location: str | None = None,
    ) -> dict:
        """Create a calendar event.

        Args:
            user_id: UUID of the user.
            title: Event title.
            start_time: Start time in ISO format.
            end_time: End time in ISO format.
            description: Optional event description.
            location: Optional event location.

        Returns:
            Dictionary with created event details.
        """
        prompt = f"Create a calendar event titled '{title}' from {start_time} to {end_time}"
        if description:
            prompt += f" with description: {description}"
        if location:
            prompt += f" at location: {location}"

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "operation": "create_event",
            },
        )

        return {
            "status": "success",
            "response": result.message if hasattr(result, "message") else str(result),
        }

    def process(
        self,
        message: str,
        user_id: str,
        family_ids: list[str] | None = None,
    ) -> dict:
        """Process a calendar-related message.

        Args:
            message: User's message.
            user_id: UUID of the user.
            family_ids: Optional list of family IDs for shared calendars.

        Returns:
            Dictionary with agent response.
        """
        result = self.agent(
            message,
            additional_context={
                "user_id": user_id,
                "family_ids": family_ids or [],
                "operation": "general",
            },
        )

        return {
            "status": "success",
            "response": result.message if hasattr(result, "message") else str(result),
        }

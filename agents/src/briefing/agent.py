"""Briefing Agent - Generates personalized morning briefings."""

from datetime import datetime
from strands import Agent

from .prompts import BRIEFING_AGENT_PROMPT
from ..shared.tools.calendar import calendar_get_events, calendar_get_events_with_context
from ..shared.tools.database import fact_search
from ..shared.tools.vector_search import semantic_search


def create_briefing_agent(model_id: str | None = None) -> Agent:
    """Create a Briefing Agent for generating personalized briefings.

    The Briefing Agent specializes in:
    - Morning briefings with schedule overview
    - Meeting preparation summaries
    - Daily task and reminder compilation
    - Contextual information about upcoming interactions

    Args:
        model_id: Optional Bedrock model ID. Defaults to Claude 3.5 Sonnet.

    Returns:
        Configured Briefing Agent instance.
    """
    return Agent(
        model_id=model_id or "anthropic.claude-3-5-sonnet-20241022-v2:0",
        system_prompt=BRIEFING_AGENT_PROMPT,
        tools=[
            calendar_get_events,
            calendar_get_events_with_context,
            fact_search,
            semantic_search,
        ],
    )


class BriefingAgentProcessor:
    """Processor for generating briefings."""

    def __init__(self, model_id: str | None = None):
        """Initialize the Briefing Agent processor.

        Args:
            model_id: Optional Bedrock model ID.
        """
        self.agent = create_briefing_agent(model_id)

    def generate_morning_briefing(
        self,
        user_id: str,
        date: str | None = None,
        include_weather: bool = False,
        timezone: str = "America/New_York",
    ) -> dict:
        """Generate a comprehensive morning briefing.

        Args:
            user_id: UUID of the user.
            date: Optional date (YYYY-MM-DD). Defaults to today.
            include_weather: Whether to include weather information.
            timezone: User's timezone for time formatting.

        Returns:
            Dictionary with the morning briefing.
        """
        target_date = date or datetime.now().strftime("%Y-%m-%d")

        prompt = f"""Generate my morning briefing for {target_date}.

Include:
1. Today's calendar overview - all events for the day
2. Key meetings with attendee context (who am I meeting and what do I know about them?)
3. Any important facts or reminders relevant to today
4. Available time blocks for focused work

Format it in a clear, scannable way I can quickly read in the morning."""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "date": target_date,
                "timezone": timezone,
                "operation": "morning_briefing",
            },
        )

        return {
            "status": "success",
            "date": target_date,
            "briefing": result.message if hasattr(result, "message") else str(result),
            "type": "morning",
        }

    def generate_meeting_prep(
        self,
        user_id: str,
        meeting_title: str | None = None,
        date: str | None = None,
    ) -> dict:
        """Generate meeting preparation notes.

        Args:
            user_id: UUID of the user.
            meeting_title: Optional specific meeting to prepare for.
            date: Optional date to look for meetings.

        Returns:
            Dictionary with meeting prep information.
        """
        if meeting_title:
            prompt = f"Prepare me for my meeting: '{meeting_title}'. Include context about attendees and relevant facts from my knowledge base."
        else:
            target_date = date or datetime.now().strftime("%Y-%m-%d")
            prompt = f"Prepare me for all my meetings on {target_date}. For each meeting, include context about attendees and any relevant facts."

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "operation": "meeting_prep",
            },
        )

        return {
            "status": "success",
            "prep": result.message if hasattr(result, "message") else str(result),
            "type": "meeting_prep",
        }

    def generate_evening_summary(
        self,
        user_id: str,
        date: str | None = None,
    ) -> dict:
        """Generate an evening summary of the day.

        Args:
            user_id: UUID of the user.
            date: Optional date (YYYY-MM-DD). Defaults to today.

        Returns:
            Dictionary with the evening summary.
        """
        target_date = date or datetime.now().strftime("%Y-%m-%d")

        prompt = f"""Generate my evening summary for {target_date}.

Include:
1. What meetings/events happened today
2. Key takeaways or notes from the day
3. Preview of tomorrow's schedule
4. Any pending items or follow-ups"""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "date": target_date,
                "operation": "evening_summary",
            },
        )

        return {
            "status": "success",
            "date": target_date,
            "summary": result.message if hasattr(result, "message") else str(result),
            "type": "evening",
        }

    def process(
        self,
        message: str,
        user_id: str,
        briefing_type: str = "morning",
    ) -> dict:
        """Process a briefing request.

        Args:
            message: User's message or empty for default briefing.
            user_id: UUID of the user.
            briefing_type: Type of briefing (morning, meeting_prep, evening).

        Returns:
            Dictionary with the briefing.
        """
        if briefing_type == "meeting_prep":
            return self.generate_meeting_prep(user_id)
        elif briefing_type == "evening":
            return self.generate_evening_summary(user_id)
        else:
            return self.generate_morning_briefing(user_id)

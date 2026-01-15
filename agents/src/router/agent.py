"""Router Agent implementation using Strands SDK."""

from typing import Any
from uuid import UUID

from strands import Agent, tool

from .prompts import ROUTER_SYSTEM_PROMPT

# Model IDs for cost optimization
# Haiku: Fast, cheap - good for simple classification
# Sonnet: Balanced - good for complex reasoning
# Opus: Most capable - for complex multi-step tasks
MODELS = {
    "haiku": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "sonnet": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "opus": "anthropic.claude-3-opus-20240229-v1:0",
}

# Default to Haiku for routing (simple classification task)
DEFAULT_ROUTER_MODEL = MODELS["haiku"]


class RouterContext:
    """Context object passed through the routing process."""

    def __init__(
        self,
        user_id: str,
        family_ids: list[str] | None = None,
        device_id: str | None = None,
        conversation_id: str | None = None,
    ):
        self.user_id = user_id
        self.family_ids = family_ids or []
        self.device_id = device_id
        self.conversation_id = conversation_id
        self.extracted_entities: list[dict[str, Any]] = []
        self.extracted_dates: list[dict[str, Any]] = []
        self.intent: str | None = None


@tool
def route_to_ingestion(
    message: str,
    user_id: str,
    extracted_entities: list[dict[str, Any]] | None = None,
    extracted_dates: list[dict[str, Any]] | None = None,
    visibility_tier: int = 3,
) -> dict[str, Any]:
    """Route a request to the Ingestion Agent.

    Use this tool when the user wants to store or remember new information.
    The Ingestion Agent will extract entities, classify the information,
    and store it in the knowledge base.

    Args:
        message: The original user message to process.
        user_id: UUID of the user making the request.
        extracted_entities: Pre-extracted entities from the message.
        extracted_dates: Pre-extracted temporal information.
        visibility_tier: Default visibility tier for stored facts (1-4).

    Returns:
        Dictionary with routing confirmation and handoff details.
    """
    return {
        "status": "routed",
        "target_agent": "ingestion",
        "message": message,
        "context": {
            "user_id": user_id,
            "extracted_entities": extracted_entities or [],
            "extracted_dates": extracted_dates or [],
            "visibility_tier": visibility_tier,
        },
    }


@tool
def route_to_query(
    message: str,
    user_id: str,
    family_ids: list[str] | None = None,
    query_type: str = "general",
) -> dict[str, Any]:
    """Route a request to the Query Agent.

    Use this tool when the user wants to retrieve or search for information.
    The Query Agent will search the knowledge base and synthesize a response.

    Args:
        message: The user's query.
        user_id: UUID of the user making the request.
        family_ids: List of family IDs the user belongs to.
        query_type: Type of query (general, entity, temporal, geographic).

    Returns:
        Dictionary with routing confirmation and handoff details.
    """
    return {
        "status": "routed",
        "target_agent": "query",
        "message": message,
        "context": {
            "user_id": user_id,
            "family_ids": family_ids or [],
            "query_type": query_type,
        },
    }


@tool
def route_to_calendar(
    message: str,
    user_id: str,
    action: str = "query",
) -> dict[str, Any]:
    """Route a request to the Calendar Agent.

    Use this tool when the user wants to check or manage calendar events.

    Args:
        message: The user's calendar-related request.
        user_id: UUID of the user making the request.
        action: Calendar action type (query, create, sync).

    Returns:
        Dictionary with routing confirmation and handoff details.
    """
    return {
        "status": "routed",
        "target_agent": "calendar",
        "message": message,
        "context": {
            "user_id": user_id,
            "action": action,
        },
    }


@tool
def request_clarification(
    original_message: str,
    clarification_question: str,
    possible_intents: list[str],
) -> dict[str, Any]:
    """Request clarification from the user when intent is unclear.

    Use this tool when you cannot determine whether the user wants to
    store information or query existing information.

    Args:
        original_message: The user's original message.
        clarification_question: The question to ask the user.
        possible_intents: List of possible intents to choose from.

    Returns:
        Dictionary with clarification request details.
    """
    return {
        "status": "clarification_needed",
        "original_message": original_message,
        "question": clarification_question,
        "options": possible_intents,
    }


class RouterAgent:
    """Router Agent that classifies intent and routes to specialized agents.

    Uses Haiku by default for cost-efficient classification. Override with
    model_id parameter for more complex routing decisions.
    """

    def __init__(
        self,
        model_id: str | None = None,
    ):
        """Initialize the Router Agent.

        Args:
            model_id: Bedrock model ID to use. Defaults to Haiku for cost efficiency.
        """
        self.model_id = model_id or DEFAULT_ROUTER_MODEL
        self.agent = Agent(
            model=self.model_id,
            system_prompt=ROUTER_SYSTEM_PROMPT,
            tools=[
                route_to_ingestion,
                route_to_query,
                route_to_calendar,
                request_clarification,
            ],
        )

    def process(
        self,
        message: str,
        user_id: str,
        family_ids: list[str] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Process a user message and route to the appropriate agent.

        Args:
            message: The user's message.
            user_id: UUID of the user.
            family_ids: List of family IDs the user belongs to.
            conversation_history: Previous messages in the conversation.

        Returns:
            Dictionary with routing decision and response.
        """
        # Build context-aware prompt
        context_parts = [
            f"User ID: {user_id}",
        ]
        if family_ids:
            context_parts.append(f"Family IDs: {', '.join(family_ids)}")

        context_str = "\n".join(context_parts)

        # Include conversation history if available
        history_str = ""
        if conversation_history:
            history_lines = []
            for msg in conversation_history[-5:]:  # Last 5 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_lines.append(f"{role}: {content}")
            history_str = "\n".join(history_lines)

        full_prompt = f"""
Context:
{context_str}

{"Previous conversation:" + chr(10) + history_str if history_str else ""}

User message: {message}

Analyze this message and route it to the appropriate agent using the available tools.
"""

        # Run the agent
        response = self.agent(full_prompt)

        # Extract the routing result from the response
        return {
            "response": str(response),
            "user_id": user_id,
            "original_message": message,
        }


def create_router_agent(
    model_id: str | None = None,
    use_haiku: bool = True,
) -> RouterAgent:
    """Factory function to create a Router Agent.

    Args:
        model_id: Bedrock model ID to use. If None, uses default based on use_haiku.
        use_haiku: If True (default), use Haiku for cost efficiency.

    Returns:
        Configured RouterAgent instance.
    """
    if model_id is None and not use_haiku:
        model_id = MODELS["sonnet"]
    return RouterAgent(model_id=model_id)

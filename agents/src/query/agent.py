"""Query Agent implementation using Strands SDK."""

from typing import Any

from strands import Agent, tool

from ..shared.tools import (
    calendar_get_events,
    calendar_get_events_with_context,
    calculate_distance,
    entity_get_details,
    entity_search,
    fact_search,
    proximity_search,
    semantic_search,
)
from .prompts import QUERY_SYSTEM_PROMPT


@tool
def analyze_query(
    query: str,
) -> dict[str, Any]:
    """Analyze a user query to determine search strategy.

    Use this tool first to understand what the user is asking
    and plan the search approach.

    Args:
        query: The user's question or search query.

    Returns:
        Dictionary with query analysis and recommended strategies.
    """
    query_lower = query.lower()

    strategies = []
    extracted_info = {}

    # Check for entity-focused queries
    entity_patterns = ["what do i know about", "tell me about", "who is", "what is"]
    for pattern in entity_patterns:
        if pattern in query_lower:
            strategies.append("entity_search")
            # Extract the entity name (simple extraction)
            idx = query_lower.find(pattern)
            remainder = query[idx + len(pattern):].strip().rstrip("?")
            extracted_info["target_entity"] = remainder
            break

    # Check for relationship queries
    relationship_patterns = ["who works at", "who lives", "friends of", "colleagues"]
    if any(pattern in query_lower for pattern in relationship_patterns):
        strategies.append("relationship_search")

    # Check for temporal queries
    temporal_patterns = ["last week", "yesterday", "in 199", "in 200", "when did", "history"]
    if any(pattern in query_lower for pattern in temporal_patterns):
        strategies.append("temporal_search")

    # Check for geographic queries
    geo_patterns = ["near", "close to", "within", "distance", "walking", "nearby"]
    if any(pattern in query_lower for pattern in geo_patterns):
        strategies.append("geographic_search")

    # Check for calendar queries
    calendar_patterns = ["calendar", "schedule", "tomorrow", "this week", "meeting", "appointment"]
    if any(pattern in query_lower for pattern in calendar_patterns):
        strategies.append("calendar_search")

    # Default to semantic search for general queries
    if not strategies:
        strategies.append("semantic_search")

    return {
        "query": query,
        "recommended_strategies": strategies,
        "extracted_info": extracted_info,
    }


@tool
def synthesize_response(
    query: str,
    facts: list[dict[str, Any]] | None = None,
    entities: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    no_results: bool = False,
) -> dict[str, Any]:
    """Synthesize a natural language response from search results.

    Use this tool after gathering search results to create a
    user-friendly response.

    Args:
        query: The original user query.
        facts: List of relevant facts from the knowledge base.
        entities: List of relevant entities found.
        events: List of relevant calendar events.
        no_results: Set to True if no results were found.

    Returns:
        Dictionary with synthesized response.
    """
    if no_results or (not facts and not entities and not events):
        return {
            "response": "I don't have any information about that in my knowledge base. Would you like to tell me about it?",
            "has_results": False,
            "suggestions": ["You can add information by saying 'Remember that...'"],
        }

    response_parts = []
    sources_count = 0

    # Handle entity information
    if entities:
        for entity in entities:
            entity_type = entity.get("entity_type", "item")
            name = entity.get("name", "Unknown")
            response_parts.append(f"About {name} ({entity_type}):")

            if entity.get("attributes"):
                for key, value in entity["attributes"].items():
                    response_parts.append(f"  - {key}: {value}")

            sources_count += 1

    # Handle facts
    if facts:
        if not entities:
            response_parts.append("Here's what I found:")

        for fact in facts[:5]:  # Limit to top 5 facts
            content = fact.get("content", "")
            importance = fact.get("importance", 3)
            recorded = fact.get("recorded_at", "")

            if importance >= 4:
                response_parts.append(f"  - {content} (important)")
            else:
                response_parts.append(f"  - {content}")
            sources_count += 1

        if len(facts) > 5:
            response_parts.append(f"  ... and {len(facts) - 5} more related items")

    # Handle calendar events
    if events:
        if response_parts:
            response_parts.append("")
            response_parts.append("Upcoming events:")
        else:
            response_parts.append("Here are the upcoming events:")

        for event in events[:5]:
            title = event.get("title", "Event")
            start = event.get("start_time", "")
            location = event.get("location", "")

            event_str = f"  - {title}"
            if start:
                # Format the date nicely
                event_str += f" at {start}"
            if location:
                event_str += f" ({location})"
            response_parts.append(event_str)
            sources_count += 1

    return {
        "response": "\n".join(response_parts),
        "has_results": True,
        "sources_count": sources_count,
    }


@tool
def suggest_follow_ups(
    query: str,
    found_entities: list[str] | None = None,
    query_type: str = "general",
) -> dict[str, Any]:
    """Suggest follow-up questions the user might want to ask.

    Use this tool at the end of a response to help guide
    the user's exploration.

    Args:
        query: The original user query.
        found_entities: Names of entities found in the response.
        query_type: Type of query that was processed.

    Returns:
        Dictionary with suggested follow-up questions.
    """
    suggestions = []

    if found_entities:
        for entity in found_entities[:2]:
            suggestions.append(f"Tell me more about {entity}")

    if query_type == "entity_search":
        suggestions.append("What events involve this person?")
        suggestions.append("Who else is connected to them?")
    elif query_type == "calendar_search":
        suggestions.append("What should I know about the attendees?")
        suggestions.append("Are there any conflicts with these events?")
    elif query_type == "geographic_search":
        suggestions.append("Show me on a map")
        suggestions.append("Who else lives nearby?")

    return {
        "suggestions": suggestions[:3],  # Limit to 3 suggestions
    }


class QueryAgent:
    """Agent responsible for answering questions from the knowledge base."""

    def __init__(
        self,
        model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    ):
        """Initialize the Query Agent.

        Args:
            model_id: Bedrock model ID to use for the agent.
        """
        self.model_id = model_id
        self.agent = Agent(
            model=model_id,
            system_prompt=QUERY_SYSTEM_PROMPT,
            tools=[
                # Query analysis
                analyze_query,
                # Search tools (from shared)
                semantic_search,
                fact_search,
                entity_search,
                entity_get_details,
                proximity_search,
                calculate_distance,
                calendar_get_events,
                calendar_get_events_with_context,
                # Response synthesis
                synthesize_response,
                suggest_follow_ups,
            ],
        )

    def process(
        self,
        query: str,
        user_id: str,
        family_ids: list[str] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Process a user query and return relevant information.

        Args:
            query: The user's question or search query.
            user_id: UUID of the user.
            family_ids: List of family IDs the user belongs to.
            conversation_history: Previous messages for context.

        Returns:
            Dictionary with query results and response.
        """
        context_parts = [
            f"User ID: {user_id}",
        ]
        if family_ids:
            context_parts.append(f"Family IDs: {', '.join(family_ids)}")

        context_str = "\n".join(context_parts)

        # Include conversation history for context
        history_str = ""
        if conversation_history:
            history_lines = []
            for msg in conversation_history[-5:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_lines.append(f"{role}: {content}")
            history_str = "\n".join(history_lines)

        prompt = f"""
Context:
{context_str}

{"Previous conversation:" + chr(10) + history_str if history_str else ""}

User question: "{query}"

Process this query by:
1. Analyzing the query to determine the best search strategy
2. Executing the appropriate searches using available tools
3. Synthesizing the results into a helpful response
4. Suggesting relevant follow-up questions

Always respect the user's access permissions - only show information they have access to.
"""

        response = self.agent(prompt)

        return {
            "response": str(response),
            "user_id": user_id,
            "original_query": query,
        }


def create_query_agent(
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
) -> QueryAgent:
    """Factory function to create a Query Agent.

    Args:
        model_id: Bedrock model ID to use.

    Returns:
        Configured QueryAgent instance.
    """
    return QueryAgent(model_id=model_id)

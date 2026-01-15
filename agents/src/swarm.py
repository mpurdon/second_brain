"""Swarm configuration for Second Brain multi-agent system.

This module configures the Strands SDK Swarm pattern for coordinating
multiple specialized agents with defined handoff rules.
"""

from typing import Any

from strands import Agent

from .router import create_router_agent, ROUTER_SYSTEM_PROMPT
from .ingestion import create_ingestion_agent, INGESTION_SYSTEM_PROMPT
from .query import create_query_agent, QUERY_SYSTEM_PROMPT
from .shared.tools import (
    # Database tools
    fact_store,
    fact_search,
    # Vector search tools
    semantic_search,
    generate_embedding,
    store_fact_embedding,
    # Entity tools
    entity_search,
    entity_create,
    entity_get_details,
    entity_link_to_fact,
    # Geographic tools
    proximity_search,
    geocode_address,
    store_entity_location,
    calculate_distance,
    # Calendar tools
    calendar_get_events,
    calendar_get_events_with_context,
    calendar_sync,
    calendar_create_event,
)


# Agent configuration constants
DEFAULT_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
HAIKU_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# Swarm configuration
SWARM_CONFIG = {
    "max_handoffs": 5,
    "timeout_seconds": 30,
    "parallel_execution": False,
}


class SecondBrainSwarm:
    """Multi-agent swarm for the Second Brain system.

    This class coordinates the Router, Ingestion, and Query agents
    using the Strands SDK Swarm pattern.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        classification_model_id: str = HAIKU_MODEL_ID,
    ):
        """Initialize the Second Brain Swarm.

        Args:
            model_id: Primary model for agent reasoning (Sonnet).
            classification_model_id: Faster model for classification (Haiku).
        """
        self.model_id = model_id
        self.classification_model_id = classification_model_id

        # Initialize agents
        self._router = None
        self._ingestion = None
        self._query = None

    @property
    def router(self) -> Agent:
        """Get or create the Router Agent."""
        if self._router is None:
            self._router = create_router_agent(model_id=self.classification_model_id)
        return self._router

    @property
    def ingestion(self) -> Agent:
        """Get or create the Ingestion Agent."""
        if self._ingestion is None:
            self._ingestion = create_ingestion_agent(model_id=self.model_id)
        return self._ingestion

    @property
    def query(self) -> Agent:
        """Get or create the Query Agent."""
        if self._query is None:
            self._query = create_query_agent(model_id=self.model_id)
        return self._query

    def process(
        self,
        message: str,
        user_id: str,
        family_ids: list[str] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        intent: str | None = None,
    ) -> dict[str, Any]:
        """Process a user message through the swarm.

        The swarm coordinates agents to handle the request:
        1. Router classifies intent (if not pre-classified)
        2. Routes to appropriate specialized agent
        3. Specialized agent processes and responds

        Args:
            message: The user's message.
            user_id: UUID of the user.
            family_ids: List of family IDs the user belongs to.
            conversation_history: Previous messages for context.
            intent: Pre-classified intent (skips router if provided).

        Returns:
            Dictionary with processing results.
        """
        handoff_count = 0
        current_agent = "router"
        result = None

        # Track the conversation through the swarm
        swarm_trace = []

        while handoff_count < SWARM_CONFIG["max_handoffs"]:
            if current_agent == "router" and intent is None:
                # Use router to classify and route
                routing_result = self.router.process(
                    message=message,
                    user_id=user_id,
                    family_ids=family_ids,
                    conversation_history=conversation_history,
                )
                swarm_trace.append({
                    "agent": "router",
                    "action": "classify",
                })

                # Parse routing decision from response
                response_text = routing_result.get("response", "").lower()
                if "ingest" in response_text or "store" in response_text or "remember" in response_text:
                    current_agent = "ingestion"
                elif "query" in response_text or "search" in response_text or "find" in response_text:
                    current_agent = "query"
                elif "calendar" in response_text or "schedule" in response_text:
                    current_agent = "query"  # Query agent handles calendar
                else:
                    # Default to query for unknown intents
                    current_agent = "query"

                handoff_count += 1

            elif current_agent == "ingestion" or intent == "ingest":
                # Process with ingestion agent
                result = self.ingestion.process(
                    message=message,
                    user_id=user_id,
                )
                swarm_trace.append({
                    "agent": "ingestion",
                    "action": "process",
                })
                break

            elif current_agent == "query" or intent == "query":
                # Process with query agent
                result = self.query.process(
                    message=message,
                    user_id=user_id,
                    family_ids=family_ids,
                    conversation_history=conversation_history,
                )
                swarm_trace.append({
                    "agent": "query",
                    "action": "process",
                })
                break

            else:
                # Unknown state, break to prevent infinite loop
                break

        if result is None:
            result = {
                "response": "I wasn't able to process that request. Could you try rephrasing?",
                "error": "No agent was able to handle the request",
            }

        # Add swarm metadata to result
        result["swarm_trace"] = swarm_trace
        result["handoff_count"] = handoff_count

        return result


def create_swarm(
    model_id: str = DEFAULT_MODEL_ID,
    classification_model_id: str = HAIKU_MODEL_ID,
) -> SecondBrainSwarm:
    """Factory function to create a Second Brain Swarm.

    Args:
        model_id: Primary model for agent reasoning.
        classification_model_id: Faster model for classification.

    Returns:
        Configured SecondBrainSwarm instance.
    """
    return SecondBrainSwarm(
        model_id=model_id,
        classification_model_id=classification_model_id,
    )


# Convenience function for getting all tools (for AgentCore registration)
def get_all_tools() -> list:
    """Get all available tools for the swarm.

    Returns:
        List of all tool functions.
    """
    return [
        # Database tools
        fact_store,
        fact_search,
        # Vector search tools
        semantic_search,
        generate_embedding,
        store_fact_embedding,
        # Entity tools
        entity_search,
        entity_create,
        entity_get_details,
        entity_link_to_fact,
        # Geographic tools
        proximity_search,
        geocode_address,
        store_entity_location,
        calculate_distance,
        # Calendar tools
        calendar_get_events,
        calendar_get_events_with_context,
        calendar_sync,
        calendar_create_event,
    ]

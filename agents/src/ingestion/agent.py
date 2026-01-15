"""Ingestion Agent implementation using Strands SDK."""

from typing import Any

from strands import Agent, tool

from ..shared.tools import (
    entity_create,
    entity_link_to_fact,
    entity_search,
    fact_store,
    generate_embedding,
    store_fact_embedding,
)
from .prompts import INGESTION_SYSTEM_PROMPT


@tool
def extract_entities(
    message: str,
) -> dict[str, Any]:
    """Extract entities mentioned in a message.

    Use this tool to identify people, organizations, places, projects,
    and events mentioned in user input. Returns a list of extracted entities
    with their types and attributes.

    Args:
        message: The user's message to analyze.

    Returns:
        Dictionary with list of extracted entities.
    """
    # This is a placeholder - the actual extraction is done by the LLM
    # through its natural language understanding
    return {
        "status": "ready",
        "message": message,
        "note": "Use entity_search to find existing entities, entity_create for new ones",
    }


@tool
def classify_visibility(
    content: str,
    context: str | None = None,
) -> dict[str, Any]:
    """Classify the appropriate visibility tier for content.

    Use this tool to determine the default access tier for a fact
    based on its content type.

    Args:
        content: The fact content to classify.
        context: Optional additional context about the content.

    Returns:
        Dictionary with recommended visibility tier and reasoning.
    """
    # Keywords for classification
    tier_1_keywords = [
        "medical", "doctor", "hospital", "health", "diagnosis",
        "financial", "salary", "bank", "debt", "loan", "tax",
        "private", "secret", "confidential", "personal note",
    ]
    tier_2_keywords = [
        "grade", "score", "test result", "preference", "favorite",
        "phone number", "email", "address", "birthday",
    ]
    tier_3_keywords = [
        "event", "recital", "game", "practice", "meeting",
        "school", "activity", "sports", "club",
    ]

    content_lower = content.lower()

    # Check for tier 1 (most private)
    for keyword in tier_1_keywords:
        if keyword in content_lower:
            return {
                "recommended_tier": 1,
                "reasoning": f"Contains sensitive content related to: {keyword}",
                "content_type": "sensitive",
            }

    # Check for tier 2 (personal)
    for keyword in tier_2_keywords:
        if keyword in content_lower:
            return {
                "recommended_tier": 2,
                "reasoning": f"Contains personal information related to: {keyword}",
                "content_type": "personal",
            }

    # Check for tier 3 (events/milestones)
    for keyword in tier_3_keywords:
        if keyword in content_lower:
            return {
                "recommended_tier": 3,
                "reasoning": f"Contains event/activity information related to: {keyword}",
                "content_type": "event",
            }

    # Default to tier 3 for general information
    return {
        "recommended_tier": 3,
        "reasoning": "General information, using default tier",
        "content_type": "general",
    }


@tool
def assign_importance(
    content: str,
    has_deadline: bool = False,
    has_date: bool = False,
) -> dict[str, Any]:
    """Assign an importance score to content.

    Use this tool to determine how important a fact is, which affects
    how prominently it appears in search results and briefings.

    Args:
        content: The fact content to score.
        has_deadline: Whether the fact contains a deadline.
        has_date: Whether the fact contains a specific date.

    Returns:
        Dictionary with importance score (1-5) and reasoning.
    """
    content_lower = content.lower()

    # High importance indicators
    critical_keywords = ["urgent", "emergency", "critical", "asap", "immediately"]
    important_keywords = ["important", "deadline", "due", "must", "required"]

    for keyword in critical_keywords:
        if keyword in content_lower:
            return {
                "importance": 5,
                "reasoning": f"Contains critical indicator: {keyword}",
            }

    for keyword in important_keywords:
        if keyword in content_lower:
            return {
                "importance": 4,
                "reasoning": f"Contains importance indicator: {keyword}",
            }

    if has_deadline:
        return {
            "importance": 4,
            "reasoning": "Contains a deadline",
        }

    if has_date:
        return {
            "importance": 3,
            "reasoning": "Contains a specific date",
        }

    # Default importance
    return {
        "importance": 3,
        "reasoning": "Standard importance level",
    }


@tool
def suggest_tags(
    content: str,
    entity_type: str | None = None,
) -> dict[str, Any]:
    """Suggest tags for content based on analysis.

    Use this tool to get tag suggestions for a fact based on its content
    and any associated entities.

    Args:
        content: The fact content to tag.
        entity_type: Optional entity type if fact is about an entity.

    Returns:
        Dictionary with suggested tag paths.
    """
    tags = []
    content_lower = content.lower()

    # Entity type tags
    if entity_type:
        tags.append(f"entity_type/{entity_type}")

    # Domain detection
    work_keywords = ["work", "office", "meeting", "project", "colleague", "boss"]
    family_keywords = ["family", "mom", "dad", "sister", "brother", "child", "parent"]
    personal_keywords = ["hobby", "favorite", "like", "enjoy", "personal"]

    if any(kw in content_lower for kw in work_keywords):
        tags.append("domain/work")
    if any(kw in content_lower for kw in family_keywords):
        tags.append("domain/family")
    if any(kw in content_lower for kw in personal_keywords):
        tags.append("domain/personal")

    # Temporal tags
    if "birthday" in content_lower or "anniversary" in content_lower:
        tags.append("temporal/anniversary")
    if "deadline" in content_lower or "due" in content_lower:
        tags.append("temporal/deadline")
    if "every" in content_lower or "weekly" in content_lower or "monthly" in content_lower:
        tags.append("temporal/recurring")

    # Priority detection
    if "urgent" in content_lower or "critical" in content_lower:
        tags.append("priority/critical")
    elif "important" in content_lower:
        tags.append("priority/high")

    return {
        "suggested_tags": tags,
        "count": len(tags),
    }


@tool
def confirm_ingestion(
    fact_content: str,
    fact_id: str,
    entities_created: list[str] | None = None,
    entities_linked: list[str] | None = None,
    visibility_tier: int = 3,
    importance: int = 3,
) -> dict[str, Any]:
    """Generate a confirmation message for the user.

    Use this tool after successfully storing a fact to confirm
    what was saved.

    Args:
        fact_content: The stored fact content.
        fact_id: UUID of the stored fact.
        entities_created: Names of any new entities created.
        entities_linked: Names of entities linked to this fact.
        visibility_tier: The visibility tier assigned.
        importance: The importance score assigned.

    Returns:
        Dictionary with confirmation message.
    """
    parts = [f"Got it! I've stored that information."]

    if entities_created:
        parts.append(f"Created new entries for: {', '.join(entities_created)}.")

    if entities_linked:
        parts.append(f"Linked to: {', '.join(entities_linked)}.")

    tier_descriptions = {
        1: "private (only you can see)",
        2: "personal (close family can see)",
        3: "shared (extended family can see)",
        4: "public (anyone in your circle can see)",
    }

    parts.append(f"Visibility: {tier_descriptions.get(visibility_tier, 'standard')}.")

    return {
        "confirmation": " ".join(parts),
        "fact_id": fact_id,
        "summary": {
            "content_preview": fact_content[:100] + "..." if len(fact_content) > 100 else fact_content,
            "visibility_tier": visibility_tier,
            "importance": importance,
            "entities_created": entities_created or [],
            "entities_linked": entities_linked or [],
        },
    }


class IngestionAgent:
    """Agent responsible for processing and storing new facts."""

    def __init__(
        self,
        model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    ):
        """Initialize the Ingestion Agent.

        Args:
            model_id: Bedrock model ID to use for the agent.
        """
        self.model_id = model_id
        self.agent = Agent(
            model=model_id,
            system_prompt=INGESTION_SYSTEM_PROMPT,
            tools=[
                # Extraction and classification tools
                extract_entities,
                classify_visibility,
                assign_importance,
                suggest_tags,
                # Storage tools (from shared)
                fact_store,
                store_fact_embedding,
                entity_search,
                entity_create,
                entity_link_to_fact,
                # Confirmation
                confirm_ingestion,
            ],
        )

    def process(
        self,
        message: str,
        user_id: str,
        owner_type: str = "user",
        owner_id: str | None = None,
        source_type: str = "voice",
        default_visibility: int | None = None,
    ) -> dict[str, Any]:
        """Process a message and store extracted facts.

        Args:
            message: The user's message to process.
            user_id: UUID of the user performing the action.
            owner_type: Type of owner (user or family).
            owner_id: UUID of the owner (user_id if user, family_id if family).
                     Defaults to user_id if not specified.
            source_type: Source of the message (voice, text, import).
            default_visibility: Override default visibility tier.

        Returns:
            Dictionary with processing results.
        """
        # Default owner_id to user_id if not specified
        actual_owner_id = owner_id or user_id

        context_parts = [
            f"User ID: {user_id}",
            f"Owner Type: {owner_type}",
            f"Owner ID: {actual_owner_id}",
            f"Source: {source_type}",
        ]
        if default_visibility:
            context_parts.append(f"Default Visibility Tier: {default_visibility}")

        context_str = "\n".join(context_parts)

        prompt = f"""
Context:
{context_str}

User wants to store this information:
"{message}"

Process this message by:
1. Extracting any entities mentioned (people, places, organizations, etc.)
2. Classifying the appropriate visibility tier
3. Assigning an importance score
4. Suggesting relevant tags
5. Storing the fact in the knowledge base
6. Creating any new entities if needed
7. Linking entities to the fact
8. Generating and storing the embedding for semantic search
9. Confirming what was stored

Use the available tools to complete each step.
"""

        response = self.agent(prompt)

        return {
            "response": str(response),
            "user_id": user_id,
            "original_message": message,
        }


def create_ingestion_agent(
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
) -> IngestionAgent:
    """Factory function to create an Ingestion Agent.

    Args:
        model_id: Bedrock model ID to use.

    Returns:
        Configured IngestionAgent instance.
    """
    return IngestionAgent(model_id=model_id)

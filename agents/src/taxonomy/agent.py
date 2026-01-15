"""Taxonomy Agent - Manages tags and classification evolution."""

from strands import Agent

from .prompts import TAXONOMY_AGENT_PROMPT, TAXONOMY_ANALYSIS_PROMPT, BATCH_TAGGING_PROMPT
from ..shared.tools.taxonomy import (
    tag_cooccurrence_analysis,
    untagged_facts_analysis,
    tag_hierarchy_analysis,
    suggest_tags_for_fact,
    propose_taxonomy_changes,
)
from ..shared.tools.database import fact_search


def create_taxonomy_agent(model_id: str | None = None) -> Agent:
    """Create a Taxonomy Agent for managing tags and classification.

    The Taxonomy Agent specializes in:
    - Detecting patterns in tag usage
    - Finding gaps in fact categorization
    - Proposing taxonomy improvements
    - Suggesting tags for untagged facts

    Args:
        model_id: Optional Bedrock model ID. Defaults to Claude 3.5 Sonnet.

    Returns:
        Configured Taxonomy Agent instance.
    """
    return Agent(
        model_id=model_id or "anthropic.claude-3-5-sonnet-20241022-v2:0",
        system_prompt=TAXONOMY_AGENT_PROMPT,
        tools=[
            tag_cooccurrence_analysis,
            untagged_facts_analysis,
            tag_hierarchy_analysis,
            suggest_tags_for_fact,
            propose_taxonomy_changes,
            fact_search,
        ],
    )


class TaxonomyAgentProcessor:
    """Processor for taxonomy analysis and improvement."""

    def __init__(self, model_id: str | None = None):
        """Initialize the Taxonomy Agent processor.

        Args:
            model_id: Optional Bedrock model ID.
        """
        self.agent = create_taxonomy_agent(model_id)

    def analyze_taxonomy(
        self,
        user_id: str,
        family_ids: list[str] | None = None,
    ) -> dict:
        """Perform comprehensive taxonomy analysis.

        Analyzes tag usage patterns, coverage, and structure to provide
        actionable recommendations for taxonomy improvement.

        Args:
            user_id: UUID of the user.
            family_ids: Optional list of family IDs.

        Returns:
            Dictionary with analysis results and recommendations.
        """
        prompt = f"""{TAXONOMY_ANALYSIS_PROMPT}

Analyze the taxonomy for user {user_id}.
Family IDs: {family_ids or 'None'}

Use all available analysis tools to build a complete picture:
1. First check tag coverage with untagged_facts_analysis
2. Then analyze co-occurrence patterns
3. Review the hierarchy structure
4. Finally, propose specific improvements

Summarize findings with clear action items."""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "family_ids": family_ids,
                "operation": "taxonomy_analysis",
            },
        )

        return {
            "status": "success",
            "analysis": result.message if hasattr(result, "message") else str(result),
            "type": "taxonomy_analysis",
        }

    def suggest_batch_tags(
        self,
        user_id: str,
        family_ids: list[str] | None = None,
        limit: int = 20,
    ) -> dict:
        """Suggest tags for multiple untagged facts.

        Reviews untagged facts and generates tag suggestions for each,
        prioritized by fact importance.

        Args:
            user_id: UUID of the user.
            family_ids: Optional list of family IDs.
            limit: Maximum facts to process.

        Returns:
            Dictionary with tag suggestions per fact.
        """
        prompt = f"""{BATCH_TAGGING_PROMPT}

Find untagged facts for user {user_id} (limit: {limit}).
Family IDs: {family_ids or 'None'}

For each untagged fact found:
1. Get tag suggestions using suggest_tags_for_fact
2. Compile results with confidence scores

Present results as a prioritized list of facts with their suggested tags."""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "family_ids": family_ids,
                "operation": "batch_tagging",
            },
        )

        return {
            "status": "success",
            "suggestions": result.message if hasattr(result, "message") else str(result),
            "type": "batch_tagging",
        }

    def get_tag_suggestions(
        self,
        user_id: str,
        fact_id: str,
        family_ids: list[str] | None = None,
    ) -> dict:
        """Get tag suggestions for a specific fact.

        Args:
            user_id: UUID of the user.
            fact_id: UUID of the fact.
            family_ids: Optional list of family IDs.

        Returns:
            Dictionary with tag suggestions.
        """
        prompt = f"""Suggest appropriate tags for fact {fact_id}.

Use the suggest_tags_for_fact tool to get initial suggestions,
then refine them based on the fact content and entity context.

Provide your top 3-5 tag recommendations with explanations."""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "fact_id": fact_id,
                "family_ids": family_ids,
                "operation": "tag_suggestion",
            },
        )

        return {
            "status": "success",
            "fact_id": fact_id,
            "suggestions": result.message if hasattr(result, "message") else str(result),
            "type": "tag_suggestion",
        }

    def propose_improvements(
        self,
        user_id: str,
        family_ids: list[str] | None = None,
    ) -> dict:
        """Propose taxonomy structure improvements.

        Analyzes the current taxonomy and proposes specific improvements
        such as merging tags, creating hierarchies, or cleanup.

        Args:
            user_id: UUID of the user.
            family_ids: Optional list of family IDs.

        Returns:
            Dictionary with improvement proposals.
        """
        prompt = f"""Propose taxonomy improvements for user {user_id}.
Family IDs: {family_ids or 'None'}

Use propose_taxonomy_changes to get initial proposals,
then analyze each one and provide:
1. Clear action steps
2. Expected impact
3. Any risks or considerations

Prioritize high-impact, low-risk changes."""

        result = self.agent(
            prompt,
            additional_context={
                "user_id": user_id,
                "family_ids": family_ids,
                "operation": "propose_improvements",
            },
        )

        return {
            "status": "success",
            "proposals": result.message if hasattr(result, "message") else str(result),
            "type": "taxonomy_improvements",
        }

    def process(
        self,
        message: str,
        user_id: str,
        family_ids: list[str] | None = None,
    ) -> dict:
        """Process a taxonomy-related request.

        Args:
            message: User's message or request.
            user_id: UUID of the user.
            family_ids: Optional list of family IDs.

        Returns:
            Dictionary with the response.
        """
        result = self.agent(
            message,
            additional_context={
                "user_id": user_id,
                "family_ids": family_ids,
                "operation": "general",
            },
        )

        return {
            "status": "success",
            "response": result.message if hasattr(result, "message") else str(result),
            "type": "general",
        }

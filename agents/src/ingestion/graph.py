"""Fast parallel ingestion pipeline.

This module implements a parallel processing pipeline for fact ingestion,
using an LLM for intelligent fact extraction with regex fallback.

Performance: ~1-2 seconds with LLM extraction.
"""

import asyncio
import json
import re
import time
from typing import Any
from uuid import UUID

import boto3

from ..shared.database import execute_one, execute_command, get_or_create_user


# ============================================================================
# LLM-based Fact Extraction
# ============================================================================

FACT_EXTRACTION_PROMPT = """Extract structured facts from the user's message. Identify:
1. Relationships (family, work, social connections)
2. Events with dates (births, deaths, marriages, jobs, trips, etc.)
3. Attributes (preferences, traits, contact info)
4. Temporal information (when things happen)

Today's date is: {today_date}

Return JSON with this exact structure:
{{
  "facts": [
    {{
      "content": "human-readable fact statement WITH dates resolved",
      "type": "relationship|event|attribute|temporal|general",
      "entity_name": "name of person/thing or null",
      "entity_type": "person|organization|place|event|null",
      "relationship": "relationship type or null (e.g., father, granddaughter, friend, boss)",
      "event_type": "birth|death|marriage|graduation|job_start|trip|vacation|null",
      "valid_from": "YYYY-MM-DD or null - when this fact starts being true",
      "valid_to": "YYYY-MM-DD or null - when this fact stops being true"
    }}
  ],
  "confidence": 0.0-1.0
}}

IMPORTANT Rules for temporal information:
- Convert relative dates to actual dates using today's date ({today_date})
- "this weekend" = the coming Saturday and Sunday
- "next week" = the Monday through Sunday after this week
- "tomorrow" = the day after today
- Keep temporal context WITH the main fact - don't split into separate facts
- For trips/vacations, include location AND dates in the same fact
- Set valid_from and valid_to for time-bound facts

Example: If today is 2026-01-18 and user says "Erin is away at Blue Mountain this weekend":
{{
  "facts": [
    {{
      "content": "Erin is away at Blue Mountain (Jan 18-19, 2026)",
      "type": "temporal",
      "entity_name": "Erin",
      "entity_type": "person",
      "event_type": "trip",
      "valid_from": "2026-01-18",
      "valid_to": "2026-01-19"
    }}
  ],
  "confidence": 0.95
}}

Other rules:
- Split compound statements into separate atomic facts EXCEPT temporal context
- "my daughter's daughter" = granddaughter, "my son's son" = grandson
- Normalize relationship names (dad->father, mom->mother, etc.)
- For deaths, create fact like "Person passed away in YEAR"
- For relationships, create fact like "Person is my relationship"

User message: {message}

Return only valid JSON, no other text."""


async def extract_facts_with_llm(message: str) -> dict:
    """Use LLM to extract structured facts from a message.

    Returns:
        Dictionary with 'facts' list and 'confidence' score.
    """
    from datetime import date
    today_date = date.today().isoformat()

    try:
        bedrock = boto3.client("bedrock-runtime")

        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-3-haiku-20240307-v1:0",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": [
                    {
                        "role": "user",
                        "content": FACT_EXTRACTION_PROMPT.format(
                            message=message,
                            today_date=today_date
                        )
                    }
                ]
            }),
        )

        body_bytes = response["body"].read()
        result = json.loads(body_bytes.decode("utf-8") if isinstance(body_bytes, bytes) else body_bytes)

        # Extract content from Anthropic response format
        content_list = result.get("content", [])
        if not content_list:
            return {"facts": [], "confidence": 0.0, "source": "llm_empty"}

        first_content = content_list[0]
        if isinstance(first_content, dict):
            content = first_content.get("text", "{}")
        else:
            content = str(first_content)

        # Parse the JSON response
        try:
            # Handle potential markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                parts = content.split("```")
                if len(parts) >= 2:
                    content = parts[1]

            # Try to find JSON object in the content
            content = content.strip()
            if not content.startswith("{"):
                # Look for JSON object in the text
                start_idx = content.find("{")
                if start_idx != -1:
                    # Find the matching closing brace
                    brace_count = 0
                    end_idx = start_idx
                    for i, char in enumerate(content[start_idx:], start_idx):
                        if char == "{":
                            brace_count += 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                end_idx = i + 1
                                break
                    content = content[start_idx:end_idx]

            extracted = json.loads(content)
            facts = extracted.get("facts", [])
            confidence = extracted.get("confidence", 0.5)

            # Validate facts structure
            valid_facts = []
            for fact in facts:
                if isinstance(fact, dict) and "content" in fact:
                    valid_facts.append(fact)

            return {
                "facts": valid_facts,
                "confidence": float(confidence) if valid_facts else 0.0,
                "source": "llm"
            }
        except json.JSONDecodeError:
            return {"facts": [], "confidence": 0.0, "source": "llm_parse_error"}

    except Exception as e:
        print(f"LLM extraction error: {type(e).__name__}: {e}")
        return {"facts": [], "confidence": 0.0, "source": "llm_error"}


# ============================================================================
# Deterministic Classification Functions (no LLM needed)
# ============================================================================

def classify_visibility(content: str) -> dict:
    """Classify visibility tier based on keywords."""
    content_lower = content.lower()

    # Tier 1: Most private (medical, financial, secrets)
    tier_1_keywords = [
        "medical", "doctor", "hospital", "health", "diagnosis", "prescription",
        "financial", "salary", "bank", "debt", "loan", "tax", "income",
        "private", "secret", "confidential", "password", "ssn", "social security",
    ]
    for keyword in tier_1_keywords:
        if keyword in content_lower:
            return {"tier": 1, "reason": f"sensitive: {keyword}"}

    # Tier 2: Personal (preferences, contact info)
    tier_2_keywords = [
        "grade", "score", "test result", "preference", "favorite",
        "phone number", "email", "address", "birthday", "age",
    ]
    for keyword in tier_2_keywords:
        if keyword in content_lower:
            return {"tier": 2, "reason": f"personal: {keyword}"}

    return {"tier": 3, "reason": "default"}


def assign_importance(content: str) -> dict:
    """Assign importance score based on keywords."""
    content_lower = content.lower()

    if any(kw in content_lower for kw in ["urgent", "emergency", "critical", "asap", "immediately"]):
        return {"importance": 5, "reason": "critical"}

    if any(kw in content_lower for kw in ["important", "deadline", "due", "must", "required"]):
        return {"importance": 4, "reason": "important"}

    # Check for dates
    date_patterns = [
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b",
    ]
    for pattern in date_patterns:
        if re.search(pattern, content_lower):
            return {"importance": 3, "reason": "has date"}

    return {"importance": 3, "reason": "default"}


def suggest_tags(content: str) -> list[str]:
    """Suggest tags based on content analysis."""
    content_lower = content.lower()
    tags = []

    # Domain detection
    if any(kw in content_lower for kw in ["work", "office", "meeting", "project", "colleague", "boss", "client"]):
        tags.append("domain/work")
    if any(kw in content_lower for kw in ["family", "mom", "dad", "sister", "brother", "child", "parent", "spouse", "wife", "husband"]):
        tags.append("domain/family")
    if any(kw in content_lower for kw in ["hobby", "favorite", "like", "enjoy", "personal", "i am", "i'm"]):
        tags.append("domain/personal")

    # Temporal tags
    if any(kw in content_lower for kw in ["birthday", "anniversary"]):
        tags.append("temporal/anniversary")
    if any(kw in content_lower for kw in ["deadline", "due"]):
        tags.append("temporal/deadline")

    if not tags:
        tags.append("domain/personal")

    return tags


def extract_entities(content: str) -> list[dict]:
    """Extract entities using regex patterns."""
    entities = []

    # Extract capitalized names (two or more capitalized words)
    name_pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"
    names = re.findall(name_pattern, content)
    for name in names:
        if name.lower() not in ["second brain", "my second"]:
            entities.append({"name": name, "type": "person"})

    return entities


# ============================================================================
# Relationship Bidirectional Mapping
# ============================================================================

# Symmetric relationships - the inverse is the same
SYMMETRIC_RELATIONSHIPS = {
    "cousin", "friend", "sibling", "neighbor", "colleague", "coworker",
    "spouse", "partner", "roommate", "classmate",
}

# Asymmetric relationships - maps relationship to its inverse
RELATIONSHIP_INVERSES = {
    # Parent/Child
    "father": "child",
    "mother": "child",
    "parent": "child",
    "dad": "child",
    "mom": "child",
    "child": "parent",
    "son": "parent",
    "daughter": "parent",
    # Grandparent/Grandchild
    "grandfather": "grandchild",
    "grandmother": "grandchild",
    "grandpa": "grandchild",
    "grandma": "grandchild",
    "grandparent": "grandchild",
    "grandson": "grandparent",
    "granddaughter": "grandparent",
    "grandchild": "grandparent",
    # Great-grandparent
    "great-grandfather": "great-grandchild",
    "great-grandmother": "great-grandchild",
    "great-grandchild": "great-grandparent",
    # Aunt/Uncle and Niece/Nephew
    "uncle": "niece/nephew",
    "aunt": "niece/nephew",
    "niece": "aunt/uncle",
    "nephew": "aunt/uncle",
    # In-laws
    "father-in-law": "child-in-law",
    "mother-in-law": "child-in-law",
    "son-in-law": "parent-in-law",
    "daughter-in-law": "parent-in-law",
    "brother-in-law": "sibling-in-law",
    "sister-in-law": "sibling-in-law",
    # Spouse (symmetric but listed for clarity)
    "wife": "husband",
    "husband": "wife",
    # Work relationships
    "boss": "employee",
    "manager": "direct report",
    "employee": "boss",
    "direct report": "manager",
}


def get_inverse_relationship(relationship: str) -> str | None:
    """Get the inverse of a relationship.

    Args:
        relationship: The relationship type (e.g., "cousin", "father")

    Returns:
        The inverse relationship, or the same relationship if symmetric,
        or None if no inverse is defined.
    """
    rel_lower = relationship.lower()

    # Check if symmetric
    if rel_lower in SYMMETRIC_RELATIONSHIPS:
        return relationship

    # Check for defined inverse
    if rel_lower in RELATIONSHIP_INVERSES:
        return RELATIONSHIP_INVERSES[rel_lower]

    return None


# Relationship keywords that indicate family/personal connections
RELATIONSHIP_PATTERNS = {
    # Compound/possessive relationships (must be checked first - more specific)
    # "my daughter's daughter is Isla" -> granddaughter
    r"\bmy\s+(?:daughter|son)'s\s+(?:daughter)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("granddaughter", "person"),
    r"\bmy\s+(?:daughter|son)'s\s+(?:son)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("grandson", "person"),
    r"\bmy\s+(?:daughter|son)'s\s+(?:child|kid)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("grandchild", "person"),
    # "my mother's mother is Mary" -> grandmother
    r"\bmy\s+(?:mother|father)'s\s+(?:mother|mom)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("great-grandmother", "person"),
    r"\bmy\s+(?:mother|father)'s\s+(?:father|dad)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("great-grandfather", "person"),
    # "my brother's wife is Sarah" -> sister-in-law
    r"\bmy\s+(?:brother)'s\s+(?:wife|spouse)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("sister-in-law", "person"),
    r"\bmy\s+(?:sister)'s\s+(?:husband|spouse)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("brother-in-law", "person"),
    # "my brother's/sister's child" -> niece/nephew
    r"\bmy\s+(?:brother|sister)'s\s+(?:daughter)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("niece", "person"),
    r"\bmy\s+(?:brother|sister)'s\s+(?:son)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("nephew", "person"),
    # Direct family relationships (use negative lookbehind to avoid matching within compound patterns)
    r"(?<!'s )(?:my\s+)?(?:father|dad|daddy)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("father", "person"),
    r"(?<!'s )(?:my\s+)?(?:mother|mom|mommy|mum)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("mother", "person"),
    r"(?<!'s )(?:my\s+)?(?:brother)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("brother", "person"),
    r"(?<!'s )(?:my\s+)?(?:sister)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("sister", "person"),
    r"(?<!'s )(?:my\s+)?(?:son)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("son", "person"),
    r"(?<!'s )(?:my\s+)?(?:daughter)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("daughter", "person"),
    r"(?<!'s )(?:my\s+)?(?:wife|spouse)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("wife", "person"),
    r"(?<!'s )(?:my\s+)?(?:husband|spouse)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("husband", "person"),
    # Grandchildren (direct patterns)
    r"\b(?:my\s+)?(?:granddaughter)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("granddaughter", "person"),
    r"\b(?:my\s+)?(?:grandson)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("grandson", "person"),
    r"\b(?:my\s+)?(?:grandchild)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("grandchild", "person"),
    # Grandparents
    r"\b(?:my\s+)?(?:grandfather|grandpa)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("grandfather", "person"),
    r"\b(?:my\s+)?(?:grandmother|grandma)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("grandmother", "person"),
    # Extended family
    r"\b(?:my\s+)?(?:uncle)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("uncle", "person"),
    r"\b(?:my\s+)?(?:aunt)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("aunt", "person"),
    r"\b(?:my\s+)?(?:cousin)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("cousin", "person"),
    r"\b(?:my\s+)?(?:niece)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("niece", "person"),
    r"\b(?:my\s+)?(?:nephew)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("nephew", "person"),
    # Work/social relationships
    r"\b(?:my\s+)?(?:friend)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("friend", "person"),
    r"\b(?:my\s+)?(?:boss|manager)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("boss", "person"),
    r"\b(?:my\s+)?(?:colleague|coworker)\s+(?:is\s+|named\s+)?([A-Z][a-z]+)": ("colleague", "person"),
    # Also match "a father Lindsay" pattern
    r"\ba\s+(?:father|dad)\s+(?:named\s+)?([A-Z][a-z]+)": ("father", "person"),
    r"\ba\s+(?:mother|mom)\s+(?:named\s+)?([A-Z][a-z]+)": ("mother", "person"),
}

# Temporal event patterns that indicate something happened
# Note: These patterns use "that" connector to match phrases like "father Lindsay that died"
TEMPORAL_EVENT_PATTERNS = [
    (r"([A-Z][a-z]+)\s+(?:that\s+)?(?:died|passed away|passed)\s+(?:in\s+)?(\d{4})", "death", "{name} passed away in {year}"),
    (r"([A-Z][a-z]+)\s+(?:that\s+)?(?:who\s+)?(?:died|passed away|passed)\s+(?:in\s+)?(\d{4})", "death", "{name} passed away in {year}"),
    (r"([A-Z][a-z]+)\s+was\s+born\s+(?:in\s+)?(\d{4})", "birth", "{name} was born in {year}"),
    (r"([A-Z][a-z]+)\s+(?:started|began)\s+(?:working|work)\s+(?:at\s+)?(.+?)(?:\s+in\s+(\d{4}))?", "career", "{name} started working at {place}"),
    (r"([A-Z][a-z]+)\s+(?:married|got married)\s+(?:in\s+)?(\d{4})?", "marriage", "{name} got married"),
    (r"([A-Z][a-z]+)\s+(?:retired)\s+(?:in\s+)?(\d{4})?", "retirement", "{name} retired"),
    (r"([A-Z][a-z]+)\s+(?:graduated)\s+(?:from\s+)?(.+?)(?:\s+in\s+(\d{4}))?", "education", "{name} graduated"),
]


def split_into_facts_regex(content: str) -> list[dict]:
    """Regex-based fallback for fact extraction.

    Used when LLM extraction fails or has low confidence.

    Returns:
        List of fact dictionaries with content and metadata.
    """
    facts = []
    seen_facts = set()  # Track fact content to avoid duplicates
    entities_found = {}  # Track entities and their relationships

    # Step 1: Extract relationships (e.g., "my father Lindsay", "a father Lindsay")
    for pattern, (relationship, entity_type) in RELATIONSHIP_PATTERNS.items():
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            name = match.group(1)
            if name and name[0].isupper():
                fact_content = f"{name} is my {relationship}"
                if fact_content not in seen_facts:
                    seen_facts.add(fact_content)
                    entities_found[name] = {
                        "relationship": relationship,
                        "type": entity_type,
                    }
                    facts.append({
                        "content": fact_content,
                        "type": "relationship",
                        "entity_name": name,
                        "entity_type": entity_type,
                        "relationship": relationship,
                    })

    # Step 2: Extract temporal events (e.g., "died in 2012")
    for pattern, event_type, template in TEMPORAL_EVENT_PATTERNS:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            name = match.group(1)
            if name and name[0].isupper():
                # Build the fact content
                if event_type == "death":
                    year = match.group(2)
                    fact_content = f"{name} passed away in {year}"
                    if fact_content not in seen_facts:
                        seen_facts.add(fact_content)
                        facts.append({
                            "content": fact_content,
                            "type": "event",
                            "entity_name": name,
                            "event_type": event_type,
                            "year": year,
                        })
                elif event_type == "birth":
                    year = match.group(2)
                    fact_content = f"{name} was born in {year}"
                    if fact_content not in seen_facts:
                        seen_facts.add(fact_content)
                        facts.append({
                            "content": fact_content,
                            "type": "event",
                            "entity_name": name,
                            "event_type": event_type,
                            "year": year,
                        })
                elif event_type in ("marriage", "retirement"):
                    year = match.group(2) if len(match.groups()) > 1 else None
                    fact_content = f"{name} {event_type}d" + (f" in {year}" if year else "")
                    if fact_content not in seen_facts:
                        seen_facts.add(fact_content)
                        facts.append({
                            "content": fact_content,
                            "type": "event",
                            "entity_name": name,
                            "event_type": event_type,
                            "year": year,
                        })

    # Step 3: If no structured facts found, treat the whole message as one fact
    if not facts:
        facts.append({
            "content": content,
            "type": "general",
            "entity_name": None,
        })

    return facts


# Confidence threshold for using LLM results
LLM_CONFIDENCE_THRESHOLD = 0.7


async def split_into_facts(content: str) -> tuple[list[dict], str]:
    """Split a complex statement into multiple atomic facts using LLM with regex fallback.

    Uses an LLM for intelligent extraction, falling back to regex patterns
    if LLM fails or has low confidence.

    Examples:
        "I had a father Lindsay that died in 2012" ->
        [
            {"content": "Lindsay is my father", "type": "relationship", ...},
            {"content": "Lindsay passed away in 2012", "type": "event", ...}
        ]

    Returns:
        Tuple of (facts list, extraction source: "llm" or "regex")
    """
    # Try LLM extraction first
    llm_result = await extract_facts_with_llm(content)

    if llm_result["facts"] and llm_result["confidence"] >= LLM_CONFIDENCE_THRESHOLD:
        # LLM extraction successful with high confidence
        return llm_result["facts"], "llm"

    # Fall back to regex if LLM fails or has low confidence
    regex_facts = split_into_facts_regex(content)
    return regex_facts, "regex"


def extract_entities_with_relationships(content: str) -> list[dict]:
    """Extract entities with their relationships to the user.

    Returns entities with relationship metadata for creating proper entity records.
    """
    entities = []
    seen_names = set()

    # Extract from relationship patterns
    for pattern, (relationship, entity_type) in RELATIONSHIP_PATTERNS.items():
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            name = match.group(1)
            if name and name[0].isupper() and name not in seen_names:
                seen_names.add(name)
                entities.append({
                    "name": name,
                    "type": entity_type,
                    "relationship": relationship,
                })

    # Also extract from temporal events (in case entity not in relationship pattern)
    for pattern, event_type, _ in TEMPORAL_EVENT_PATTERNS:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            name = match.group(1)
            if name and name[0].isupper() and name not in seen_names:
                seen_names.add(name)
                entities.append({
                    "name": name,
                    "type": "person",
                    "relationship": None,
                })

    # Fall back to simple capitalized name extraction
    name_pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b"
    for match in re.finditer(name_pattern, content):
        name = match.group(1)
        if name not in seen_names and name.lower() not in ["second brain", "my second", "i"]:
            # Check it's not a common word
            common_words = {"The", "This", "That", "What", "When", "Where", "How", "Why"}
            if name not in common_words:
                seen_names.add(name)
                entities.append({
                    "name": name,
                    "type": "person",
                    "relationship": None,
                })

    return entities


# ============================================================================
# Async Database Operations
# ============================================================================

async def store_fact(
    message: str,
    user_id: str,
    source: str,
    visibility: int,
    importance: int,
) -> dict:
    """Store the fact in the database."""
    try:
        db_user_id, _ = await get_or_create_user(user_id, source)

        result = await execute_one(
            """
            INSERT INTO facts (
                content, owner_type, owner_id, created_by,
                importance, visibility_tier, source
            ) VALUES ($1, 'user', $2, $2, $3, $4, $5::fact_source)
            RETURNING id
            """,
            message,
            UUID(db_user_id),
            importance,
            visibility,
            source if source in ("voice", "text", "import", "calendar", "inferred") else "text",
        )

        if not result:
            return {"status": "error", "message": "Failed to store fact"}

        return {"status": "success", "fact_id": str(result["id"])}

    except Exception as e:
        return {"status": "error", "message": str(e)}


async def store_embedding(fact_id: str, content: str) -> dict:
    """Generate and store embedding for the fact."""
    try:
        bedrock = boto3.client("bedrock-runtime")

        response = bedrock.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            body=json.dumps({"inputText": content}),
        )

        result = json.loads(response["body"].read())
        embedding = result["embedding"]

        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        await execute_command(
            """
            UPDATE facts
            SET embedding = $1::vector
            WHERE id = $2
            """,
            embedding_str,
            UUID(fact_id),
        )

        return {"status": "success", "dimensions": len(embedding)}

    except Exception as e:
        return {"status": "error", "message": str(e)}


async def apply_tags(fact_id: str, tags: list[str]) -> dict:
    """Apply tags to the fact."""
    try:
        applied = 0
        for tag_path in tags:
            result = await execute_command(
                """
                INSERT INTO fact_tags (fact_id, tag_id)
                SELECT $1, id FROM tags WHERE path = $2
                ON CONFLICT DO NOTHING
                """,
                UUID(fact_id),
                tag_path,
            )
            if "INSERT" in result:
                applied += 1

        return {"status": "success", "applied": applied}

    except Exception as e:
        return {"status": "error", "message": str(e)}


async def create_or_get_entity(
    name: str,
    entity_type: str,
    db_user_id: str,
    relationship: str | None = None,
) -> dict:
    """Create an entity or get existing one, updating relationship if provided."""
    try:
        # Check if entity already exists for this user
        existing = await execute_one(
            """
            SELECT id, name, metadata FROM entities
            WHERE normalized_name = lower($1)
            AND owner_type = 'user' AND owner_id = $2
            """,
            name,
            UUID(db_user_id),
        )

        if existing:
            # Update metadata with relationship if provided and different
            if relationship:
                raw_metadata = existing.get("metadata")
                if raw_metadata is None:
                    current_metadata = {}
                elif isinstance(raw_metadata, dict):
                    current_metadata = raw_metadata
                else:
                    try:
                        current_metadata = json.loads(str(raw_metadata)) if raw_metadata else {}
                    except Exception:
                        current_metadata = {}

                current_rel = current_metadata.get("relationship_to_user")
                if current_rel != relationship:
                    current_metadata["relationship_to_user"] = relationship
                    await execute_command(
                        """
                        UPDATE entities SET metadata = $1::jsonb, updated_at = NOW()
                        WHERE id = $2
                        """,
                        json.dumps(current_metadata),
                        existing["id"],
                    )
            return {
                "status": "existing",
                "entity_id": str(existing["id"]),
                "name": existing["name"],
            }

        # Create new entity with relationship metadata
        metadata = {}
        if relationship:
            metadata["relationship_to_user"] = relationship

        result = await execute_one(
            """
            INSERT INTO entities (entity_type, name, owner_type, owner_id, created_by, metadata)
            VALUES ($1::entity_type, $2, 'user', $3, $3, $4::jsonb)
            RETURNING id, normalized_name
            """,
            entity_type,
            name,
            UUID(db_user_id),
            json.dumps(metadata),
        )

        if not result:
            return {"status": "error", "message": "Failed to create entity"}

        return {
            "status": "created",
            "entity_id": str(result["id"]),
            "name": name,
            "normalized_name": result["normalized_name"],
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


async def create_reverse_relationship_fact(
    entity_name: str,
    user_name: str | None,
    relationship: str,
    db_user_id: str,
    source: str,
    original_entity_id: str | None,
) -> dict:
    """Create a reverse relationship fact for bidirectional mapping.

    For example, if we store "Sharon is Jenny's cousin", this creates
    "Jenny is Sharon's cousin".

    Args:
        entity_name: Name of the entity in the original fact (e.g., "Sharon")
        user_name: Name of the user if known (e.g., "Jenny"), or None for "the user"
        relationship: The original relationship (e.g., "cousin")
        db_user_id: Database user ID
        source: Source of the fact
        original_entity_id: Entity ID of the original entity

    Returns:
        Dictionary with result status.
    """
    inverse_rel = get_inverse_relationship(relationship)
    if not inverse_rel:
        return {"status": "skipped", "reason": "no inverse relationship defined"}

    # Build the reverse fact content
    # "Sharon is Jenny's cousin" -> "Jenny is Sharon's cousin"
    if user_name:
        reverse_content = f"{user_name} is {entity_name}'s {inverse_rel}"
    else:
        # Use generic phrasing when we don't know the user's name
        reverse_content = f"The user is {entity_name}'s {inverse_rel}"

    try:
        # Store the reverse fact, linked to the original entity
        result = await execute_one(
            """
            INSERT INTO facts (
                content, owner_type, owner_id, created_by,
                importance, visibility_tier, source, about_entity_id
            ) VALUES ($1, 'user', $2, $2, 3, 3, $3::fact_source, $4)
            RETURNING id
            """,
            reverse_content,
            UUID(db_user_id),
            source if source in ("voice", "text", "import", "calendar", "inferred") else "inferred",
            UUID(original_entity_id) if original_entity_id else None,
        )

        if not result:
            return {"status": "error", "message": "Failed to store reverse fact"}

        # Generate embedding for the reverse fact
        await store_embedding(str(result["id"]), reverse_content)

        return {
            "status": "success",
            "fact_id": str(result["id"]),
            "content": reverse_content,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


async def link_entity_to_fact(fact_id: str, entity_id: str, role: str = "subject") -> dict:
    """Link an entity to a fact."""
    try:
        await execute_command(
            """
            INSERT INTO entity_mentions (fact_id, entity_id, role, confidence)
            VALUES ($1, $2, $3::mention_role, 1.0)
            ON CONFLICT DO NOTHING
            """,
            UUID(fact_id),
            UUID(entity_id),
            role,
        )
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def store_fact_with_entity(
    content: str,
    db_user_id: str,
    source: str,
    visibility: int,
    importance: int,
    entity_id: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> dict:
    """Store a fact and optionally link it to an entity.

    Args:
        content: The fact content.
        db_user_id: Database user ID.
        source: Source of the fact.
        visibility: Visibility tier.
        importance: Importance level.
        entity_id: Optional entity ID to link.
        valid_from: Optional start date (YYYY-MM-DD) when fact becomes true.
        valid_to: Optional end date (YYYY-MM-DD) when fact stops being true.
    """
    from datetime import date as date_type

    # Parse dates if provided as strings
    parsed_valid_from = None
    parsed_valid_to = None
    if valid_from:
        try:
            parsed_valid_from = date_type.fromisoformat(valid_from)
        except (ValueError, TypeError):
            pass
    if valid_to:
        try:
            parsed_valid_to = date_type.fromisoformat(valid_to)
        except (ValueError, TypeError):
            pass

    try:
        result = await execute_one(
            """
            INSERT INTO facts (
                content, owner_type, owner_id, created_by,
                importance, visibility_tier, source, about_entity_id,
                valid_from, valid_to
            ) VALUES ($1, 'user', $2, $2, $3, $4, $5::fact_source, $6, $7, $8)
            RETURNING id
            """,
            content,
            UUID(db_user_id),
            importance,
            visibility,
            source if source in ("voice", "text", "import", "calendar", "inferred") else "text",
            UUID(entity_id) if entity_id else None,
            parsed_valid_from,
            parsed_valid_to,
        )

        if not result:
            return {"status": "error", "message": "Failed to store fact"}

        return {"status": "success", "fact_id": str(result["id"])}

    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================================
# Main Pipeline
# ============================================================================

async def run_ingestion_pipeline(
    message: str,
    user_id: str,
    source: str = "text",
) -> dict[str, Any]:
    """Run the parallel ingestion pipeline with LLM-based fact splitting.

    Pipeline structure:
    1. Split message into atomic facts (LLM with regex fallback)
    2. Extract entities from facts
    3. Create/get entities in database
    4. Store each fact with entity links
    5. Generate embeddings in parallel
    6. Build confirmation

    Args:
        message: The user's message to store.
        user_id: User ID (Cognito sub, Discord ID, etc.)
        source: Source of the message.

    Returns:
        Dictionary with processing results.
    """
    start_time = time.time()

    # Step 1: Get database user ID
    try:
        db_user_id, _ = await get_or_create_user(user_id, source)
    except Exception as e:
        return {
            "response": f"Sorry, I couldn't identify your account: {str(e)}",
            "success": False,
            "execution_time_ms": int((time.time() - start_time) * 1000),
        }

    # Step 2: Split message into atomic facts (LLM with regex fallback)
    facts_to_store, extraction_source = await split_into_facts(message)

    # Step 3: Extract entities from facts
    # When using LLM, entities come from the facts themselves
    # When using regex, use the regex-based entity extraction
    if extraction_source == "llm":
        # Build entities from LLM-extracted facts
        entities = []
        seen_names = set()
        for fact in facts_to_store:
            entity_name = fact.get("entity_name")
            if entity_name and entity_name not in seen_names:
                seen_names.add(entity_name)
                entities.append({
                    "name": entity_name,
                    "type": fact.get("entity_type", "person"),
                    "relationship": fact.get("relationship"),
                })
    else:
        # Regex fallback - use original entity extraction
        entities = extract_entities_with_relationships(message)

    # Step 4: Create entities in database (parallel)
    entity_map = {}  # name -> entity_id
    entity_tasks = []
    for entity in entities:
        task = create_or_get_entity(
            name=entity["name"],
            entity_type=entity["type"],
            db_user_id=db_user_id,
            relationship=entity.get("relationship"),
        )
        entity_tasks.append((entity["name"], task))

    if entity_tasks:
        entity_results = await asyncio.gather(*[t[1] for t in entity_tasks])
        for (name, _), result in zip(entity_tasks, entity_results):
            if result.get("entity_id"):
                entity_map[name] = result["entity_id"]

    # Step 5: Store each fact (with entity links)
    stored_facts = []
    for fact in facts_to_store:
        # Classify this specific fact
        visibility = classify_visibility(fact["content"])["tier"]
        importance = assign_importance(fact["content"])["importance"]
        tags = suggest_tags(fact["content"])

        # Get entity ID if fact is about an entity
        entity_id = None
        if fact.get("entity_name") and fact["entity_name"] in entity_map:
            entity_id = entity_map[fact["entity_name"]]

        # Store the fact (with temporal dates if present)
        store_result = await store_fact_with_entity(
            content=fact["content"],
            db_user_id=db_user_id,
            source=source,
            visibility=visibility,
            importance=importance,
            entity_id=entity_id,
            valid_from=fact.get("valid_from"),
            valid_to=fact.get("valid_to"),
        )

        if store_result.get("fact_id"):
            stored_facts.append({
                "fact_id": store_result["fact_id"],
                "content": fact["content"],
                "type": fact.get("type", "general"),
                "relationship": fact.get("relationship"),
                "entity_name": fact.get("entity_name"),
                "visibility": visibility,
                "importance": importance,
                "tags": tags,
                "entity_id": entity_id,
            })

    if not stored_facts:
        return {
            "response": "Sorry, I couldn't save that information.",
            "success": False,
            "execution_time_ms": int((time.time() - start_time) * 1000),
        }

    # Step 6: Generate embeddings and apply tags in parallel
    embedding_tasks = []
    tag_tasks = []
    for fact in stored_facts:
        embedding_tasks.append(store_embedding(fact["fact_id"], fact["content"]))
        tag_tasks.append(apply_tags(fact["fact_id"], fact["tags"]))

    await asyncio.gather(*embedding_tasks, *tag_tasks)

    # Step 6.5: Create reverse relationship facts for bidirectional mapping
    # e.g., "Sharon is my cousin" also creates "I am Sharon's cousin"
    reverse_facts_created = []
    for fact in stored_facts:
        if fact.get("type") == "relationship" and fact.get("relationship") and fact.get("entity_name"):
            # Get the user's name if we have an entity for them
            # For now, we'll use a generic approach
            reverse_result = await create_reverse_relationship_fact(
                entity_name=fact["entity_name"],
                user_name=None,  # Could look up user's name from their profile
                relationship=fact["relationship"],
                db_user_id=db_user_id,
                source="inferred",
                original_entity_id=fact.get("entity_id"),
            )
            if reverse_result.get("status") == "success":
                reverse_facts_created.append(reverse_result)

    # Step 6.7: Detect and create annual milestone events (birthdays, anniversaries, etc.)
    from ..shared.milestones import detect_milestone, create_annual_calendar_event

    milestone_events_created = []
    for fact in stored_facts:
        milestone = detect_milestone(fact["content"], fact.get("type"))
        if milestone:
            try:
                event_result = await create_annual_calendar_event(
                    user_id=db_user_id,
                    milestone=milestone,
                    entity_id=fact.get("entity_id"),
                    fact_id=fact.get("fact_id"),
                )
                if event_result.get("status") == "success":
                    milestone_events_created.append(event_result)
            except Exception:
                pass  # Silently skip milestone event creation on error

    # Step 7: Build confirmation
    execution_time = int((time.time() - start_time) * 1000)

    tier_names = {1: "private", 2: "personal", 3: "shared", 4: "public"}

    # Build user-friendly response
    if len(stored_facts) == 1:
        parts = ["Got it! I've saved that."]
    else:
        parts = [f"Got it! I've saved {len(stored_facts)} facts:"]
        for i, fact in enumerate(stored_facts[:3], 1):
            # Truncate long facts
            content_preview = fact["content"][:50] + "..." if len(fact["content"]) > 50 else fact["content"]
            parts.append(f"  {i}. {content_preview}")
        if len(stored_facts) > 3:
            parts.append(f"  ...and {len(stored_facts) - 3} more.")

    # Mention entities if created
    created_entities = [e["name"] for e in entities if e.get("relationship")]
    if created_entities:
        parts.append(f"Created entries for: {', '.join(created_entities)}.")

    # Mention milestone calendar events if created
    if milestone_events_created:
        event_titles = [e.get("title", "event") for e in milestone_events_created]
        parts.append(f"Added to calendar: {', '.join(event_titles)} (annual).")

    # Mention visibility
    primary_visibility = stored_facts[0]["visibility"]
    parts.append(f"Visibility: {tier_names.get(primary_visibility, 'shared')}.")

    return {
        "response": "\n".join(parts) if len(stored_facts) > 1 else " ".join(parts),
        "success": True,
        "fact_ids": [f["fact_id"] for f in stored_facts],
        "facts_stored": len(stored_facts),
        "entities_created": [{"name": e["name"], "relationship": e.get("relationship")} for e in entities],
        "extraction_source": extraction_source,  # "llm" or "regex"
        "execution_time_ms": execution_time,
    }


class GraphIngestionPipeline:
    """High-performance ingestion pipeline.

    Uses LLM for intelligent fact extraction with regex fallback for reliability.
    """

    def process(
        self,
        message: str,
        user_id: str,
        source: str = "text",
    ) -> dict[str, Any]:
        """Process a message through the parallel ingestion pipeline.

        Args:
            message: The user's message to store.
            user_id: User ID (Cognito sub, Discord ID, etc.)
            source: Source of the message (voice, text, discord, etc.)

        Returns:
            Dictionary with processing results.
        """
        return asyncio.run(run_ingestion_pipeline(message, user_id, source))

# Strands Agent Architecture Design

**Version:** 1.0
**Date:** January 2025
**Status:** Draft

---

## Overview

This document defines the agent architecture for the Second Brain application using Strands SDK. The system uses specialized agents that collaborate via the Swarm pattern to handle user queries, fact ingestion, proactive notifications, and calendar management.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RUST LAMBDA LAYER                                 │
│                     (Request validation, routing)                           │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AGENTCORE RUNTIME                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         ROUTER AGENT                                 │   │
│  │                    (Entry point for all requests)                    │   │
│  └────────────────────────────┬────────────────────────────────────────┘   │
│                               │                                             │
│         ┌─────────────────────┼─────────────────────┐                      │
│         │                     │                     │                      │
│         ▼                     ▼                     ▼                      │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                 │
│  │  INGESTION  │      │    QUERY    │      │  CALENDAR   │                 │
│  │    AGENT    │      │    AGENT    │      │    AGENT    │                 │
│  └─────────────┘      └─────────────┘      └─────────────┘                 │
│                               │                                             │
│                               │ (Swarm handoff if needed)                   │
│                               ▼                                             │
│                       ┌─────────────┐                                       │
│                       │  SCHEDULER  │                                       │
│                       │    AGENT    │                                       │
│                       └─────────────┘                                       │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                           SHARED TOOLS                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │ DB Tools │ │ Vector   │ │ Entity   │ │ Geo      │ │ Calendar │         │
│  │          │ │ Search   │ │ Extract  │ │ Tools    │ │ Sync     │         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘         │
│                                                                             │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      RDS PostgreSQL + Bedrock                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Agent Definitions

### 1. Router Agent

**Purpose:** Entry point that classifies requests and routes to specialized agents.

```python
# agents/src/router/agent.py

from strands import Agent
from strands.multiagent import Swarm

ROUTER_SYSTEM_PROMPT = """You are the Router Agent for a personal knowledge management system called Second Brain.

Your role is to:
1. Understand the user's intent from their message
2. Route to the appropriate specialized agent using handoff

## Request Classification

Classify each request into ONE of these categories:

### INGESTION (→ ingestion_agent)
- User wants to store/remember information
- Keywords: "remember", "save", "note that", "store", "record"
- Examples:
  - "Remember that John's birthday is March 15th"
  - "Note that Emma has a dentist appointment Thursday"
  - "Save that I worked at Acme Corp from 1995 to 1998"

### QUERY (→ query_agent)
- User wants to retrieve information or ask questions
- Keywords: "what", "who", "when", "where", "tell me", "find", "search"
- Examples:
  - "What do I know about John?"
  - "Who did I work with at Acme?"
  - "When is Emma's school play?"
  - "Which of Emma's friends live nearby?"

### CALENDAR (→ calendar_agent)
- User wants calendar information or to create events
- Keywords: "calendar", "schedule", "meeting", "appointment", "today", "tomorrow", "this week"
- Examples:
  - "What's on my calendar today?"
  - "Schedule a meeting with Sarah"
  - "When is my next dentist appointment?"

### BRIEFING (→ scheduler_agent)
- User wants their morning briefing or summary
- Keywords: "briefing", "summary", "what's happening", "overview"
- Examples:
  - "Give me my morning briefing"
  - "What do I need to know today?"

## Instructions

1. Analyze the user's message
2. Classify into one of the categories above
3. Use handoff_to_agent to route to the appropriate agent
4. Include relevant context in the handoff message

IMPORTANT: You are ONLY a router. Do not attempt to answer questions yourself.
Always hand off to a specialized agent.
"""

def create_router_agent() -> Agent:
    return Agent(
        name="router",
        system_prompt=ROUTER_SYSTEM_PROMPT,
        # Tools will be added by Swarm (handoff tools)
    )
```

### 2. Ingestion Agent

**Purpose:** Processes new facts, extracts entities, classifies visibility, and stores in database.

```python
# agents/src/ingestion/agent.py

from strands import Agent

INGESTION_SYSTEM_PROMPT = """You are the Ingestion Agent for Second Brain, responsible for processing and storing new information.

## Your Responsibilities

1. **Parse the user's input** to extract structured facts
2. **Identify entities** (people, places, organizations, projects, events)
3. **Extract temporal information** (dates, time ranges, recurrence)
4. **Classify visibility tier** based on content type
5. **Generate tags** for categorization
6. **Store the fact** in the database

## Entity Extraction

Look for and extract:
- **People**: Names, relationships, roles
- **Organizations**: Companies, schools, institutions
- **Places**: Addresses, locations, venues
- **Projects**: Work projects, personal projects
- **Events**: Meetings, appointments, milestones

## Temporal Information

Extract time-related data:
- Specific dates: "March 15th", "November 2024"
- Relative dates: "next Tuesday", "in two weeks"
- Date ranges: "from 1995 to 1998", "during college"
- Recurring: "every Monday", "annually"

If temporal info is ambiguous or missing for historical facts, ASK the user.

## Visibility Classification

Classify based on content type:
- **Tier 1 (Private)**: Medical, financial, personal notes
- **Tier 2 (Personal)**: Birthdays, preferences, grades, contact info
- **Tier 3 (Events/Milestones)**: School events, activities, achievements
- **Tier 4 (Basic)**: Name, relationship only

When uncertain about classification, ASK the user.

## About Entity

If the fact is primarily ABOUT a specific entity (person, place, etc.):
1. Check if the entity already exists using entity_search
2. If not, create a new entity using entity_create
3. Link the fact to the entity

## Workflow

1. Parse the input using extract_entities tool
2. Check for existing entities using entity_search
3. Create new entities if needed using entity_create
4. Determine visibility tier (ask if uncertain)
5. Extract temporal validity (ask if uncertain)
6. Store the fact using fact_store
7. Generate embedding using generate_embedding
8. Confirm to user what was stored

## Response Format

After storing, confirm with:
- What was stored (summarize the fact)
- Who/what it's about (entity)
- Visibility level
- Any temporal validity applied
"""

def create_ingestion_agent(tools: list) -> Agent:
    return Agent(
        name="ingestion",
        system_prompt=INGESTION_SYSTEM_PROMPT,
        tools=tools,
    )
```

### 3. Query Agent

**Purpose:** Answers questions by searching the knowledge base, applying permissions, and synthesizing responses.

```python
# agents/src/query/agent.py

from strands import Agent

QUERY_SYSTEM_PROMPT = """You are the Query Agent for Second Brain, responsible for answering questions about stored knowledge.

## Your Responsibilities

1. **Understand the query** and what information is being requested
2. **Search the knowledge base** using appropriate methods
3. **Apply permission filtering** based on the user's access
4. **Synthesize a helpful response** from retrieved facts
5. **Handle follow-up questions** with conversation context

## Search Strategies

Choose the appropriate search strategy:

### Semantic Search
Use for conceptual or broad queries:
- "What do I know about John?"
- "Tell me about Emma's activities"
- "Find information about my job history"

### Entity Search
Use for specific entity lookups:
- "Who is Sarah?"
- "What is Acme Corp?"

### Temporal Search
Use for time-based queries:
- "Who did I work with in 1996?"
- "What was my phone number in 2004?"
- "Where did we live when Emma was born?"

### Geographic Search
Use for location-based queries:
- "Which friends live near Emma's school?"
- "Who lives within walking distance?"
- "What restaurants are near my office?"

### Relationship Search
Use for graph queries:
- "Who works at Acme?"
- "Who are Emma's friends?"
- "List my grandchildren"

## Permission Awareness

You have access to the current user's context including:
- user_id: The requesting user
- access_cache: Pre-computed access permissions

ONLY return facts the user has permission to see based on:
- Facts they own
- Facts owned by their family
- Facts about people they have relationship access to (via access tier)

## Response Guidelines

1. Be concise but complete
2. Cite sources when relevant ("Based on what you told me on [date]...")
3. If no relevant facts found, say so clearly
4. For ambiguous queries, ask clarifying questions
5. For temporal queries, include the time context

## Handling "No Results"

If you can't find relevant information:
1. Acknowledge the gap
2. Suggest what the user could store
3. Offer to check different search strategies

Example: "I don't have any information about John's birthday stored. Would you like to tell me when it is so I can remember it?"
"""

def create_query_agent(tools: list) -> Agent:
    return Agent(
        name="query",
        system_prompt=QUERY_SYSTEM_PROMPT,
        tools=tools,
    )
```

### 4. Calendar Agent

**Purpose:** Syncs and queries calendar data, creates events, links calendar events to entities.

```python
# agents/src/calendar/agent.py

from strands import Agent

CALENDAR_SYSTEM_PROMPT = """You are the Calendar Agent for Second Brain, responsible for calendar operations.

## Your Responsibilities

1. **Query calendar events** from synced calendars
2. **Create new events** on user's calendar
3. **Link events to entities** (attendees, locations)
4. **Provide schedule summaries** for time ranges
5. **Find scheduling conflicts**

## Calendar Operations

### Querying Events
- Get events for today, tomorrow, this week
- Find events with specific attendees
- Search events by title/description
- Look up events near a date

### Creating Events
- Create new events with title, time, location
- Add attendees (link to entities if possible)
- Set reminders
- Handle recurring events

### Entity Linking
When events have attendees:
1. Search for matching entities using entity_search
2. Link attendees to entities for rich context
3. This enables queries like "When am I meeting with Sarah?"

## Response Guidelines

When listing events:
- Show date/time in user's timezone
- Include location if available
- Mention linked entities (not just email addresses)
- Note any relevant facts about attendees

For schedule summaries:
- Group by day if multiple days
- Highlight conflicts or tight schedules
- Note important context from linked entities

## Integration with Other Agents

You may hand off to:
- **query_agent**: If user asks about facts related to calendar attendees
- **ingestion_agent**: If user wants to store notes about a meeting
"""

def create_calendar_agent(tools: list) -> Agent:
    return Agent(
        name="calendar",
        system_prompt=CALENDAR_SYSTEM_PROMPT,
        tools=tools,
    )
```

### 5. Scheduler Agent

**Purpose:** Generates morning briefings and proactive notifications.

```python
# agents/src/scheduler/agent.py

from strands import Agent

SCHEDULER_SYSTEM_PROMPT = """You are the Scheduler Agent for Second Brain, responsible for proactive notifications and briefings.

## Your Responsibilities

1. **Generate morning briefings** with personalized content
2. **Identify reminder triggers** (birthdays, deadlines, etc.)
3. **Create proactive notifications**
4. **Surface contextual information** before meetings

## Morning Briefing Format

Generate briefings with these sections:

### 1. Calendar Summary
- Today's events with times and locations
- Note relevant context about attendees

### 2. Birthdays & Anniversaries
- Today's celebrations
- Upcoming (next 7 days)

### 3. Deadlines
- Approaching deadlines (next 7 days)
- Overdue items

### 4. Meeting Prep
For each meeting today:
- Recent facts about attendees
- Open action items with them
- Last interaction/notes

### 5. Family Updates (if applicable)
- Upcoming events for family members the user can see
- School events, activities, etc.

## Reminder Triggers

Identify and create reminders for:
- **Birthdays**: N days before (user configurable, default 3)
- **Anniversaries**: N days before
- **Deadlines**: When approaching (7, 3, 1 day)
- **Follow-ups**: When due date reached
- **Recurring**: Based on recurrence rules

## Contextual Notifications

Before meetings, surface:
- Facts about attendees
- Previous meeting notes
- Open items/action items

## Personalization

Respect user preferences from their settings:
- Briefing time
- Included sections
- Notification frequency
- Reminder lead times
"""

def create_scheduler_agent(tools: list) -> Agent:
    return Agent(
        name="scheduler",
        system_prompt=SCHEDULER_SYSTEM_PROMPT,
        tools=tools,
    )
```

---

## Tool Definitions

### Database Tools

```python
# agents/src/shared/tools/database.py

from strands import tool, ToolContext
import asyncpg
from typing import Optional, List
from datetime import date

@tool(context=True)
async def fact_store(
    content: str,
    owner_type: str,
    owner_id: str,
    visibility_tier: int,
    about_entity_id: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_to: Optional[str] = None,
    importance: int = 3,
    source: str = "text",
    tags: Optional[List[str]] = None,
    tool_context: ToolContext = None,
) -> dict:
    """Store a new fact in the knowledge base.

    Args:
        content: The fact content to store
        owner_type: Either 'user' or 'family'
        owner_id: The user_id or family_id that owns this fact
        visibility_tier: Access tier (1=private, 2=personal, 3=events, 4=basic)
        about_entity_id: Optional entity this fact is about
        valid_from: When this fact became true (ISO date)
        valid_to: When this fact stopped being true (ISO date, null=current)
        importance: Importance score 1-5 (default 3)
        source: Source type (voice, text, import, calendar, inferred)
        tags: Optional list of tag paths to apply
    """
    db = tool_context.invocation_state.get("db")
    user_id = tool_context.invocation_state.get("user_id")

    # Insert fact
    fact_id = await db.fetchval("""
        INSERT INTO facts (
            owner_type, owner_id, created_by, content, source,
            importance, visibility_tier, about_entity_id,
            valid_from, valid_to
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
    """, owner_type, owner_id, user_id, content, source,
        importance, visibility_tier, about_entity_id,
        valid_from, valid_to)

    # Apply tags if provided
    if tags:
        for tag_path in tags:
            await db.execute("""
                INSERT INTO fact_tags (fact_id, tag_id)
                SELECT $1, id FROM tags WHERE path = $2
                ON CONFLICT DO NOTHING
            """, fact_id, tag_path)

    return {
        "status": "success",
        "fact_id": str(fact_id),
        "message": f"Fact stored successfully with ID {fact_id}"
    }


@tool(context=True)
async def fact_search(
    query: Optional[str] = None,
    about_entity_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    as_of_date: Optional[str] = None,
    limit: int = 10,
    tool_context: ToolContext = None,
) -> dict:
    """Search for facts with filtering and permission checks.

    Args:
        query: Text to search for (uses full-text search)
        about_entity_id: Filter to facts about a specific entity
        owner_id: Filter to facts owned by specific user/family
        tags: Filter to facts with any of these tags
        as_of_date: Point-in-time query (ISO date)
        limit: Maximum results to return
    """
    db = tool_context.invocation_state.get("db")
    user_id = tool_context.invocation_state.get("user_id")
    family_ids = tool_context.invocation_state.get("family_ids", [])

    # Build query with permission filtering
    conditions = []
    params = [user_id]
    param_idx = 2

    # Permission filter
    conditions.append(f"""(
        (f.owner_type = 'user' AND f.owner_id = $1)
        OR (f.owner_type = 'family' AND f.owner_id = ANY(${param_idx}))
        OR EXISTS (
            SELECT 1 FROM user_access_cache uac
            WHERE uac.viewer_user_id = $1
              AND uac.target_user_id = f.owner_id
              AND uac.access_tier <= f.visibility_tier
        )
    )""")
    params.append(family_ids)
    param_idx += 1

    # Additional filters
    if about_entity_id:
        conditions.append(f"f.about_entity_id = ${param_idx}")
        params.append(about_entity_id)
        param_idx += 1

    if as_of_date:
        conditions.append(f"f.valid_range @> ${param_idx}::timestamptz")
        params.append(as_of_date)
        param_idx += 1
    else:
        conditions.append("(f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)")

    if query:
        conditions.append(f"f.content_normalized ILIKE ${param_idx}")
        params.append(f"%{query.lower()}%")
        param_idx += 1

    where_clause = " AND ".join(conditions)

    results = await db.fetch(f"""
        SELECT f.id, f.content, f.importance, f.visibility_tier,
               f.valid_from, f.valid_to, f.recorded_at,
               e.name as entity_name
        FROM facts f
        LEFT JOIN entities e ON e.id = f.about_entity_id
        WHERE {where_clause}
        ORDER BY f.importance DESC, f.recorded_at DESC
        LIMIT ${param_idx}
    """, *params, limit)

    return {
        "status": "success",
        "count": len(results),
        "facts": [dict(r) for r in results]
    }
```

### Vector Search Tools

```python
# agents/src/shared/tools/vector_search.py

from strands import tool, ToolContext
from typing import Optional, List
import json

@tool(context=True)
async def semantic_search(
    query: str,
    limit: int = 10,
    min_similarity: float = 0.7,
    tool_context: ToolContext = None,
) -> dict:
    """Search facts using semantic similarity (vector search).

    Args:
        query: Natural language query to search for
        limit: Maximum results to return
        min_similarity: Minimum cosine similarity threshold (0-1)
    """
    db = tool_context.invocation_state.get("db")
    bedrock = tool_context.invocation_state.get("bedrock")
    user_id = tool_context.invocation_state.get("user_id")
    family_ids = tool_context.invocation_state.get("family_ids", [])

    # Generate embedding for query
    response = bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": query})
    )
    query_embedding = json.loads(response["body"].read())["embedding"]

    # Search with permission filtering
    results = await db.fetch("""
        WITH query_embedding AS (
            SELECT $1::vector AS vec
        )
        SELECT
            f.id,
            f.content,
            f.importance,
            1 - (fe.embedding <=> qe.vec) AS similarity,
            e.name as entity_name
        FROM facts f
        JOIN fact_embeddings fe ON fe.fact_id = f.id
        CROSS JOIN query_embedding qe
        LEFT JOIN entities e ON e.id = f.about_entity_id
        WHERE (
            (f.owner_type = 'user' AND f.owner_id = $2)
            OR (f.owner_type = 'family' AND f.owner_id = ANY($3))
            OR EXISTS (
                SELECT 1 FROM user_access_cache uac
                WHERE uac.viewer_user_id = $2
                  AND uac.target_user_id = f.owner_id
                  AND uac.access_tier <= f.visibility_tier
            )
        )
        AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
        AND 1 - (fe.embedding <=> qe.vec) >= $4
        ORDER BY fe.embedding <=> qe.vec
        LIMIT $5
    """, query_embedding, user_id, family_ids, min_similarity, limit)

    return {
        "status": "success",
        "count": len(results),
        "facts": [dict(r) for r in results]
    }


@tool(context=True)
async def generate_embedding(
    fact_id: str,
    tool_context: ToolContext = None,
) -> dict:
    """Generate and store embedding for a fact.

    Args:
        fact_id: The ID of the fact to generate embedding for
    """
    db = tool_context.invocation_state.get("db")
    bedrock = tool_context.invocation_state.get("bedrock")

    # Get fact content
    content = await db.fetchval(
        "SELECT content FROM facts WHERE id = $1",
        fact_id
    )

    if not content:
        return {"status": "error", "message": "Fact not found"}

    # Generate embedding
    response = bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": content})
    )
    embedding = json.loads(response["body"].read())["embedding"]

    # Store embedding
    await db.execute("""
        INSERT INTO fact_embeddings (fact_id, embedding)
        VALUES ($1, $2)
        ON CONFLICT (fact_id) DO UPDATE SET
            embedding = EXCLUDED.embedding,
            created_at = NOW()
    """, fact_id, embedding)

    return {"status": "success", "message": "Embedding generated and stored"}
```

### Entity Tools

```python
# agents/src/shared/tools/entities.py

from strands import tool, ToolContext
from typing import Optional, List

@tool(context=True)
async def entity_search(
    query: str,
    entity_type: Optional[str] = None,
    limit: int = 10,
    tool_context: ToolContext = None,
) -> dict:
    """Search for entities by name with fuzzy matching.

    Args:
        query: Name or partial name to search for
        entity_type: Optional filter by type (person, organization, place, project, event)
        limit: Maximum results to return
    """
    db = tool_context.invocation_state.get("db")
    user_id = tool_context.invocation_state.get("user_id")
    family_ids = tool_context.invocation_state.get("family_ids", [])

    type_filter = ""
    params = [user_id, family_ids, query.lower(), limit]

    if entity_type:
        type_filter = "AND e.entity_type = $5"
        params.append(entity_type)

    results = await db.fetch(f"""
        SELECT e.id, e.name, e.entity_type, e.description,
               similarity(e.normalized_name, $3) as match_score
        FROM entities e
        WHERE (
            (e.owner_type = 'user' AND e.owner_id = $1)
            OR (e.owner_type = 'family' AND e.owner_id = ANY($2))
        )
        AND (
            e.normalized_name % $3
            OR $3 = ANY(SELECT LOWER(unnest(e.aliases)))
        )
        {type_filter}
        ORDER BY match_score DESC
        LIMIT $4
    """, *params)

    return {
        "status": "success",
        "count": len(results),
        "entities": [dict(r) for r in results]
    }


@tool(context=True)
async def entity_create(
    name: str,
    entity_type: str,
    owner_type: str,
    owner_id: str,
    description: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    visibility_tier: int = 3,
    linked_user_id: Optional[str] = None,
    tool_context: ToolContext = None,
) -> dict:
    """Create a new entity (person, place, organization, etc.).

    Args:
        name: Display name for the entity
        entity_type: Type (person, organization, place, project, event, product, custom)
        owner_type: Either 'user' or 'family'
        owner_id: The user_id or family_id that owns this entity
        description: Optional description
        aliases: Optional list of alternative names
        visibility_tier: Access tier (1-4)
        linked_user_id: For person entities, optional link to a system user
    """
    db = tool_context.invocation_state.get("db")
    user_id = tool_context.invocation_state.get("user_id")

    entity_id = await db.fetchval("""
        INSERT INTO entities (
            owner_type, owner_id, created_by, entity_type,
            name, description, aliases, visibility_tier, linked_user_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
    """, owner_type, owner_id, user_id, entity_type,
        name, description, aliases or [], visibility_tier, linked_user_id)

    return {
        "status": "success",
        "entity_id": str(entity_id),
        "message": f"Entity '{name}' created successfully"
    }


@tool(context=True)
async def entity_get_details(
    entity_id: str,
    include_facts: bool = True,
    include_attributes: bool = True,
    include_locations: bool = True,
    tool_context: ToolContext = None,
) -> dict:
    """Get detailed information about an entity.

    Args:
        entity_id: The entity ID to look up
        include_facts: Include related facts
        include_attributes: Include temporal attributes
        include_locations: Include locations
    """
    db = tool_context.invocation_state.get("db")
    user_id = tool_context.invocation_state.get("user_id")

    # Get entity
    entity = await db.fetchrow("""
        SELECT e.*, u.display_name as linked_user_name
        FROM entities e
        LEFT JOIN users u ON u.id = e.linked_user_id
        WHERE e.id = $1
    """, entity_id)

    if not entity:
        return {"status": "error", "message": "Entity not found"}

    result = {
        "status": "success",
        "entity": dict(entity)
    }

    if include_facts:
        facts = await db.fetch("""
            SELECT f.content, f.importance, f.recorded_at
            FROM facts f
            WHERE f.about_entity_id = $1
              AND (f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)
            ORDER BY f.importance DESC, f.recorded_at DESC
            LIMIT 20
        """, entity_id)
        result["facts"] = [dict(f) for f in facts]

    if include_attributes:
        attributes = await db.fetch("""
            SELECT attribute_name, attribute_value, valid_from, valid_to
            FROM entity_attributes
            WHERE entity_id = $1
            ORDER BY valid_from DESC NULLS LAST
        """, entity_id)
        result["attributes"] = [dict(a) for a in attributes]

    if include_locations:
        locations = await db.fetch("""
            SELECT label, address_raw, ST_AsText(location) as coordinates,
                   valid_from, valid_to
            FROM entity_locations
            WHERE entity_id = $1
            ORDER BY valid_from DESC NULLS LAST
        """, entity_id)
        result["locations"] = [dict(l) for l in locations]

    return result
```

### Geographic Tools

```python
# agents/src/shared/tools/geographic.py

from strands import tool, ToolContext
from typing import Optional

@tool(context=True)
async def proximity_search(
    reference_entity_id: str,
    reference_location_label: str,
    relationship_type: Optional[str] = None,
    max_distance_meters: int = 2000,
    limit: int = 10,
    tool_context: ToolContext = None,
) -> dict:
    """Find entities near a reference location.

    Args:
        reference_entity_id: Entity to use as reference point
        reference_location_label: Location label (home, school, work)
        relationship_type: Optional filter to specific relationship
        max_distance_meters: Maximum distance in meters
        limit: Maximum results to return
    """
    db = tool_context.invocation_state.get("db")
    user_id = tool_context.invocation_state.get("user_id")

    results = await db.fetch("""
        WITH reference AS (
            SELECT el.location
            FROM entity_locations el
            WHERE el.entity_id = $1
              AND el.label = $2
              AND el.valid_to IS NULL
            LIMIT 1
        )
        SELECT
            e.id,
            e.name,
            e.entity_type,
            el.label as location_label,
            el.address_raw,
            ST_Distance(el.location, r.location) as distance_meters
        FROM entities e
        JOIN entity_locations el ON el.entity_id = e.id
        CROSS JOIN reference r
        LEFT JOIN relationships rel ON rel.target_user_id = e.linked_user_id
        WHERE el.valid_to IS NULL
          AND ST_DWithin(el.location, r.location, $3)
          AND e.id != $1
          AND ($4 IS NULL OR rel.relationship_type::text = $4)
        ORDER BY distance_meters
        LIMIT $5
    """, reference_entity_id, reference_location_label,
        max_distance_meters, relationship_type, limit)

    return {
        "status": "success",
        "count": len(results),
        "nearby_entities": [dict(r) for r in results]
    }


@tool(context=True)
async def geocode_address(
    address: str,
    entity_id: str,
    location_label: str,
    tool_context: ToolContext = None,
) -> dict:
    """Geocode an address and store the location for an entity.

    Args:
        address: The address to geocode
        entity_id: Entity to attach this location to
        location_label: Label for this location (home, work, school)
    """
    db = tool_context.invocation_state.get("db")
    location_client = tool_context.invocation_state.get("location_client")

    # Call AWS Location Service
    response = location_client.search_place_index_for_text(
        IndexName="second-brain-places",
        Text=address,
        MaxResults=1
    )

    if not response.get("Results"):
        return {"status": "error", "message": "Could not geocode address"}

    result = response["Results"][0]
    point = result["Place"]["Geometry"]["Point"]
    confidence = result.get("Relevance", 0.8)

    # Store location
    await db.execute("""
        INSERT INTO entity_locations (
            entity_id, label, address_raw, location,
            geocode_source, geocode_confidence, geocoded_at
        ) VALUES (
            $1, $2, $3,
            ST_SetSRID(ST_MakePoint($4, $5), 4326),
            'aws_location', $6, NOW()
        )
        ON CONFLICT (entity_id, label)
        WHERE valid_to IS NULL
        DO UPDATE SET
            address_raw = EXCLUDED.address_raw,
            location = EXCLUDED.location,
            geocode_confidence = EXCLUDED.geocode_confidence,
            geocoded_at = NOW()
    """, entity_id, location_label, address, point[0], point[1], confidence)

    return {
        "status": "success",
        "message": f"Location stored for {location_label}",
        "coordinates": {"lng": point[0], "lat": point[1]},
        "confidence": confidence
    }
```

### Calendar Tools

```python
# agents/src/shared/tools/calendar.py

from strands import tool, ToolContext
from datetime import datetime, timedelta
from typing import Optional

@tool(context=True)
async def calendar_get_events(
    start_date: str,
    end_date: Optional[str] = None,
    attendee_entity_id: Optional[str] = None,
    tool_context: ToolContext = None,
) -> dict:
    """Get calendar events for a date range.

    Args:
        start_date: Start of range (ISO date)
        end_date: End of range (ISO date, defaults to start_date)
        attendee_entity_id: Optional filter to events with specific attendee
    """
    db = tool_context.invocation_state.get("db")
    user_id = tool_context.invocation_state.get("user_id")

    if not end_date:
        end_date = start_date

    # Parse dates and add time
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date) + timedelta(days=1)

    attendee_filter = ""
    params = [user_id, start, end]

    if attendee_entity_id:
        attendee_filter = """
            AND EXISTS (
                SELECT 1 FROM calendar_event_attendees cea
                WHERE cea.event_id = ce.id
                  AND cea.entity_id = $4
            )
        """
        params.append(attendee_entity_id)

    results = await db.fetch(f"""
        SELECT ce.id, ce.title, ce.description, ce.location,
               ce.start_time, ce.end_time, ce.all_day
        FROM calendar_events ce
        WHERE ce.user_id = $1
          AND ce.start_time >= $2
          AND ce.start_time < $3
          {attendee_filter}
        ORDER BY ce.start_time
    """, *params)

    # Get attendees for each event
    events = []
    for event in results:
        attendees = await db.fetch("""
            SELECT cea.display_name, cea.email, e.name as entity_name
            FROM calendar_event_attendees cea
            LEFT JOIN entities e ON e.id = cea.entity_id
            WHERE cea.event_id = $1
        """, event["id"])

        events.append({
            **dict(event),
            "attendees": [dict(a) for a in attendees]
        })

    return {
        "status": "success",
        "count": len(events),
        "events": events
    }


@tool(context=True)
async def calendar_sync(
    tool_context: ToolContext = None,
) -> dict:
    """Sync calendar from external provider (Google Calendar).

    Fetches recent and upcoming events and stores/updates them.
    """
    db = tool_context.invocation_state.get("db")
    user_id = tool_context.invocation_state.get("user_id")
    google_client = tool_context.invocation_state.get("google_calendar_client")

    # Sync logic here - fetch from Google, update database
    # This is a simplified version

    now = datetime.utcnow()
    time_min = (now - timedelta(days=7)).isoformat() + "Z"
    time_max = (now + timedelta(days=30)).isoformat() + "Z"

    events_result = google_client.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    synced_count = 0
    for event in events_result.get("items", []):
        # Upsert event
        await db.execute("""
            INSERT INTO calendar_events (
                user_id, external_id, external_provider, title,
                description, location, start_time, end_time, all_day, synced_at
            ) VALUES ($1, $2, 'google', $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (user_id, external_provider, external_id)
            DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                location = EXCLUDED.location,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                synced_at = NOW()
        """, user_id, event["id"], event.get("summary"),
            event.get("description"), event.get("location"),
            event["start"].get("dateTime") or event["start"].get("date"),
            event["end"].get("dateTime") or event["end"].get("date"),
            "date" in event["start"])
        synced_count += 1

    return {
        "status": "success",
        "message": f"Synced {synced_count} events"
    }
```

---

## Swarm Configuration

```python
# agents/src/swarm.py

from strands import Agent
from strands.multiagent import Swarm
from strands.agent.conversation_manager import SlidingWindowConversationManager

from .router.agent import create_router_agent
from .ingestion.agent import create_ingestion_agent
from .query.agent import create_query_agent
from .calendar.agent import create_calendar_agent
from .scheduler.agent import create_scheduler_agent
from .shared.tools import (
    database_tools,
    vector_tools,
    entity_tools,
    geographic_tools,
    calendar_tools,
)

def create_second_brain_swarm() -> Swarm:
    """Create the Second Brain agent swarm."""

    # Shared conversation manager
    conversation_manager = SlidingWindowConversationManager(
        window_size=20,  # Keep last 20 message pairs
    )

    # Create agents with their tools
    router = create_router_agent()

    ingestion = create_ingestion_agent(tools=[
        database_tools.fact_store,
        vector_tools.generate_embedding,
        entity_tools.entity_search,
        entity_tools.entity_create,
        geographic_tools.geocode_address,
    ])

    query = create_query_agent(tools=[
        database_tools.fact_search,
        vector_tools.semantic_search,
        entity_tools.entity_search,
        entity_tools.entity_get_details,
        geographic_tools.proximity_search,
    ])

    calendar = create_calendar_agent(tools=[
        calendar_tools.calendar_get_events,
        calendar_tools.calendar_sync,
        entity_tools.entity_search,
    ])

    scheduler = create_scheduler_agent(tools=[
        database_tools.fact_search,
        calendar_tools.calendar_get_events,
        entity_tools.entity_get_details,
    ])

    # Create swarm with router as entry point
    swarm = Swarm(
        agents=[router, ingestion, query, calendar, scheduler],
        entry_point=router,
        max_handoffs=10,
        max_iterations=15,
        execution_timeout=60.0,  # 1 minute total
        node_timeout=30.0,       # 30 seconds per agent
        repetitive_handoff_detection_window=6,
        repetitive_handoff_min_unique_agents=2,
    )

    return swarm
```

---

## AgentCore Entrypoint

```python
# agents/agentcore_entry.py

from bedrock_agentcore.runtime import BedrockAgentCoreApp
import asyncpg
import boto3
import json

from src.swarm import create_second_brain_swarm

app = BedrockAgentCoreApp()

# Initialize shared resources
db_pool = None
bedrock_client = None
location_client = None

@app.on_startup
async def startup():
    global db_pool, bedrock_client, location_client

    # Create database pool
    db_pool = await asyncpg.create_pool(
        host=os.environ["DB_HOST"],
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )

    # Create AWS clients
    bedrock_client = boto3.client("bedrock-runtime")
    location_client = boto3.client("location")

@app.on_shutdown
async def shutdown():
    if db_pool:
        await db_pool.close()

@app.entrypoint
async def invoke(payload: dict) -> dict:
    """Process user requests through the Second Brain swarm."""

    user_message = payload.get("prompt", "")
    user_id = payload.get("user_id")
    session_id = payload.get("session_id", "default")
    family_ids = payload.get("family_ids", [])

    # Get database connection
    async with db_pool.acquire() as db:
        # Create swarm
        swarm = create_second_brain_swarm()

        # Execute with invocation state
        result = await swarm.invoke_async(
            user_message,
            # Shared state accessible to all tools
            db=db,
            bedrock=bedrock_client,
            location_client=location_client,
            user_id=user_id,
            family_ids=family_ids,
        )

        return {
            "response": result.result.message if result.result else "No response",
            "status": result.status.value,
            "agents_used": [node.node_id for node in result.node_history],
            "session_id": session_id,
        }

if __name__ == "__main__":
    app.run()
```

---

## Request Flow Examples

### Example 1: Fact Ingestion

```
User: "Remember that Emma's school play is Friday at 6pm"

1. Rust Lambda receives request
   - Validates JWT
   - Extracts user_id from token
   - Invokes AgentCore

2. Router Agent
   - Classifies as INGESTION
   - Handoff to ingestion_agent

3. Ingestion Agent
   - Calls entity_search("Emma") → finds Emma entity
   - Extracts: event type, date (Friday), time (6pm)
   - Classifies visibility: Tier 3 (school event)
   - Calls fact_store(...)
   - Calls generate_embedding(fact_id)
   - Returns: "Got it! I'll remember Emma's school play is Friday at 6pm."

4. Rust Lambda returns response to user
```

### Example 2: Query with Permissions

```
User (Grandpa): "What's coming up for Emma this week?"

1. Router Agent → query_agent

2. Query Agent
   - Gets user context: grandpa has Tier 3 access to Emma
   - Calls fact_search(about_entity_id=emma_id)
   - Calls calendar_get_events(attendee_entity_id=emma_id)
   - Filters results to Tier 3+ only (events, not medical)
   - Returns: "Emma has her school play on Friday at 6pm
     and soccer practice on Saturday morning."
```

### Example 3: Geographic Query

```
User: "Which of Emma's friends live within walking distance?"

1. Router Agent → query_agent

2. Query Agent
   - Identifies: subject=Emma, relationship=friends, distance=walking
   - Gets Emma's age from facts → 8 years old
   - Calculates walking distance for 8yo → 800m
   - Calls proximity_search(
       reference_entity_id=emma_id,
       reference_location_label="home",
       relationship_type="friend",
       max_distance_meters=800
     )
   - Returns: "Two of Emma's friends live within walking distance:
     Sarah (about 650m, ~8 minute walk) and Lily (400m, ~5 minutes)."
```

---

## Configuration

### Environment Variables

```bash
# Database
DB_HOST=xxx.rds.amazonaws.com
DB_NAME=second_brain
DB_USER=app_user
DB_PASSWORD=<from secrets manager>

# AWS
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-20250514-v1:0

# Limits
MAX_HANDOFFS=10
MAX_ITERATIONS=15
EXECUTION_TIMEOUT=60
```

### Model Configuration

```python
# For primary reasoning (Router, Query, Ingestion)
SONNET_CONFIG = {
    "model_id": "anthropic.claude-sonnet-4-20250514-v1:0",
    "max_tokens": 4096,
    "temperature": 0.7,
}

# For simple classification tasks
HAIKU_CONFIG = {
    "model_id": "anthropic.claude-haiku-4-20250514-v1:0",
    "max_tokens": 1024,
    "temperature": 0.3,
}
```

---

*Document Version: 1.0*
*Architecture supports: Multi-agent coordination, permission-aware queries, temporal/spatial reasoning*

# Second Brain - Requirements Document

**Version:** 2.0
**Date:** January 2025
**Status:** Implementation In Progress - Phases 1-4 Complete

### Changelog
- v2.0: Synced with implementation status. Phases 1-4 complete (Core, Extended Features, Calendar, Discord). Updated phase definitions.
- v1.2: Added Tech Stack section (Rust Lambdas, Python Agents, Python CDK, TypeScript Web)
- v1.1: Added Geographic (PostGIS) and Temporal query requirements, consolidated to PostgreSQL-only storage (removed DynamoDB)

---

## Executive Summary

A voice-enabled personal knowledge management system ("Second Brain") for families. The platform enables natural language fact ingestion, intelligent classification, proactive reminders, and multi-platform access. Built on AWS with Strands SDK for agentic capabilities.

---

## Implementation Status

### Completed (Phases 1-4)

| Phase | Status | Key Deliverables |
|-------|--------|------------------|
| **Phase 1: Core Knowledge** | ✅ Complete | Fact ingestion (~8s), semantic search, entity extraction, visibility tiers, Cognito auth |
| **Phase 2: Extended Features** | ✅ Complete | Hierarchical tags, PostGIS locations, proximity queries, reminders, user feedback loop |
| **Phase 3: Calendar & Briefings** | ✅ Complete | Google Calendar OAuth, 15-min sync, morning briefings, meeting context, milestone detection |
| **Phase 4: Discord Integration** | ✅ Complete | Slash commands (/remember, /ask, /briefing), deferred responses, auto-tagging, temporal parsing |

### In Progress (Phase 5)

| Phase | Status | Key Deliverables |
|-------|--------|------------------|
| **Phase 5: Multi-User & Family** | 🔄 In Progress | Family hierarchy with RBAC, tiered access control, relationship graph |

### Planned (Phases 6-8)

| Phase | Status | Key Deliverables |
|-------|--------|------------------|
| **Phase 6: Alexa & Smart Mirror** | ⏳ Planned | Alexa custom skill, account linking, MagicMirror² module, shared device mode |
| **Phase 7: Proactive Intelligence** | ⏳ Planned | Advanced briefing customization, context-aware reminders, deadline notifications |
| **Phase 8: Advanced & Optimization** | ⏳ Planned | Taxonomy evolution, pattern detection, performance optimization |

### Test Results

| Metric | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|--------|---------|---------|---------|---------|
| Ingestion Latency | ~8s | ~8s | ~8s | ~14-18s (Discord deferred) |
| Query Latency | ~8s | ~8s | ~8s | ~14-18s (Discord deferred) |
| Core Functions | ✅ Pass | ✅ Pass | ✅ Pass | ✅ Pass |

---

## Tech Stack

### Overview

The system uses a **hybrid Rust/Python architecture** to optimize for both performance and AI capabilities:

| Layer | Language | Rationale |
|-------|----------|-----------|
| **API Lambdas** | Rust | Fast cold starts (~10ms), low memory, type-safe validation |
| **Integration Lambdas** | Rust | Discord webhook, Alexa skill, EventBridge handlers |
| **AI Agents** | Python | Strands SDK, AgentCore Runtime, rapid iteration |
| **Infrastructure** | Python CDK | Mature L2 constructs, matches agent language |
| **Web UI** | TypeScript + React | Modern frontend, type safety |

### Rust Lambda Stack

| Crate | Purpose |
|-------|---------|
| `lambda_runtime` | AWS Lambda execution environment |
| `lambda_http` | API Gateway integration |
| `validator` | Request validation with derive macros |
| `aws-lambda-powertools` | Structured logging, tracing |
| `sqlx` | Async PostgreSQL client |
| `serde` | Serialization/deserialization |
| `tokio` | Async runtime |
| `aws-sdk-*` | AWS service clients |

### Python Agent Stack

| Library | Purpose |
|---------|---------|
| Strands SDK | Agent framework, tool definitions, Swarm orchestration |
| AWS AgentCore Runtime | Managed agent deployment |
| Pydantic | Data validation and models |
| asyncpg | Async PostgreSQL client |
| boto3 | AWS SDK for Bedrock, etc. |

### Infrastructure as Code

| Tool | Purpose |
|------|---------|
| AWS CDK (Python) | Infrastructure definition |
| CDK Constructs | L2/L3 constructs for AWS services |

### Project Structure

```
second_brain/
├── infra/                          # Python CDK
│   ├── app.py                      # CDK app entry point
│   ├── stacks/
│   │   ├── api.py                  # API Gateway + Rust Lambdas
│   │   ├── agents.py               # Python agent Lambda
│   │   ├── database.py             # RDS PostgreSQL
│   │   ├── auth.py                 # Cognito
│   │   ├── integrations.py         # Discord, Alexa Lambdas
│   │   ├── scheduling.py           # EventBridge rules
│   │   ├── migrations.py           # DB migration runner
│   │   ├── monitoring.py           # CloudWatch
│   │   └── network.py              # VPC
│   └── requirements.txt
│
├── lambdas/                        # Rust
│   ├── Cargo.toml                  # Workspace config
│   ├── shared/                     # Shared types, DB client
│   ├── api-gateway/src/bin/        # REST API handlers
│   │   ├── ingest.rs               # Fact ingestion
│   │   ├── query.rs                # Knowledge search
│   │   ├── entities.rs             # Entity CRUD
│   │   ├── relationships.rs        # Entity relationships
│   │   ├── tags.rs                 # Tagging system
│   │   ├── reminders.rs            # Reminder management
│   │   ├── locations.rs            # Geographic queries
│   │   ├── calendar.rs             # Calendar operations
│   │   ├── calendar_oauth.rs       # Google OAuth flow
│   │   ├── briefing.rs             # Morning briefings
│   │   ├── feedback.rs             # User feedback
│   │   ├── families.rs             # Family management
│   │   └── user_signup.rs          # Registration
│   ├── discord-webhook/            # Discord bot handler
│   ├── alexa-skill/                # Alexa request handler
│   ├── event-triggers/             # EventBridge handlers
│   └── geocoder/                   # AWS Location Service
│
├── agents/                         # Python (Strands SDK)
│   ├── agentcore_entry.py          # Lambda entry point
│   ├── pyproject.toml
│   └── src/
│       ├── router/                 # Intent classification agent
│       ├── ingestion/              # Fact ingestion agent
│       ├── query/                  # Query answering agent
│       ├── calendar/               # Calendar sync agent
│       ├── briefing/               # Briefing generation agent
│       ├── scheduler/              # Proactive notification agent
│       ├── taxonomy/               # Tag evolution agent
│       └── shared/
│           ├── tools/              # Agent tools (DB, entities, search)
│           ├── database.py         # Connection management
│           ├── models.py           # Pydantic models
│           └── temporal.py         # Temporal parsing
│
├── migrations/                     # SQL migration scripts (16 files)
│   ├── 001_extensions.sql          # pgvector, PostGIS, etc.
│   ├── 002_users_families.sql      # User hierarchy
│   └── ...                         # Schema evolution
│
├── web/                            # TypeScript + React (Next.js 14)
│   ├── src/
│   ├── package.json
│   └── tsconfig.json
│
├── docs/
│   ├── requirements.md             # This document
│   └── implementation-plan.md      # Development roadmap
│
└── TESTING_PLAN.md                 # Comprehensive test scenarios
```

### Request Flow

```
User Request (Discord/Alexa/API)
         │
         ▼
┌─────────────────────┐
│  Rust Lambda        │  ~10ms cold start
│  - Validate request │  - Auth check
│  - Parse input      │  - Rate limiting
└──────────┬──────────┘
           │
           ▼ Invoke AgentCore
┌─────────────────────┐
│  Python Agent       │  Strands SDK
│  (AgentCore)        │  - LLM reasoning
│  - Process request  │  - Tool execution
│  - Query/Store DB   │  - Response generation
└──────────┬──────────┘
           │
           ▼ Return
┌─────────────────────┐
│  Rust Lambda        │  Format response
│  - Transform output │  Return to caller
└─────────────────────┘
```

---

## Table of Contents

- [Implementation Status](#implementation-status)
- [Tech Stack](#tech-stack)
1. [User Interaction Requirements](#1-user-interaction-requirements)
2. [Knowledge Ingestion Requirements](#2-knowledge-ingestion-requirements)
3. [Storage Requirements](#3-storage-requirements)
4. [Multi-User & Family Requirements](#4-multi-user--family-requirements)
5. [Geographic Query Requirements](#5-geographic-query-requirements)
6. [Temporal Query Requirements](#6-temporal-query-requirements)
7. [Proactive Intelligence Requirements](#7-proactive-intelligence-requirements)
8. [Agent Architecture Requirements](#8-agent-architecture-requirements)
9. [Multi-Platform API Requirements](#9-multi-platform-api-requirements)
10. [Authentication Requirements](#10-authentication-requirements)
11. [AWS Infrastructure Requirements](#11-aws-infrastructure-requirements)
12. [Non-Functional Requirements](#12-non-functional-requirements)
13. [Cost Targets](#13-cost-targets)
14. [Implementation Phases](#14-implementation-phases)

---

## 1. User Interaction Requirements

### 1.1 Supported Platforms

| Platform | Type | Status | Priority | Notes |
|----------|------|--------|----------|-------|
| Discord Bot | Primary | ✅ Active | High | Slash commands, deferred responses |
| REST API | Direct | ✅ Active | High | Full CRUD, Cognito auth |
| Alexa Skill | Voice | ⏳ Planned | High | Hands-free, household access |
| Smart Mirror | Ambient | ⏳ Planned | Medium | MagicMirror² integration |
| Web App | Dashboard | ⏳ Planned | Medium | Next.js 14 (scaffolded) |
| Mobile App | Future | ⏳ Planned | Low | iOS/Android |

### 1.2 Voice Input/Output

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| UI-V-001 | Support Discord voice channel input with real-time audio streaming | High |
| UI-V-002 | Integrate Amazon Transcribe for speech-to-text conversion | High |
| UI-V-003 | Support Amazon Polly (Neural) for text-to-speech responses | High |
| UI-V-004 | Provide text-based fallback in all channels | High |
| UI-V-005 | Support Alexa custom skill with account linking | High |
| UI-V-006 | Smart Mirror wake word detection ("Mirror") | Medium |

### 1.3 Query Types Supported

| Req ID | Query Type | Example | Priority |
|--------|------------|---------|----------|
| UI-Q-001 | Fact Ingestion | "Remember that John's birthday is March 15th" | High |
| UI-Q-002 | Entity Queries | "What do I know about John?" | High |
| UI-Q-003 | Relationship Queries | "Who works at Acme Corp?" | High |
| UI-Q-004 | Project Queries | "What are the open tasks for Project Alpha?" | High |
| UI-Q-005 | Temporal Queries | "What happened last week?" | Medium |
| UI-Q-006 | Calendar Queries | "What's on my calendar tomorrow?" | High |
| UI-Q-007 | Context-Aware Follow-ups | "Tell me more about that" | Medium |
| UI-Q-008 | Comparative Queries | "Compare Project A and Project B" | Low |
| UI-Q-009 | Inference Queries | "Who should I contact about X?" | Medium |
| UI-Q-010 | Family Queries | "What's Emma's school schedule?" | High |

### 1.4 Response Formats

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| UI-R-001 | Conversational text responses for general queries | High |
| UI-R-002 | Structured lists for enumeration queries | High |
| UI-R-003 | Summary cards for entity profiles | Medium |
| UI-R-004 | Audio responses via Amazon Polly for voice interactions | High |
| UI-R-005 | Markdown formatting support for rich text output | Medium |

---

## 2. Knowledge Ingestion Requirements

### 2.1 Fact Types

| Req ID | Fact Type | Examples | Priority |
|--------|-----------|----------|----------|
| KI-T-001 | Person Facts | Names, birthdays, contact info, relationships, preferences | High |
| KI-T-002 | Place Facts | Locations, addresses, associations, visited dates | High |
| KI-T-003 | Project Facts | Names, status, deadlines, stakeholders, notes | High |
| KI-T-004 | Event Facts | Dates, participants, outcomes, follow-ups | High |
| KI-T-005 | Organization Facts | Companies, roles, contacts, relationships | Medium |
| KI-T-006 | Task Facts | Action items, due dates, assignees, status | High |
| KI-T-007 | Preference Facts | User preferences, habits, routines | Medium |
| KI-T-008 | Temporal Facts | Anniversaries, recurring events, milestones | High |

### 2.2 Classification System

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| KI-C-001 | Entity Extraction - Identify people, places, organizations, projects | High |
| KI-C-002 | Relationship Extraction - Identify relationships between entities | High |
| KI-C-003 | Temporal Extraction - Parse dates, durations, recurring patterns | High |
| KI-C-004 | Importance Classification - Auto-assign importance scores (1-5) | Medium |
| KI-C-005 | Confidence Scoring - Assign confidence levels to extracted info | Medium |
| KI-C-006 | Disambiguation - Handle ambiguous references with user confirmation | Medium |
| KI-C-007 | Visibility Classification - Auto-assign access tier based on content type | High |

#### Classification Example
```
Input: "Remember that Sarah from Acme Corp mentioned the Q4 deadline is November 15th"

Extracted:
- Entity: Person("Sarah") -> linked to Organization("Acme Corp")
- Entity: Organization("Acme Corp")
- Entity: Event("Q4 deadline") -> date: 2024-11-15
- Relationship: Sarah WORKS_AT Acme Corp
- Tags: [deadline, q4, acme-corp, sarah]
- Importance: 4 (deadline-related)
- Visibility: Tier 2 (work-related, personal)
```

### 2.3 Tagging Taxonomy

#### Hierarchical Structure
```
Root Categories:
├── entity_type/
│   ├── person
│   ├── organization
│   ├── place
│   ├── project
│   └── event
├── domain/
│   ├── work
│   ├── personal
│   ├── family
│   └── hobby
├── temporal/
│   ├── recurring
│   ├── deadline
│   ├── milestone
│   └── anniversary
├── priority/
│   ├── critical
│   ├── high
│   ├── medium
│   └── low
└── custom/
    └── [user-defined tags]
```

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| KI-TAG-001 | Support hierarchical tag structure with parent/child relationships | High |
| KI-TAG-002 | Allow user-defined custom tags | High |
| KI-TAG-003 | Auto-suggest tags based on content analysis | Medium |
| KI-TAG-004 | Support tag aliases and synonyms | Low |

### 2.4 Agentic Taxonomy Evolution

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| KI-EV-001 | Pattern Detection - Identify frequently co-occurring tags | Medium |
| KI-EV-002 | Gap Detection - Identify facts without tags and suggest categorization | Medium |
| KI-EV-003 | User Confirmation - Require user approval for taxonomy changes | High |

---

## 3. Storage Requirements

### 3.1 Primary Database

**Primary Choice: Amazon RDS PostgreSQL (Single Database for All Data)**

PostgreSQL serves as the unified data store for all application data, leveraging extensions for specialized functionality.

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| ST-DB-001 | Use Amazon RDS PostgreSQL as single data store | High |
| ST-DB-002 | Instance type: db.t4g.micro for cost optimization (upgradeable) | High |
| ST-DB-003 | Enable automated backups with 7-day retention | High |
| ST-DB-004 | Enable encryption at rest (AWS KMS) | High |
| ST-DB-005 | Configure connection pooling via RDS Proxy (future scaling) | Low |

### 3.2 PostgreSQL Extensions

| Extension | Purpose | RDS Support | Priority |
|-----------|---------|-------------|----------|
| **pgvector** | Vector similarity search for semantic queries | ✅ | High |
| **PostGIS** | Geographic/spatial queries (locations, distances) | ✅ | High |
| **pg_trgm** | Fuzzy text matching ("did you mean...") | ✅ | Medium |
| **btree_gist** | Compound indexes for temporal ranges | ✅ | High |
| **aws_lambda** | Call AWS services (geocoding) from SQL | ✅ | Medium |

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| ST-EXT-001 | Enable pgvector with HNSW index for vector search | High |
| ST-EXT-002 | Enable PostGIS for geographic queries | High |
| ST-EXT-003 | Enable pg_trgm for fuzzy name matching | Medium |
| ST-EXT-004 | Enable btree_gist for temporal range queries | High |

### 3.3 Vector Search (pgvector)

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| ST-VEC-001 | Configure HNSW index for approximate nearest neighbor search | High |
| ST-VEC-002 | Support hybrid search (vector + metadata filtering) | High |
| ST-VEC-003 | Namespace isolation per user and per family | High |
| ST-VEC-004 | Migration path to OpenSearch Serverless at scale (50+ families) | Low |

### 3.4 Embedding Model

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| ST-EMB-001 | Use Amazon Titan Embeddings V2 (1024 dimensions) | High |
| ST-EMB-002 | Support batch embedding for bulk ingestion | Medium |
| ST-EMB-003 | Cache embeddings for common queries | Medium |

### 3.5 Relationship Graph Storage

The relationship graph uses standard relational tables with recursive CTEs for traversal.

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| ST-GRAPH-001 | Adjacency list model for relationship storage | High |
| ST-GRAPH-002 | Recursive CTEs for graph traversal (up to 4 hops) | High |
| ST-GRAPH-003 | Materialized access cache for fast permission lookups | High |
| ST-GRAPH-004 | Trigger-based cache refresh on relationship changes | High |

### 3.6 Calendar Integration

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| ST-CAL-001 | Integrate with Google Calendar via OAuth2 | High |
| ST-CAL-002 | Sync calendar events to internal event store | High |
| ST-CAL-003 | Support read and write operations | Medium |
| ST-CAL-004 | Cache calendar data with 15-minute TTL | Medium |
| ST-CAL-005 | Support Outlook calendar (future) | Low |

---

## 4. Multi-User & Family Requirements

### 4.1 User Hierarchy

```
Platform
├── Family A (Household)
│   ├── Admin (parent) - billing, membership, policies
│   ├── Member (adult) - full personal access, can share
│   └── Child (minor) - restricted, activity visible to admins
├── Family B (Household)
└── Individual User (no family)
```

### 4.2 Role-Based Access Control

| Req ID | Role | Permissions | Priority |
|--------|------|-------------|----------|
| MU-RBAC-001 | FAMILY_ADMIN | Manage membership, billing, policies, child accounts | High |
| MU-RBAC-002 | FAMILY_MEMBER | Full personal CRUD, create/read shared data, share own data | High |
| MU-RBAC-003 | FAMILY_CHILD | Personal CRUD (age-appropriate), read shared, no billing | High |
| MU-RBAC-004 | INDIVIDUAL | Full personal CRUD, self-manage billing, can create/join family | High |

### 4.3 Relationship Graph & Tiered Access

#### Relationship Types
```
Relationship Types:
├── SPOUSE (Tier 1 default)
├── PARENT_OF (Tier 1 to child's data)
├── CHILD_OF (Tier 2 to parent's data)
├── GRANDPARENT_OF (Tier 3 default)
├── GRANDCHILD_OF (Tier 3 default)
├── SIBLING (Tier 2 default)
├── AUNT_UNCLE_OF (Tier 3 default)
└── CUSTOM (configurable)
```

#### Access Tiers

| Tier | Access Level | Example Data |
|------|--------------|--------------|
| **Tier 1** | Full | Medical, finances, private notes, everything |
| **Tier 2** | Personal | Birthdays, preferences, school, activities, contact info |
| **Tier 3** | Events/Milestones | School events, recitals, games, achievements |
| **Tier 4** | Basic | Name, relationship, birthday only |

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| MU-TIER-001 | Implement 4-tier access system based on relationship type | High |
| MU-TIER-002 | Allow parents to explicitly share items up/down the graph | High |
| MU-TIER-003 | Default to most restrictive tier, user can upgrade | High |
| MU-TIER-004 | Agent auto-classifies visibility based on content type | High |
| MU-TIER-005 | Agent asks for confirmation on ambiguous classification | High |

#### Visibility Classification Defaults

| Content Type | Default Tier | Example |
|--------------|--------------|---------|
| Medical/Health | Tier 1 | "Emma has dentist appointment Thursday" |
| Financial | Tier 1 | "Paid $500 for Emma's braces" |
| Academic (grades) | Tier 2 | "Emma got an A on her math test" |
| School Events | Tier 3 | "Emma's school play is Friday" |
| Activities/Sports | Tier 3 | "Emma has soccer practice at 4pm" |
| Birthdays/Anniversaries | Tier 3 | "Emma's birthday is March 15th" |
| Preferences | Tier 2 | "Emma loves dinosaurs" |
| Private Notes | Tier 1 | "Note to self about Emma..." |

### 4.4 Data Sharing Model

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| MU-SHARE-001 | Personal facts private by default | High |
| MU-SHARE-002 | Explicit sharing action required for family visibility | High |
| MU-SHARE-003 | Conversation history NEVER shared | High |
| MU-SHARE-004 | Shared contacts (plumber, doctor) visible to all family | High |
| MU-SHARE-005 | Per-fact override of default visibility | Medium |

---

## 5. Geographic Query Requirements

### 5.1 Overview

Support location-aware queries that combine spatial data with relationship graphs and contextual reasoning.

**Example Queries:**
- "Which of Emma's friends live within walking distance?"
- "What restaurants are near my office?"
- "Who lives closest to Emma's school?" (for carpooling)
- "What's the nearest pharmacy to home?"

### 5.2 Location Storage

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| GEO-001 | Store locations using PostGIS GEOGRAPHY type (WGS84/SRID 4326) | High |
| GEO-002 | Support multiple locations per entity (home, work, school) | High |
| GEO-003 | Store raw address text and normalized components | High |
| GEO-004 | Create spatial index (GIST) for fast proximity queries | High |
| GEO-005 | Track geocoding source and confidence score | Medium |

#### Location Schema
```sql
entity_locations:
├── entity_id (FK)
├── label (home, work, school, etc.)
├── address_raw (original text)
├── address_normalized (JSONB - street, city, state, zip)
├── location (GEOGRAPHY POINT)
├── geocode_source (aws_location, manual)
├── geocode_confidence (0-1)
└── valid_from / valid_to (temporal validity)
```

### 5.3 Geocoding Integration

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| GEO-GC-001 | Integrate AWS Location Service for address geocoding | High |
| GEO-GC-002 | Lambda function to call SearchPlaceIndexForText API | High |
| GEO-GC-003 | Cache geocoded addresses (one-time per address) | High |
| GEO-GC-004 | Support manual coordinate entry for edge cases | Low |

### 5.4 Spatial Query Types

| Req ID | Query Type | Example | Priority |
|--------|------------|---------|----------|
| GEO-Q-001 | Proximity search | "Friends within 1 mile of home" | High |
| GEO-Q-002 | Nearest neighbor | "Closest friend to Emma's school" | High |
| GEO-Q-003 | Distance calculation | "How far is Sarah's house?" | High |
| GEO-Q-004 | Route-aware (future) | "Friends on the way to school" | Low |

### 5.5 Context-Aware Distance Interpretation

The LLM agent interprets natural language distance terms based on context:

| Term | Child (< 10) | Teen (10-16) | Adult |
|------|--------------|--------------|-------|
| "Walking distance" | 800m (~0.5 mi) | 1200m (~0.75 mi) | 2000m (~1.25 mi) |
| "Biking distance" | 2000m | 5000m | 8000m |
| "Nearby" | 1000m | 2000m | 5000m |
| "Close" | 500m | 1000m | 2000m |

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| GEO-CTX-001 | Agent interprets distance terms based on subject's age | High |
| GEO-CTX-002 | Agent asks for clarification on ambiguous distance queries | Medium |
| GEO-CTX-003 | Support explicit distance overrides ("within 2 miles") | High |

### 5.6 Cost Estimate

| Service | Cost | Notes |
|---------|------|-------|
| PostGIS extension | $0 | Included with RDS |
| AWS Location Service | ~$0.50/1000 geocodes | One-time per address |
| **Estimated monthly** | **$1-2** | Most addresses cached |

---

## 6. Temporal Query Requirements

### 6.1 Overview

Support historical queries about facts, relationships, and attributes at specific points in time.

**Example Queries:**
- "Who did I work with at Acme Corp in 1996?"
- "What was my home phone number in 2004?"
- "Where did we live when Emma was born?"
- "What was Sarah's job title before she got promoted?"
- "List all the addresses I've lived at"

### 6.2 Temporal Data Model

All facts and attributes support temporal validity ranges (bitemporal where needed).

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| TEMP-001 | Store valid_from and valid_to timestamps on facts | High |
| TEMP-002 | Support open-ended ranges (valid_to = NULL means current) | High |
| TEMP-003 | Use PostgreSQL TSTZRANGE for efficient range queries | High |
| TEMP-004 | Create GiST index on temporal ranges | High |
| TEMP-005 | Support "as of" queries (point-in-time lookups) | High |
| TEMP-006 | Track when facts were recorded vs when they were true (bitemporal) | Medium |

#### Temporal Schema Pattern
```sql
facts:
├── content
├── valid_from TIMESTAMPTZ      -- When fact became true
├── valid_to TIMESTAMPTZ        -- When fact stopped being true (NULL = current)
├── valid_range TSTZRANGE       -- Computed range for indexing
├── recorded_at TIMESTAMPTZ     -- When we learned this fact
└── superseded_by UUID          -- Link to newer version of same fact

-- Example: Job history
-- "I worked at Acme Corp from 1995-1998"
valid_from: 1995-01-01, valid_to: 1998-06-30

-- "My phone number was 555-1234" (until changed)
valid_from: 2004-03-15, valid_to: 2010-08-01
```

### 6.3 Temporal Query Types

| Req ID | Query Type | SQL Pattern | Example |
|--------|------------|-------------|---------|
| TEMP-Q-001 | Point-in-time | `WHERE valid_range @> '1996-06-01'::timestamptz` | "Coworkers in 1996" |
| TEMP-Q-002 | Range overlap | `WHERE valid_range && '[1995,2000)'` | "Jobs in the late 90s" |
| TEMP-Q-003 | Current state | `WHERE valid_to IS NULL` | "Current phone number" |
| TEMP-Q-004 | History list | `ORDER BY valid_from` | "All addresses I've lived at" |
| TEMP-Q-005 | Timeline | Aggregate by period | "Career timeline" |

### 6.4 Temporal Relationship Tracking

Relationships also have temporal validity:

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| TEMP-REL-001 | Track when relationships started and ended | High |
| TEMP-REL-002 | Support "worked with" queries at specific times | High |
| TEMP-REL-003 | Track role/title changes within relationships | Medium |

#### Example: Employment History
```sql
relationships:
├── source_entity_id (you)
├── target_entity_id (Acme Corp)
├── relationship_type (WORKED_AT)
├── attributes JSONB ({"title": "Engineer", "department": "R&D"})
├── valid_from: 1995-03-01
├── valid_to: 1998-06-30
└── valid_range: [1995-03-01, 1998-06-30)

-- Query: "Who did I work with at Acme in 1996?"
SELECT DISTINCT e.name
FROM relationships r1
JOIN relationships r2 ON r2.target_entity_id = r1.target_entity_id
JOIN entities e ON e.id = r2.source_entity_id
WHERE r1.source_entity_id = :my_id
  AND r1.target_entity_id = :acme_id
  AND r1.valid_range @> '1996-06-01'::timestamptz
  AND r2.valid_range @> '1996-06-01'::timestamptz
  AND r2.relationship_type = 'WORKED_AT';
```

### 6.5 LLM Temporal Interpretation

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| TEMP-LLM-001 | Parse natural language time references ("in the 90s", "when I was at Acme") | High |
| TEMP-LLM-002 | Resolve relative dates ("before Emma was born", "during college") | High |
| TEMP-LLM-003 | Handle ambiguous dates with clarification | Medium |
| TEMP-LLM-004 | Infer time periods from context ("my first job" → earliest employment) | Medium |

#### Natural Language → Temporal Range Examples
```
"in 1996"           → [1996-01-01, 1997-01-01)
"the late 90s"      → [1997-01-01, 2000-01-01)
"when Emma was born" → (lookup Emma's birthdate) → point query
"before 2010"       → (-infinity, 2010-01-01)
"my first job"      → (find earliest WORKED_AT relationship)
```

### 6.6 Temporal Fact Ingestion

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| TEMP-ING-001 | Agent extracts temporal information from natural language | High |
| TEMP-ING-002 | Agent asks for time period when ingesting historical facts | High |
| TEMP-ING-003 | Default to current time if no temporal context given | High |
| TEMP-ING-004 | Support "this replaced X" to supersede old facts | Medium |

#### Ingestion Examples
```
User: "Remember that I worked at Acme Corp from 1995 to 1998"
Agent: Extracted employment relationship with valid_from=1995, valid_to=1998

User: "My phone number is 555-9999"
Agent: "I see you had 555-1234 recorded. Should I mark that as your
        old number and 555-9999 as current? When did you switch?"

User: "We lived on Oak Street when the kids were young"
Agent: "When approximately did you live on Oak Street? I can look up
        when your kids were born to help narrow it down."
```

### 6.7 Temporal Visualization (Future)

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| TEMP-VIS-001 | Timeline view of entity history | Low |
| TEMP-VIS-002 | "On this day" historical lookups | Low |
| TEMP-VIS-003 | Career/life event visualization | Low |

---

## 7. Proactive Intelligence Requirements

### 7.1 Notification Triggers

| Req ID | Trigger Type | Description | Priority |
|--------|--------------|-------------|----------|
| PI-TR-001 | Birthday Reminder | Notify N days before stored birthdays | High |
| PI-TR-002 | Anniversary Reminder | Notify for stored anniversaries | High |
| PI-TR-003 | Deadline Approaching | Notify when deadlines are approaching | High |
| PI-TR-004 | Calendar Event | Notify before calendar events | High |
| PI-TR-005 | Follow-up Due | Remind about pending follow-ups | Medium |
| PI-TR-006 | Context Trigger | Surface relevant facts before meetings | High |
| PI-TR-007 | Recurring Check-in | Periodic reminders about people/projects | Low |

### 7.2 Morning Briefing Content

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| PI-MB-001 | Calendar Summary - Today's events with times and locations | High |
| PI-MB-002 | Birthday/Anniversary Alerts - Today + upcoming 7 days | High |
| PI-MB-003 | Deadline Summary - Approaching deadlines (7-day window) | High |
| PI-MB-004 | Task Summary - Open/pending tasks | Medium |
| PI-MB-005 | Meeting Context - Relevant facts for today's attendees | High |
| PI-MB-006 | Customizable Sections - User configures briefing components | Medium |

#### Morning Briefing Example
```
Good morning! Here's your briefing for Monday, November 11th:

CALENDAR (3 events)
├── 9:00 AM: Team Standup (Zoom)
├── 11:00 AM: 1:1 with Sarah [Note: Her birthday is in 4 days]
└── 2:00 PM: Q4 Planning Review

FAMILY
├── Emma's school play is Friday at 6pm
└── Sarah's birthday is November 15th

DEADLINES THIS WEEK
├── Q4 Report due November 15th (4 days)
└── Project Alpha milestone November 13th (2 days)

MEETING CONTEXT (1:1 with Sarah)
├── Last discussed: Project Alpha timeline concerns
├── Open action: Review budget proposal
└── Recent note: "Sarah mentioned considering team expansion"
```

### 7.3 Importance Scoring

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| PI-IMP-001 | Temporal Proximity - Increase importance as dates approach | High |
| PI-IMP-002 | Explicit Priority - Respect user-assigned priority levels | High |
| PI-IMP-003 | Relationship Depth - Higher importance for frequently referenced entities | Medium |
| PI-IMP-004 | User Feedback Loop - Learn from dismissed vs acted-upon notifications | Low |

---

## 8. Agent Architecture Requirements

### 8.1 Agent Types

| Agent | Purpose | Tools | Status |
|-------|---------|-------|--------|
| **Router Agent** | Intent classification (ingest vs query vs briefing vs calendar) | — | ✅ Active |
| **Ingestion Agent** | Parse input, extract entities, generate embeddings, assign tags & visibility | entity_create, entity_link_to_fact, fact_store, generate_embedding, store_fact_embedding | ✅ Active |
| **Query Agent** | Interpret queries, vector search, synthesize responses | semantic_search, entity_search, entity_get_details, calendar_get_events, relationship traversal | ✅ Active |
| **Calendar Agent** | External calendar sync, event parsing, entity linking | calendar_sync, event_parser, entity_linker | ✅ Active |
| **Briefing Agent** | Morning briefing generation, meeting context | calendar_get_events, semantic_search, reminder_lookup | ✅ Active |
| **Scheduler Agent** | Trigger evaluation, notification queuing | trigger_evaluator, notification_sender | ✅ Active |
| **Taxonomy Agent** | Tag pattern analysis, taxonomy evolution proposals | pattern_analyzer, taxonomy_updater | ⏳ Planned |

### 8.2 Agent Coordination

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AG-COORD-001 | Implement Strands SDK Swarm pattern for multi-agent coordination | High |
| AG-COORD-002 | Define clear handoff criteria between agents | High |
| AG-COORD-003 | Maintain shared context across agent handoffs | High |
| AG-COORD-004 | Implement agent timeout handling | Medium |
| AG-COORD-005 | Log all agent interactions for debugging | Medium |

### 8.3 Strands SDK Integration

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AG-SDK-001 | Use @tool decorator for custom tool definitions | High |
| AG-SDK-002 | Implement conversation context management | High |
| AG-SDK-003 | Use Agent State for cross-request persistence | High |
| AG-SDK-004 | Implement streaming responses for real-time feedback | Medium |
| AG-SDK-005 | Deploy agents via AWS AgentCore Runtime | High |

---

## 9. Multi-Platform API Requirements

### 9.1 API Endpoints

```
REST API (Implemented):
POST   /ingest                # Store a fact ✅
POST   /query                 # Ask a question ✅
GET    /briefing              # Get morning briefing ✅

GET    /entities              # List entities ✅
POST   /entities              # Create entity ✅
GET    /entities/{id}         # Get entity details ✅
PUT    /entities/{id}         # Update entity ✅
DELETE /entities/{id}         # Delete entity ✅

GET    /relationships         # List relationships ✅
POST   /relationships         # Create relationship ✅

GET    /tags                  # List tags ✅
POST   /tags                  # Create tag ✅
GET    /tags/{id}             # Get tag details ✅

GET    /reminders             # List reminders ✅
POST   /reminders             # Create reminder ✅
PUT    /reminders/{id}        # Update reminder ✅
DELETE /reminders/{id}        # Delete reminder ✅

GET    /locations/nearby      # Proximity search ✅
POST   /locations             # Add location to entity ✅

GET    /calendar/events       # Get calendar events ✅
GET    /calendar/oauth/start  # Start Google OAuth flow ✅
GET    /calendar/oauth/callback # OAuth callback ✅

GET    /families              # List family members ✅
POST   /families              # Create/join family ✅

POST   /feedback              # Submit query feedback ✅
POST   /user/signup           # User registration ✅

Planned:
POST   /query/voice           # Ask via audio stream ⏳
WS     /stream                # Real-time voice + push notifications ⏳
```

| Req ID | Requirement | Status | Priority |
|--------|-------------|--------|----------|
| API-001 | RESTful API with Lambda integration | ✅ Implemented | High |
| API-002 | WebSocket support for real-time streaming | ⏳ Planned | High |
| API-003 | API Gateway with Cognito authorizer | ✅ Implemented | High |
| API-004 | Rate limiting per user/device | ⏳ Planned | High |
| API-005 | Request/response logging (CloudWatch) | ✅ Implemented | Medium |

### 9.2 Platform Integrations

| Req ID | Requirement | Status | Priority |
|--------|-------------|--------|----------|
| API-INT-001 | Discord bot with slash commands (/remember, /ask, /briefing) | ✅ Implemented | High |
| API-INT-002 | Discord webhook with ed25519 signature verification | ✅ Implemented | High |
| API-INT-003 | Deferred response pattern for long operations | ✅ Implemented | High |
| API-INT-004 | Alexa Custom Skill with account linking | ⏳ Planned | High |
| API-INT-005 | Smart Mirror module (MagicMirror²) | ⏳ Planned | Medium |
| API-INT-006 | Mobile SDK (future) | ⏳ Planned | Low |

### 9.3 Device Management

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| API-DEV-001 | Device registry with unique device tokens | High |
| API-DEV-002 | Per-device permission configuration | High |
| API-DEV-003 | Shared device mode (Tier 3+ data only) | High |
| API-DEV-004 | Voice profile mapping to user IDs | Medium |
| API-DEV-005 | Remote device deauthorization | High |

#### Device Registry Schema
```json
{
  "device_id": "kitchen_echo_001",
  "device_type": "alexa",
  "family_id": "johnson_family",
  "location": "kitchen",
  "mode": "shared",
  "permissions": {
    "max_tier": 3,
    "voice_profiles_enabled": true,
    "can_ingest_facts": true,
    "can_create_reminders": true
  },
  "registered_users": ["user_id_1", "user_id_2"],
  "registered_at": "2025-01-01T00:00:00Z"
}
```

---

## 10. Authentication Requirements

### 10.1 Identity Provider

**Primary Choice: AWS Cognito**

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AUTH-001 | Cognito User Pool as primary identity broker | High |
| AUTH-002 | Google OAuth2 federation | High |
| AUTH-003 | Apple Sign-In federation | Medium |
| AUTH-004 | Amazon federation (for Alexa users) | Medium |
| AUTH-005 | Discord OAuth2 for bot account linking | High |

### 10.2 Authentication Flows

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AUTH-FLOW-001 | Alexa Account Linking via Cognito OAuth2 | High |
| AUTH-FLOW-002 | Discord bot OAuth2 linking | High |
| AUTH-FLOW-003 | Device token authentication for IoT | High |
| AUTH-FLOW-004 | JWT validation at API Gateway | High |
| AUTH-FLOW-005 | Refresh token handling | High |

### 10.3 Multi-Factor Authentication

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AUTH-MFA-001 | TOTP authenticator app support | High |
| AUTH-MFA-002 | SMS fallback (optional) | Low |
| AUTH-MFA-003 | MFA required for admin actions | High |

### 10.4 Shared Device Authentication

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AUTH-SHARED-001 | Alexa voice profile recognition | Medium |
| AUTH-SHARED-002 | Explicit user identification ("This is Mike...") | Medium |
| AUTH-SHARED-003 | Shared device mode defaults to family-safe data | High |
| AUTH-SHARED-004 | PIN confirmation for sensitive operations | Medium |

---

## 11. AWS Infrastructure Requirements

### 11.1 Core Services

| Service | Purpose | Status | Priority |
|---------|---------|--------|----------|
| Amazon Bedrock | LLM inference (Claude 3.5 Sonnet/Haiku, Titan) | ✅ Active | High |
| Amazon RDS PostgreSQL | Unified data store (pgvector, PostGIS, btree_gist, pg_trgm) | ✅ Active | High |
| AWS Lambda | Rust API handlers (13), Python agents (1), migrations | ✅ Active | High |
| Amazon API Gateway | REST API | ✅ Active | High |
| Amazon EventBridge | Scheduled triggers (briefings, reminders, calendar sync) | ✅ Active | High |
| Amazon Cognito | Authentication (User Pool: us-east-1) | ✅ Active | High |
| AWS Secrets Manager | DB credentials, OAuth tokens, Discord secrets | ✅ Active | High |
| AWS Location Service | Address geocoding | ✅ Ready | High |
| Amazon CloudWatch | Logging, monitoring | ✅ Active | High |
| Amazon Transcribe | Speech-to-text | ⏳ Ready | High |
| Amazon Polly | Text-to-speech | ⏳ Ready | High |
| Amazon SNS | Push notifications | ⏳ Planned | High |
| Amazon S3 | Backups, document storage | ⏳ Planned | Medium |

### 11.2 Bedrock Model Selection

| Model | Use Case | Status | Priority |
|-------|----------|--------|----------|
| Claude 3.5 Sonnet | Primary agent reasoning | ✅ Active | High |
| Claude 3 Haiku | Simple classification, routing | ✅ Active | High |
| Amazon Titan Embeddings V2 | Vector embeddings (1024-dim) | ✅ Active | High |

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AWS-BR-001 | Claude 3.5 Sonnet as primary reasoning model | High |
| AWS-BR-002 | Claude 3 Haiku for classification to reduce costs (~$0.0001/input) | High |
| AWS-BR-003 | Titan Embeddings V2 for vector generation (1024 dimensions) | High |
| AWS-BR-004 | Model fallback for availability | Medium |

### 11.3 EventBridge Scheduling

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AWS-EB-001 | Morning briefing schedule (user-configurable time) | High |
| AWS-EB-002 | Hourly reminder trigger evaluation | High |
| AWS-EB-003 | Daily calendar sync | High |
| AWS-EB-004 | Per-user timezone support | High |

### 11.4 Security

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| AWS-SEC-001 | Encrypt data at rest (RDS, S3) | High |
| AWS-SEC-002 | Encrypt data in transit (TLS 1.3) | High |
| AWS-SEC-003 | IAM roles with least privilege | High |
| AWS-SEC-004 | Store OAuth tokens in Secrets Manager | High |
| AWS-SEC-005 | CloudTrail audit logging | Medium |
| AWS-SEC-006 | WAF for API Gateway | Medium |

---

## 12. Non-Functional Requirements

### 12.1 Performance

| Req ID | Requirement | Target | Priority |
|--------|-------------|--------|----------|
| NFR-PERF-001 | Query response latency | < 3 seconds | High |
| NFR-PERF-002 | Voice transcription latency | < 2 seconds | High |
| NFR-PERF-003 | Fact ingestion latency | < 5 seconds | High |
| NFR-PERF-004 | Morning briefing generation | < 30 seconds | Medium |
| NFR-PERF-005 | Vector search latency | < 500ms | High |

### 12.2 Scalability

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| NFR-SCALE-001 | Support 10,000+ facts per user | High |
| NFR-SCALE-002 | Support 100+ concurrent queries | Medium |
| NFR-SCALE-003 | Multi-family deployment | High |
| NFR-SCALE-004 | Auto-scale based on demand | High |

### 12.3 Reliability

| Req ID | Requirement | Target | Priority |
|--------|-------------|--------|----------|
| NFR-REL-001 | Service availability | 99.9% | High |
| NFR-REL-002 | Data durability | 99.999999999% | High |
| NFR-REL-003 | Zero data loss on failures | Required | High |
| NFR-REL-004 | Graceful degradation | Required | Medium |

### 12.4 Observability

| Req ID | Requirement | Priority |
|--------|-------------|----------|
| NFR-OBS-001 | Centralized logging in CloudWatch | High |
| NFR-OBS-002 | Distributed tracing with X-Ray | Medium |
| NFR-OBS-003 | Custom metrics for agent performance | Medium |
| NFR-OBS-004 | Alerting for errors and latency | High |

---

## 13. Cost Targets

### 13.1 Target Monthly Costs (Optimized)

| Scenario | Target Cost |
|----------|-------------|
| Single User | ~$20/month |
| Family of 4 | ~$26/month |
| Per-user marginal | ~$5/month |

### 13.2 Cost Breakdown (Family of 4)

| Service | Monthly Cost | Notes |
|---------|--------------|-------|
| RDS PostgreSQL | $14.00 | db.t4g.micro + storage |
| Bedrock (Sonnet) | $5.50 | Primary reasoning |
| Transcribe | $2.70 | Voice-to-text |
| Polly | $2.20 | Text-to-speech |
| Bedrock (Haiku + Titan) | $0.50 | Classification + embeddings |
| AWS Location Service | $1.00 | Geocoding (cached) |
| Lambda/API Gateway/etc | ~$0 | Free tier |
| **Total** | **~$26/month** | |

### 13.3 Cost Optimization Strategies

| Strategy | Savings | Priority |
|----------|---------|----------|
| pgvector instead of OpenSearch Serverless | $163/month | P0 |
| Route simple queries to Haiku | $3/month | P1 |
| Cache Polly common responses | $2/month | P2 |
| Batch embedding requests | Latency improvement | P2 |

---

## 14. Implementation Phases

### Phase 1: Core Knowledge Operations ✅ COMPLETE
- [x] AWS infrastructure setup (RDS PostgreSQL with pgvector, PostGIS, btree_gist, pg_trgm)
- [x] CDK stacks (Network, Database, Auth, API, Agents, Migrations)
- [x] Rust API Lambdas (ingest, query, entities, relationships)
- [x] Python agents (Router, Ingestion, Query) with Strands SDK
- [x] Semantic vector search with Titan Embeddings V2 (1024-dim)
- [x] Entity extraction and linking
- [x] Visibility tiers (1-4) for access control
- [x] Cognito authentication with JWT validation

### Phase 2: Extended Features ✅ COMPLETE
- [x] Hierarchical tagging system with auto-suggestions
- [x] Geographic entity locations with PostGIS
- [x] Proximity-based queries ("Who lives nearby?")
- [x] AWS Location Service geocoding integration
- [x] Time-based reminders (recurring, one-time)
- [x] Location-based reminders (geofence triggers)
- [x] User feedback loop on query results
- [x] Distance calculations (meters, km, miles)

### Phase 3: Calendar & Briefings ✅ COMPLETE
- [x] Google Calendar OAuth2 integration
- [x] Calendar sync to database (15-minute cycle)
- [x] Calendar Agent for event management
- [x] Natural language calendar queries
- [x] Morning Briefing Agent
- [x] Briefing dispatcher with EventBridge scheduling
- [x] Meeting context from knowledge base
- [x] Auto-detection of annual milestones (birthdays, anniversaries)

### Phase 4: Discord Integration ✅ COMPLETE
- [x] Discord bot with slash commands (/remember, /ask, /briefing)
- [x] Discord webhook Lambda with ed25519 signature verification
- [x] Deferred response pattern for 3-second timeout
- [x] Async Lambda follow-up for long-running operations
- [x] Auto-tagging with LLM-extracted relationships
- [x] Temporal parsing for date extraction
- [x] External identity mapping (Discord ID → User ID)

### Phase 5: Multi-User & Family 🔄 IN PROGRESS
- [x] Family hierarchy schema (admin, member, child roles)
- [x] Relationship types (SPOUSE, PARENT_OF, SIBLING, etc.)
- [ ] Tiered access control enforcement across queries
- [ ] Bidirectional access permissions
- [ ] Family shared entities and visibility
- [ ] Per-fact visibility overrides

### Phase 6: Alexa & Smart Mirror ⏳ PLANNED
- [ ] Alexa Custom Skill with account linking
- [ ] Voice profile recognition for multi-user devices
- [ ] Smart Mirror (MagicMirror²) module
- [ ] Shared device mode with restricted data access (Tier 3+)
- [ ] PIN confirmation for sensitive operations

### Phase 7: Proactive Intelligence ⏳ PLANNED
- [ ] Advanced briefing customization (per-user sections)
- [ ] Context-aware reminders
- [ ] Meeting preparation summaries
- [ ] Birthday/anniversary alerts with lead time
- [ ] Deadline notifications
- [ ] SNS push notifications

### Phase 8: Advanced & Optimization ⏳ PLANNED
- [ ] Taxonomy Agent with pattern detection
- [ ] Tag evolution with user feedback
- [ ] Performance optimization for scale (50+ families)
- [ ] Query caching and optimization
- [ ] User analytics and insights
- [ ] Migration path to OpenSearch Serverless (if needed)

---

## Appendix A: Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONT-END PLATFORMS                         │
├──────────┬──────────┬──────────┬──────────┬─────────────────────────┤
│  Alexa   │ Discord  │  Smart   │  Mobile  │   Web                   │
│  Skill   │   Bot    │  Mirror  │   App    │   App                   │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬────────────────────┘
     │          │          │          │          │
     └──────────┴──────────┴────┬─────┴──────────┘
                                │
                    ┌───────────▼───────────┐
                    │     API Gateway       │
                    │   (REST + WebSocket)  │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │      Cognito          │
                    │   (Authentication)    │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   AgentCore Runtime   │
                    │   (Strands Agents)    │
                    └───────────┬───────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
    ┌────▼────────────────┐     │                ┌────▼────┐
    │  RDS PostgreSQL     │     │                │Bedrock  │
    │  ├── pgvector       │     │                │ (LLMs)  │
    │  ├── PostGIS        │     │                └─────────┘
    │  ├── btree_gist     │     │
    │  └── pg_trgm        │     │
    └─────────────────────┘     │
                                │
                    ┌───────────▼───────────┐
                    │   AWS Location Svc    │
                    │     (Geocoding)       │
                    └───────────────────────┘
```

---

## Appendix B: Relationship Access Matrix

| Your Relationship | To Person | Default Tier | Can See |
|-------------------|-----------|--------------|---------|
| Self | - | Tier 1 | Everything |
| Spouse | Partner | Tier 1 | Everything (configurable) |
| Parent | Child | Tier 1 | Everything about child |
| Child | Parent | Tier 2 | Personal, events, not finances |
| Grandparent | Grandchild | Tier 3 | Events, milestones, activities |
| Grandchild | Grandparent | Tier 3 | Events, milestones |
| Sibling | Sibling | Tier 2 | Personal, events |
| Aunt/Uncle | Niece/Nephew | Tier 3 | Events, milestones |

---

*Document last updated: January 2025*
*Implementation Status: Phases 1-4 Complete, Phase 5 In Progress*

# Second Brain - Implementation Plan

**Version:** 1.0
**Date:** January 2025
**Status:** Ready for Development

---

## Executive Summary

This document provides a step-by-step implementation plan for the Second Brain personal knowledge management system. The plan follows the seven phases defined in the requirements document, with detailed tasks ordered by dependencies, technology assignments, and external setup requirements.

**Estimated Total Duration:** 16-20 weeks for a single developer

---

## Table of Contents

1. [Prerequisites and Setup](#1-prerequisites-and-setup)
2. [Phase 1: Core Foundation](#2-phase-1-core-foundation-weeks-1-4)
3. [Phase 2: Voice and Calendar](#3-phase-2-voice-and-calendar-weeks-5-7)
4. [Phase 3: Multi-User and Family](#4-phase-3-multi-user-and-family-weeks-8-10)
5. [Phase 4: Geographic and Temporal Queries](#5-phase-4-geographic-and-temporal-queries-weeks-11-12)
6. [Phase 5: Alexa and Smart Mirror](#6-phase-5-alexa-and-smart-mirror-weeks-13-14)
7. [Phase 6: Proactive Intelligence](#7-phase-6-proactive-intelligence-weeks-15-16)
8. [Phase 7: Advanced Features](#8-phase-7-advanced-features-weeks-17-20)
9. [Deployment Checklist](#9-deployment-checklist)
10. [Risk Mitigation](#10-risk-mitigation)

---

## 1. Prerequisites and Setup

### 1.1 External Account Setup (Before Development)

Complete these setup tasks before starting Phase 1:

| Task | Description | Estimated Time |
|------|-------------|----------------|
| **AWS Account** | Create/configure AWS account with billing alerts | 30 min |
| **AWS Bedrock Access** | Request access to Claude Sonnet, Claude Haiku, Titan Embeddings in us-east-1 | 1-3 days (approval) |
| **Google Cloud Console** | Create project, enable Calendar API, configure OAuth consent screen | 1 hour |
| **Google OAuth Credentials** | Create OAuth 2.0 Client ID for web application | 30 min |
| **Discord Developer Portal** | Create Discord application and bot, get bot token | 30 min |
| **Amazon Developer Console** | Create account for Alexa skill development (Phase 5) | 30 min |
| **Domain Name** | Register domain for OAuth callbacks (optional for dev) | 30 min |

### 1.2 Development Environment Setup

```bash
# Required tools
- Rust (1.75+) with cargo-lambda
- Python 3.12+
- Node.js 20+ (for CDK and web UI)
- AWS CLI v2
- AWS CDK CLI
- Docker (for local testing)
- PostgreSQL 16 client tools
- Git

# Install cargo-lambda for Rust Lambda builds
cargo install cargo-lambda

# Install AWS CDK
npm install -g aws-cdk

# Verify Bedrock access
aws bedrock list-foundation-models --region us-east-1
```

### 1.3 AWS Secrets Setup

Store these secrets in AWS Secrets Manager before deployment:

```bash
# Google OAuth credentials
aws secretsmanager create-secret \
  --name second-brain/google-oauth \
  --secret-string '{"client_id":"xxx","client_secret":"xxx"}'

# Discord bot credentials
aws secretsmanager create-secret \
  --name second-brain/discord \
  --secret-string '{"bot_token":"xxx","application_id":"xxx","public_key":"xxx"}'

# (Phase 5) Amazon OAuth for Alexa
aws secretsmanager create-secret \
  --name second-brain/amazon-oauth \
  --secret-string '{"client_id":"xxx","client_secret":"xxx"}'
```

---

## 2. Phase 1: Core Foundation (Weeks 1-4)

**Goal:** Deploy basic infrastructure, implement text-based fact ingestion and querying via Discord.

### Week 1: Project Scaffolding and Infrastructure Base

#### Task 1.1: Initialize Project Structure
**Tech Stack:** N/A (file structure)
**Dependencies:** None

Create the project directory structure as defined in requirements:

```
second_brain/
├── infra/                          # Python CDK
│   ├── app.py
│   ├── stacks/
│   ├── constructs/
│   └── cdk.json
├── lambdas/                        # Rust
│   ├── Cargo.toml                  # Workspace
│   ├── shared/
│   ├── api-gateway/
│   ├── discord-webhook/
│   ├── alexa-skill/
│   ├── event-triggers/
│   └── geocoder/
├── agents/                         # Python (Strands SDK)
│   ├── pyproject.toml
│   ├── src/
│   └── agentcore_entry.py
├── web/                            # TypeScript + React
└── docs/
```

**Deliverable:** Empty project scaffold with package manifests

#### Task 1.2: Implement CDK Network Stack
**Tech Stack:** Python CDK
**Dependencies:** Task 1.1

Create `/infra/stacks/network.py`:
- VPC with 2 AZs
- Public, private, and isolated subnets
- Single NAT Gateway (cost optimization)
- Security groups for Lambda and RDS
- VPC endpoints for S3, Secrets Manager, Bedrock

**Deliverable:** Deployable NetworkStack

#### Task 1.3: Implement CDK Database Stack
**Tech Stack:** Python CDK
**Dependencies:** Task 1.2

Create `/infra/stacks/database.py`:
- RDS PostgreSQL 16 on db.t4g.micro
- Parameter group with pgvector preloaded
- Secrets Manager for credentials
- Custom resource Lambda to initialize extensions
- Extension initialization: uuid-ossp, pgvector, postgis, btree_gist, pg_trgm

**Deliverable:** Deployable DatabaseStack with extensions enabled

#### Task 1.4: Deploy Network and Database
**Tech Stack:** CDK CLI
**Dependencies:** Tasks 1.2, 1.3

```bash
cd infra
cdk deploy SecondBrainNetwork SecondBrainDatabase
```

**Deliverable:** Running VPC and RDS instance

### Week 2: Database Schema and Auth

#### Task 2.1: Create Database Migrations
**Tech Stack:** SQL
**Dependencies:** Task 1.4

Create SQL migration scripts following `/docs/design/postgresql-schema.md`:

1. `001_users_families.sql` - users, families, family_members tables
2. `002_relationships.sql` - relationships, user_access_cache tables
3. `003_entities.sql` - entities, entity_attributes, entity_locations tables
4. `004_facts.sql` - facts, fact_embeddings, entity_mentions tables
5. `005_tags.sql` - tags, fact_tags tables
6. `006_calendar.sql` - calendar_events, calendar_event_attendees, reminders tables
7. `007_devices.sql` - devices, device_users tables
8. `008_conversations.sql` - conversations, messages tables
9. `009_functions.sql` - refresh_user_access_cache function and triggers

**Deliverable:** Versioned migration scripts

#### Task 2.2: Run Database Migrations
**Tech Stack:** psql/sqlx-cli
**Dependencies:** Task 2.1

Execute migrations against the RDS instance.

**Deliverable:** Fully initialized database schema

#### Task 2.3: Implement CDK Auth Stack
**Tech Stack:** Python CDK
**Dependencies:** Google OAuth setup

Create `/infra/stacks/auth.py`:
- Cognito User Pool
- Google identity provider federation
- Web app client (no secret)
- Discord app client (with secret)
- Alexa app client (with secret, for Phase 5)
- Cognito domain

**Deliverable:** Deployable AuthStack

#### Task 2.4: Deploy Auth Stack
**Tech Stack:** CDK CLI
**Dependencies:** Task 2.3

```bash
cdk deploy SecondBrainAuth
```

**Deliverable:** Running Cognito User Pool

### Week 3: Rust Lambda Foundation and API

#### Task 3.1: Create Rust Shared Library
**Tech Stack:** Rust
**Dependencies:** Task 2.2

Create `/lambdas/shared/`:
- Database connection pool with sqlx
- Request/response types
- JWT validation utilities
- Error handling types
- Bedrock client wrapper
- AWS Secrets Manager integration

Key crates:
```toml
[dependencies]
lambda_runtime = "0.8"
lambda_http = "0.8"
sqlx = { version = "0.7", features = ["postgres", "runtime-tokio", "tls-rustls"] }
serde = { version = "1.0", features = ["derive"] }
tokio = { version = "1", features = ["full"] }
aws-sdk-secretsmanager = "1.0"
aws-sdk-bedrockruntime = "1.0"
```

**Deliverable:** Shared Rust library

#### Task 3.2: Implement Query Lambda
**Tech Stack:** Rust
**Dependencies:** Task 3.1

Create `/lambdas/api-gateway/src/bin/query.rs`:
- Parse incoming query request
- Validate JWT and extract user_id
- Invoke AgentCore (or mock for now)
- Return formatted response

**Deliverable:** Query Lambda binary

#### Task 3.3: Implement Ingest Lambda
**Tech Stack:** Rust
**Dependencies:** Task 3.1

Create `/lambdas/api-gateway/src/bin/ingest.rs`:
- Parse incoming fact text
- Validate JWT and extract user_id
- Invoke AgentCore (or mock for now)
- Return confirmation

**Deliverable:** Ingest Lambda binary

#### Task 3.4: Implement CDK API Stack
**Tech Stack:** Python CDK
**Dependencies:** Tasks 3.2, 3.3

Create `/infra/stacks/api.py`:
- REST API Gateway
- Cognito authorizer
- Lambda integrations for /v1/query and /v1/ingest
- CORS configuration

Create `/infra/constructs/rust_lambda.py`:
- Custom construct for building Rust Lambdas with cargo-lambda

**Deliverable:** Deployable ApiStack

#### Task 3.5: Deploy API Stack
**Tech Stack:** CDK CLI
**Dependencies:** Task 3.4

```bash
cd lambdas && cargo lambda build --release --arm64
cd ../infra && cdk deploy SecondBrainApi
```

**Deliverable:** Running API Gateway with Lambda handlers

### Week 4: Python Agents and Discord Bot

#### Task 4.1: Create Python Agent Project
**Tech Stack:** Python
**Dependencies:** None

Create `/agents/`:
- pyproject.toml with Strands SDK, asyncpg, boto3
- Project structure for agents

**Deliverable:** Python agent project scaffold

#### Task 4.2: Implement Shared Tools
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 4.1

Create `/agents/src/shared/tools/`:
- `database.py` - fact_store, fact_search tools
- `vector_search.py` - semantic_search, generate_embedding tools
- `entities.py` - entity_search, entity_create, entity_get_details tools

**Deliverable:** Core Strands tools

#### Task 4.3: Implement Router Agent
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 4.2

Create `/agents/src/router/agent.py`:
- System prompt for request classification
- Handoff logic to specialized agents

**Deliverable:** Router agent

#### Task 4.4: Implement Ingestion Agent
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Tasks 4.2, 4.3

Create `/agents/src/ingestion/agent.py`:
- Entity extraction from natural language
- Visibility tier classification
- Fact storage with embedding generation

**Deliverable:** Ingestion agent

#### Task 4.5: Implement Query Agent
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Tasks 4.2, 4.3

Create `/agents/src/query/agent.py`:
- Semantic search integration
- Permission-aware result filtering
- Response synthesis

**Deliverable:** Query agent

#### Task 4.6: Implement Swarm Configuration
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Tasks 4.3, 4.4, 4.5

Create `/agents/src/swarm.py`:
- Combine agents into Swarm
- Configure handoff limits and timeouts

**Deliverable:** Multi-agent swarm

#### Task 4.7: Implement AgentCore Entry Point
**Tech Stack:** Python
**Dependencies:** Task 4.6

Create `/agents/agentcore_entry.py`:
- BedrockAgentCoreApp initialization
- Database pool setup
- AWS client initialization
- Request handling

**Deliverable:** AgentCore deployable application

#### Task 4.8: Implement CDK Agents Stack
**Tech Stack:** Python CDK
**Dependencies:** Task 4.7

Create `/infra/stacks/agents.py`:
- IAM role for AgentCore
- ECR repository for agent container
- Docker image build
- AWS Location Service place index

**Deliverable:** Deployable AgentsStack

#### Task 4.9: Implement Discord Webhook Lambda
**Tech Stack:** Rust
**Dependencies:** Task 3.1

Create `/lambdas/discord-webhook/`:
- Discord interaction signature validation
- Slash command parsing
- AgentCore invocation
- Response formatting for Discord

**Deliverable:** Discord Lambda binary

#### Task 4.10: Implement CDK Integrations Stack (Discord only)
**Tech Stack:** Python CDK
**Dependencies:** Task 4.9

Create `/infra/stacks/integrations.py`:
- Discord webhook Lambda
- API Gateway endpoint for Discord webhook
- Secrets for Discord credentials

**Deliverable:** Deployable IntegrationsStack (partial)

#### Task 4.11: Deploy Agents and Integrations
**Tech Stack:** CDK CLI
**Dependencies:** Tasks 4.8, 4.10

```bash
cdk deploy SecondBrainAgents SecondBrainIntegrations
```

**Deliverable:** Running agent runtime and Discord bot

#### Task 4.12: Configure Discord Bot
**Tech Stack:** Discord Developer Portal
**Dependencies:** Task 4.11

- Register slash commands (/remember, /ask)
- Set interaction endpoint URL to API Gateway
- Invite bot to test server

**Deliverable:** Functional Discord bot with text commands

### Phase 1 Milestone Checklist

- [ ] VPC and networking deployed
- [ ] RDS PostgreSQL running with extensions
- [ ] Database schema applied
- [ ] Cognito User Pool configured
- [ ] API Gateway with /v1/query and /v1/ingest endpoints
- [ ] Rust Lambdas deployed
- [ ] Python agents deployed to AgentCore
- [ ] Discord bot responding to /remember and /ask commands
- [ ] End-to-end fact ingestion and retrieval working

---

## 3. Phase 2: Voice and Calendar (Weeks 5-7)

**Goal:** Add voice input/output via Discord and integrate Google Calendar.

### Week 5: Voice Integration

#### Task 5.1: Add Amazon Transcribe Integration
**Tech Stack:** Rust
**Dependencies:** Phase 1

Extend Discord webhook Lambda:
- Stream audio from Discord voice channel
- Call Amazon Transcribe streaming API
- Convert transcript to text query

**Deliverable:** Voice-to-text in Discord Lambda

#### Task 5.2: Add Amazon Polly Integration
**Tech Stack:** Rust
**Dependencies:** Phase 1

Extend Discord webhook Lambda:
- Convert agent response to speech
- Use Polly Neural voices
- Stream audio back to Discord

**Deliverable:** Text-to-speech responses

#### Task 5.3: Implement Voice Commands in Discord
**Tech Stack:** Rust
**Dependencies:** Tasks 5.1, 5.2

- Join/leave voice channel commands
- Voice activity detection
- Response delivery to voice channel

**Deliverable:** Full voice interaction flow

#### Task 5.4: Update IAM Policies
**Tech Stack:** Python CDK
**Dependencies:** Tasks 5.1, 5.2

Add Transcribe and Polly permissions to Lambda roles.

**Deliverable:** Updated IntegrationsStack

### Week 6: Calendar Agent

#### Task 6.1: Implement Google Calendar OAuth Flow
**Tech Stack:** Rust
**Dependencies:** Google OAuth setup

Create calendar OAuth callback handler:
- Exchange authorization code for tokens
- Store refresh token in Secrets Manager
- Handle token refresh

**Deliverable:** OAuth integration for Google Calendar

#### Task 6.2: Implement Calendar Sync Lambda
**Tech Stack:** Rust
**Dependencies:** Task 6.1

Create `/lambdas/event-triggers/src/bin/calendar_sync.rs`:
- Fetch events from Google Calendar API
- Upsert to calendar_events table
- Link attendees to entities when possible

**Deliverable:** Calendar sync Lambda

#### Task 6.3: Implement Calendar Agent
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 6.2

Create `/agents/src/calendar/agent.py`:
- Calendar query tool
- Calendar sync tool
- Event creation tool
- Entity linking for attendees

**Deliverable:** Calendar agent

#### Task 6.4: Implement Calendar Tools
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 6.3

Create `/agents/src/shared/tools/calendar.py`:
- calendar_get_events tool
- calendar_sync tool

**Deliverable:** Calendar Strands tools

#### Task 6.5: Add Calendar Endpoints
**Tech Stack:** Rust + CDK
**Dependencies:** Tasks 6.2, 6.3

Create `/lambdas/api-gateway/src/bin/calendar.rs`:
- GET /v1/calendar
- POST /v1/calendar

Update ApiStack with calendar endpoints.

**Deliverable:** Calendar API endpoints

### Week 7: Testing and Refinement

#### Task 7.1: Implement CDK Scheduling Stack
**Tech Stack:** Python CDK
**Dependencies:** Task 6.2

Create `/infra/stacks/scheduling.py`:
- EventBridge rule for calendar sync (every 15 minutes)

**Deliverable:** Deployable SchedulingStack (partial)

#### Task 7.2: End-to-End Voice Testing
**Tech Stack:** Manual testing
**Dependencies:** Phase 2 tasks

Test scenarios:
- Voice ingestion of facts
- Voice queries with spoken responses
- Calendar queries by voice

**Deliverable:** Test report

#### Task 7.3: Deploy Phase 2
**Tech Stack:** CDK CLI
**Dependencies:** All Phase 2 tasks

```bash
cdk deploy SecondBrainIntegrations SecondBrainScheduling
```

**Deliverable:** Updated deployment

### Phase 2 Milestone Checklist

- [ ] Voice input working in Discord
- [ ] Voice responses via Polly
- [ ] Google Calendar OAuth flow complete
- [ ] Calendar sync running on schedule
- [ ] Calendar queries returning events
- [ ] Calendar agent integrated into swarm

---

## 4. Phase 3: Multi-User and Family (Weeks 8-10)

**Goal:** Implement family data model, relationship graph, and tiered access control.

### Week 8: Family Data Model

#### Task 8.1: Create Family Management APIs
**Tech Stack:** Rust
**Dependencies:** Phase 2

Create new Lambda handlers:
- POST /v1/families - Create family
- GET /v1/families/{id} - Get family details
- POST /v1/families/{id}/members - Invite member
- DELETE /v1/families/{id}/members/{user_id} - Remove member

**Deliverable:** Family management endpoints

#### Task 8.2: Implement User Signup Flow
**Tech Stack:** Rust + Cognito
**Dependencies:** Task 8.1

- Post-confirmation Lambda trigger
- Create user record in database
- Initialize default settings

**Deliverable:** User provisioning automation

#### Task 8.3: Update Agents for Multi-User Context
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 8.1

Update all agents:
- Accept user_id and family_ids in context
- Pass context to all tool calls

**Deliverable:** Multi-user aware agents

### Week 9: Relationship Graph

#### Task 9.1: Implement Relationship Management APIs
**Tech Stack:** Rust
**Dependencies:** Task 8.1

Create endpoints:
- POST /v1/relationships - Create relationship
- GET /v1/relationships - List relationships
- PUT /v1/relationships/{id} - Update access tier
- DELETE /v1/relationships/{id} - Remove relationship

**Deliverable:** Relationship management endpoints

#### Task 9.2: Implement Access Cache Refresh
**Tech Stack:** SQL + Database triggers
**Dependencies:** Phase 1

Verify trigger-based cache refresh:
- Test relationship changes propagate to cache
- Test cache accurately reflects access permissions

**Deliverable:** Working access cache

#### Task 9.3: Update Query Agent for Permissions
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Tasks 9.1, 9.2

Modify fact_search and semantic_search tools:
- Join with user_access_cache
- Filter by visibility_tier <= access_tier
- Handle family-owned facts

**Deliverable:** Permission-aware query agent

### Week 10: Visibility Classification

#### Task 10.1: Implement Visibility Classification in Ingestion Agent
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 9.3

Update ingestion agent:
- Auto-classify content type (medical, financial, events, etc.)
- Assign default visibility tier
- Ask user for confirmation on ambiguous cases

**Deliverable:** Smart visibility classification

#### Task 10.2: Implement Per-Fact Visibility Override
**Tech Stack:** Rust
**Dependencies:** Task 10.1

Add endpoint:
- PUT /v1/facts/{id}/visibility - Update visibility tier

**Deliverable:** Visibility override API

#### Task 10.3: End-to-End Family Testing
**Tech Stack:** Manual testing
**Dependencies:** All Phase 3 tasks

Test scenarios:
- Parent can see all child data
- Grandparent sees only Tier 3+ data
- Family-owned facts visible to all members
- Conversation history never shared

**Deliverable:** Test report

### Phase 3 Milestone Checklist

- [ ] Family creation and member management
- [ ] Relationship graph with access tiers
- [ ] Automatic visibility classification
- [ ] Permission-aware queries
- [ ] Tested family data isolation

---

## 5. Phase 4: Geographic and Temporal Queries (Weeks 11-12)

**Goal:** Enable location-based and historical queries.

### Week 11: Geographic Features

#### Task 11.1: Create AWS Location Service Place Index
**Tech Stack:** Python CDK
**Dependencies:** Phase 3

Add to AgentsStack:
- Place index resource
- IAM permissions for geocoding

**Deliverable:** Place index for geocoding

#### Task 11.2: Implement Geocoding Lambda
**Tech Stack:** Rust
**Dependencies:** Task 11.1

Create `/lambdas/geocoder/`:
- Call AWS Location Service SearchPlaceIndexForText
- Cache results in entity_locations table
- Return coordinates and confidence

**Deliverable:** Geocoding Lambda

#### Task 11.3: Implement Geographic Tools
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Tasks 11.1, 11.2

Create `/agents/src/shared/tools/geographic.py`:
- proximity_search tool
- geocode_address tool

**Deliverable:** Geographic Strands tools

#### Task 11.4: Update Query Agent for Geographic Queries
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 11.3

Add capabilities:
- Interpret "walking distance", "nearby", etc.
- Context-aware distance based on subject's age
- Call proximity_search for location queries

**Deliverable:** Location-aware query agent

#### Task 11.5: Add Location to Entities
**Tech Stack:** Rust
**Dependencies:** Task 11.2

Create endpoint:
- POST /v1/entities/{id}/locations - Add location
- Trigger geocoding automatically

**Deliverable:** Entity location management

### Week 12: Temporal Features

#### Task 12.1: Update Ingestion Agent for Temporal Extraction
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Phase 3

Enhance ingestion agent:
- Parse date expressions ("in 1996", "from 1995 to 1998")
- Store valid_from/valid_to on facts
- Ask for time period when storing historical facts

**Deliverable:** Temporal fact ingestion

#### Task 12.2: Implement Temporal Query Tools
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 12.1

Update fact_search tool:
- Add as_of_date parameter
- Support range overlap queries

**Deliverable:** Temporal query support

#### Task 12.3: Implement Historical Relationship Queries
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Task 12.2

Enable queries like:
- "Who did I work with at Acme in 1996?"
- "What was my phone number in 2004?"

**Deliverable:** Temporal relationship queries

#### Task 12.4: End-to-End Testing
**Tech Stack:** Manual testing
**Dependencies:** All Phase 4 tasks

Test scenarios:
- "Friends within walking distance of home"
- "Who worked at Acme Corp in 1996?"
- "All addresses I've lived at"

**Deliverable:** Test report

### Phase 4 Milestone Checklist

- [ ] AWS Location Service geocoding working
- [ ] Entity locations stored with coordinates
- [ ] Proximity queries returning results
- [ ] Temporal facts with valid_from/valid_to
- [ ] Point-in-time queries working
- [ ] Historical relationship queries working

---

## 6. Phase 5: Alexa and Smart Mirror (Weeks 13-14)

**Goal:** Add Alexa Custom Skill and Smart Mirror integration.

### Week 13: Alexa Skill

#### Task 13.1: Create Alexa Skill in Developer Console
**Tech Stack:** Alexa Developer Console
**Dependencies:** Amazon Developer account

- Create custom skill
- Define intents: QueryIntent, RememberIntent, CalendarIntent
- Configure account linking with Cognito

**Deliverable:** Alexa skill configuration

#### Task 13.2: Implement Alexa Lambda
**Tech Stack:** Rust
**Dependencies:** Task 13.1

Create `/lambdas/alexa-skill/`:
- Parse Alexa request format
- Handle account linking token
- Invoke AgentCore
- Format response for Alexa
- Handle 8-second timeout constraint

**Deliverable:** Alexa skill Lambda

#### Task 13.3: Configure Alexa Account Linking
**Tech Stack:** Alexa Developer Console + Cognito
**Dependencies:** Tasks 13.1, 13.2

- Set authorization URL to Cognito hosted UI
- Configure client ID/secret from Alexa client
- Test linking flow

**Deliverable:** Working account linking

#### Task 13.4: Update IntegrationsStack for Alexa
**Tech Stack:** Python CDK
**Dependencies:** Task 13.2

Add Alexa Lambda to IntegrationsStack:
- Lambda function
- Alexa trigger permission

**Deliverable:** Updated IntegrationsStack

### Week 14: Smart Mirror and Shared Device Mode

#### Task 14.1: Implement Device Registry
**Tech Stack:** Rust
**Dependencies:** Phase 5 schema

Create endpoints:
- POST /v1/devices - Register device
- GET /v1/devices - List devices
- PUT /v1/devices/{id} - Update device settings
- DELETE /v1/devices/{id} - Deauthorize device

**Deliverable:** Device management API

#### Task 14.2: Implement Shared Device Mode
**Tech Stack:** Rust + Python
**Dependencies:** Task 14.1

- Device token authentication
- Max visibility tier enforcement
- Default to family-safe data (Tier 3+)

**Deliverable:** Shared device access control

#### Task 14.3: Create Smart Mirror Module
**Tech Stack:** JavaScript (MagicMirror2)
**Dependencies:** Tasks 14.1, 14.2

Create MagicMirror2 module:
- Authenticate with device token
- Display morning briefing
- Show upcoming calendar events
- Show reminders

**Deliverable:** MagicMirror2 module

#### Task 14.4: Deploy and Test
**Tech Stack:** CDK CLI + manual
**Dependencies:** All Phase 5 tasks

```bash
cdk deploy SecondBrainIntegrations
```

Test Alexa skill and Smart Mirror.

**Deliverable:** Working voice assistant on Alexa

### Phase 5 Milestone Checklist

- [ ] Alexa Custom Skill created
- [ ] Account linking working
- [ ] Alexa voice commands functional
- [ ] Device registry implemented
- [ ] Shared device mode enforcing tier limits
- [ ] Smart Mirror module displaying data

---

## 7. Phase 6: Proactive Intelligence (Weeks 15-16)

**Goal:** Implement morning briefings, reminders, and proactive notifications.

### Week 15: Scheduler Agent and Briefings

#### Task 15.1: Implement Scheduler Agent
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Phase 5

Create `/agents/src/scheduler/agent.py`:
- Morning briefing generation
- Trigger evaluation
- Notification queuing

**Deliverable:** Scheduler agent

#### Task 15.2: Implement Briefing Dispatcher Lambda
**Tech Stack:** Rust
**Dependencies:** Task 15.1

Create `/lambdas/event-triggers/src/bin/briefing_dispatcher.rs`:
- Query users by timezone
- Trigger briefing generation for users at their configured time
- Handle batch processing

**Deliverable:** Briefing dispatcher Lambda

#### Task 15.3: Implement Morning Briefing Generation
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Tasks 15.1, 15.2

Briefing content:
- Calendar summary for today
- Birthdays and anniversaries (today + 7 days)
- Approaching deadlines
- Meeting context for today's attendees

**Deliverable:** Briefing generation

#### Task 15.4: Update SchedulingStack
**Tech Stack:** Python CDK
**Dependencies:** Task 15.2

Add EventBridge rule:
- Hourly trigger for briefing dispatcher

**Deliverable:** Updated SchedulingStack

### Week 16: Reminders and Notifications

#### Task 16.1: Implement Reminder Evaluator Lambda
**Tech Stack:** Rust
**Dependencies:** Phase 5 schema

Create `/lambdas/event-triggers/src/bin/reminder_evaluator.rs`:
- Query pending reminders
- Evaluate trigger conditions
- Queue notifications

**Deliverable:** Reminder evaluator Lambda

#### Task 16.2: Implement SNS Notification Delivery
**Tech Stack:** Python CDK + Rust
**Dependencies:** Task 16.1

- Create SNS topic for notifications
- Implement push notification delivery
- Discord DM delivery for Discord users

**Deliverable:** Notification delivery system

#### Task 16.3: Implement Reminder APIs
**Tech Stack:** Rust
**Dependencies:** Task 16.1

Create endpoints:
- POST /v1/reminders - Create reminder
- GET /v1/reminders - List reminders
- PUT /v1/reminders/{id} - Update/snooze
- DELETE /v1/reminders/{id} - Cancel

**Deliverable:** Reminder management API

#### Task 16.4: Add GET /v1/briefing Endpoint
**Tech Stack:** Rust
**Dependencies:** Task 15.3

Implement on-demand briefing endpoint.

**Deliverable:** Briefing API endpoint

#### Task 16.5: Deploy and Test
**Tech Stack:** CDK CLI + manual
**Dependencies:** All Phase 6 tasks

```bash
cdk deploy SecondBrainScheduling
```

Test morning briefings and reminders.

**Deliverable:** Working proactive system

### Phase 6 Milestone Checklist

- [ ] Scheduler agent implemented
- [ ] Morning briefings generating on schedule
- [ ] Reminder triggers evaluating
- [ ] Notifications delivering via SNS/Discord
- [ ] Briefing API endpoint working

---

## 8. Phase 7: Advanced Features (Weeks 17-20)

**Goal:** Add taxonomy agent, multi-agent coordination, and optimization.

### Week 17-18: Taxonomy Agent

#### Task 17.1: Implement Taxonomy Agent
**Tech Stack:** Python (Strands SDK)
**Dependencies:** Phase 6

Create `/agents/src/taxonomy/agent.py`:
- Pattern detection for co-occurring tags
- Gap detection for untagged facts
- Taxonomy evolution proposals

**Deliverable:** Taxonomy agent

#### Task 17.2: Implement Tag Management APIs
**Tech Stack:** Rust
**Dependencies:** Task 17.1

Create endpoints:
- POST /v1/tags - Create tag
- GET /v1/tags - List tags (hierarchical)
- PUT /v1/tags/{id} - Update tag
- POST /v1/tags/suggestions - Get AI suggestions

**Deliverable:** Tag management API

#### Task 17.3: User Feedback Loop
**Tech Stack:** Rust + Python
**Dependencies:** Task 17.1

Track:
- Dismissed vs acted-upon notifications
- Query result satisfaction
- Tag acceptance/rejection

Update agent behavior based on feedback.

**Deliverable:** Learning feedback system

### Week 19: Performance Optimization

#### Task 19.1: Implement Response Caching
**Tech Stack:** Rust
**Dependencies:** Phase 6

- Cache common Polly responses
- Cache embedding lookups
- Implement cache invalidation

**Deliverable:** Caching layer

#### Task 19.2: Query Optimization
**Tech Stack:** SQL
**Dependencies:** Phase 6

- Analyze slow queries
- Add missing indexes
- Optimize complex joins

**Deliverable:** Optimized queries

#### Task 19.3: Cost Optimization
**Tech Stack:** Python CDK + agents
**Dependencies:** Phase 6

- Route simple classification to Haiku
- Batch embedding requests
- Review and optimize Bedrock usage

**Deliverable:** Reduced per-query cost

### Week 20: Monitoring and Documentation

#### Task 20.1: Implement CDK Monitoring Stack
**Tech Stack:** Python CDK
**Dependencies:** Phase 6

Create `/infra/stacks/monitoring.py`:
- CloudWatch dashboard
- Lambda metrics widgets
- RDS metrics widgets
- API Gateway metrics
- Error rate alarm
- Latency alarm
- CPU alarm

**Deliverable:** Deployable MonitoringStack

#### Task 20.2: Deploy Monitoring
**Tech Stack:** CDK CLI
**Dependencies:** Task 20.1

```bash
cdk deploy SecondBrainMonitoring
```

**Deliverable:** Operational monitoring

#### Task 20.3: Final Documentation
**Tech Stack:** Markdown
**Dependencies:** All phases

- API documentation
- User guide
- Operations runbook
- Architecture decision records

**Deliverable:** Complete documentation

### Phase 7 Milestone Checklist

- [ ] Taxonomy agent proposing tag improvements
- [ ] User feedback loop capturing signals
- [ ] Response caching implemented
- [ ] Query performance optimized
- [ ] Cost optimization applied
- [ ] CloudWatch monitoring deployed
- [ ] Documentation complete

---

## 9. Deployment Checklist

### Pre-Production Checklist

| Item | Status |
|------|--------|
| All unit tests passing | [ ] |
| Integration tests passing | [ ] |
| Load testing completed | [ ] |
| Security review completed | [ ] |
| Cost analysis reviewed | [ ] |
| Backup/restore tested | [ ] |
| Monitoring alerts configured | [ ] |
| Runbook documented | [ ] |
| Deletion protection enabled on RDS | [ ] |
| WAF configured on API Gateway | [ ] |

### Deployment Order

```
1. cdk deploy SecondBrainNetwork
2. cdk deploy SecondBrainDatabase
3. Run database migrations
4. cdk deploy SecondBrainAuth
5. cdk deploy SecondBrainAgents
6. cdk deploy SecondBrainApi
7. cdk deploy SecondBrainIntegrations
8. cdk deploy SecondBrainScheduling
9. cdk deploy SecondBrainMonitoring
```

---

## 10. Risk Mitigation

### Technical Risks

| Risk | Mitigation |
|------|------------|
| AgentCore availability/limits | Build fallback to direct Bedrock invocation |
| Bedrock quota limits | Request quota increase before launch |
| RDS connection exhaustion | Implement connection pooling in Lambdas |
| Cold start latency | Use provisioned concurrency for critical Lambdas |
| Discord rate limits | Implement exponential backoff |

### Cost Risks

| Risk | Mitigation |
|------|------------|
| Bedrock costs exceed budget | Implement usage quotas per user |
| RDS costs grow | Monitor and right-size instance |
| NAT Gateway data transfer | Use VPC endpoints where possible |

### Operational Risks

| Risk | Mitigation |
|------|------------|
| Database corruption | Automated daily backups, point-in-time recovery |
| Secret exposure | Rotate secrets regularly, audit access |
| Service outage | Multi-AZ deployment, graceful degradation |

---

## Appendix A: Key File Paths

```
second_brain/
├── docs/
│   ├── requirements.md
│   ├── implementation-plan.md
│   └── design/
│       ├── postgresql-schema.md
│       ├── strands-agent-architecture.md
│       └── cdk-infrastructure.md
├── infra/
│   ├── app.py
│   ├── stacks/
│   │   ├── network.py
│   │   ├── database.py
│   │   ├── auth.py
│   │   ├── api.py
│   │   ├── agents.py
│   │   ├── integrations.py
│   │   ├── scheduling.py
│   │   └── monitoring.py
│   └── constructs/
│       └── rust_lambda.py
├── lambdas/
│   ├── Cargo.toml
│   ├── shared/
│   ├── api-gateway/
│   ├── discord-webhook/
│   ├── alexa-skill/
│   ├── event-triggers/
│   └── geocoder/
├── agents/
│   ├── pyproject.toml
│   ├── src/
│   │   ├── router/
│   │   ├── ingestion/
│   │   ├── query/
│   │   ├── calendar/
│   │   ├── scheduler/
│   │   └── shared/tools/
│   └── agentcore_entry.py
└── web/
```

---

*Document Version: 1.0*
*Ready for Implementation*

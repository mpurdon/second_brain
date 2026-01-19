# Second Brain

A voice-enabled personal knowledge management system for families. Store facts, track relationships, manage calendars, and receive proactive intelligence through Discord, Alexa, and smart mirrors.

## Overview

Second Brain is a centralized repository for personal and family knowledge that enables:
- **Natural language fact ingestion** - Store information conversationally
- **Intelligent retrieval** - Semantic search, geographic queries, temporal filters
- **Multi-user family access** - Tiered visibility controls based on relationships
- **Proactive intelligence** - Morning briefings, reminders, notifications
- **Multi-platform access** - Discord, Alexa, web, smart mirrors

## Features

### Core Knowledge Operations (Phase 1-2)
- Fact ingestion with automatic entity extraction
- Entity management (people, places, organizations, projects)
- Semantic vector search with pgvector (1024-dim embeddings)
- Visibility tiers (1-4) for access control
- Hierarchical tagging system with auto-suggestions
- Geographic entity locations with PostGIS
- Proximity-based queries ("Who lives nearby?")
- Time-based and location-based reminders

### Calendar & Briefings (Phase 3)
- Google Calendar OAuth2 integration
- Automatic calendar sync (15-minute cycle)
- Natural language calendar queries
- Morning briefing generation
- Meeting context from knowledge base
- Auto-detection of annual milestones (birthdays, anniversaries)

### Discord Integration (Phase 4)
- Slash commands: `/remember`, `/ask`, `/briefing`
- Deferred response pattern for long operations
- Auto-tagging with LLM-extracted relationships
- Temporal parsing for date extraction

### Coming Soon
- **Phase 5**: Multi-user family hierarchy with RBAC
- **Phase 6**: Alexa skill with voice profiles
- **Phase 7**: Smart Mirror (MagicMirror2) integration
- **Phase 8**: Advanced taxonomy and pattern detection

## Architecture

```
+------------------------------------------------------------------+
|                    FRONT-END PLATFORMS                           |
+----------+----------+----------+----------+---------------------+
|  Alexa   | Discord  |  Smart   |  Mobile  |   Web               |
|  Skill   |   Bot    |  Mirror  |   App    |   App (Next.js)     |
+----+-----+----+-----+----+-----+----+-----+----+-----------------+
     |          |          |          |          |
     +----------+----------+----+-----+----------+
                                |
                    +-----------v-----------+
                    |     API Gateway       |
                    |   REST + WebSocket    |
                    |   (Rust Lambdas)      |
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |      Cognito          |
                    |   (Authentication)    |
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |  Strands Agents       |
                    |  (Python Lambda)      |
                    |  - Ingestion          |
                    |  - Query              |
                    |  - Briefing           |
                    |  - Calendar           |
                    |  - Scheduler          |
                    +-----------+-----------+
                                |
         +----------------------+----------------------+
         |                      |                      |
    +----v----------------+     |                +----v----+
    |  RDS PostgreSQL     |     |                |Bedrock  |
    |  - pgvector         |     |                | (LLMs)  |
    |  - PostGIS          |     |                +---------+
    |  - btree_gist       |     |
    |  - pg_trgm          |     |
    +---------------------+     |
                                |
                    +-----------v-----------+
                    |   AWS Location Svc    |
                    |     (Geocoding)       |
                    +-----------------------+
```

**Request Flow:**
1. User input via Discord, Alexa, web, or API
2. Rust Lambda validates request & auth (10ms cold start)
3. Invokes Python Agent Lambda via Strands SDK
4. Agent executes tools (database, vector search, external APIs)
5. Rust Lambda formats response & returns to user

## Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **API Lambdas** | Rust 1.75+ | 10ms cold starts, type-safe validation |
| **AI Agents** | Python 3.12+ | Strands SDK, rapid iteration |
| **Infrastructure** | AWS CDK (Python) | Mature constructs, IaC |
| **Web UI** | Next.js 14 / React 18 | Modern frontend |
| **Database** | PostgreSQL 15+ | pgvector, PostGIS, btree_gist |
| **LLM** | Claude 3.5 Sonnet/Haiku | via Amazon Bedrock |

### Key Dependencies

**Rust (API Lambdas)**
- `lambda_runtime` / `lambda_http` - AWS Lambda execution
- `sqlx` - Async PostgreSQL with compile-time verification
- `serde` - JSON serialization
- `tokio` - Async runtime
- `aws-sdk-*` - Bedrock, SecretsManager, Lambda, etc.

**Python (Agents)**
- `strands-sdk` - Agentic framework with @tool decorator
- `asyncpg` - Async PostgreSQL driver
- `boto3` - AWS SDK
- `pydantic` - Data validation

## Project Structure

```
second_brain/
├── infra/                          # AWS CDK Infrastructure
│   ├── app.py                      # CDK app entry point
│   ├── stacks/                     # CDK stack definitions
│   │   ├── api.py                  # API Gateway + Rust Lambdas
│   │   ├── agents.py               # Python agent Lambda
│   │   ├── database.py             # RDS PostgreSQL
│   │   ├── auth.py                 # Cognito
│   │   ├── integrations.py         # Discord, Alexa
│   │   ├── scheduling.py           # EventBridge rules
│   │   └── monitoring.py           # CloudWatch
│   └── requirements.txt
│
├── lambdas/                        # Rust AWS Lambdas
│   ├── Cargo.toml                  # Workspace config
│   ├── shared/                     # Shared types & utilities
│   ├── api-gateway/src/bin/        # REST API handlers
│   │   ├── ingest.rs               # Fact ingestion
│   │   ├── query.rs                # Knowledge search
│   │   ├── entities.rs             # Entity CRUD
│   │   ├── relationships.rs        # Entity relationships
│   │   ├── tags.rs                 # Tagging system
│   │   ├── reminders.rs            # Reminder management
│   │   ├── locations.rs            # Geographic queries
│   │   ├── calendar.rs             # Calendar operations
│   │   ├── briefing.rs             # Morning briefings
│   │   └── families.rs             # Family management
│   ├── discord-webhook/            # Discord bot handler
│   ├── alexa-skill/                # Alexa skill handler
│   ├── event-triggers/             # EventBridge handlers
│   └── geocoder/                   # Location Service
│
├── agents/                         # Python Strands Agents
│   ├── agentcore_entry.py          # Lambda entry point
│   ├── pyproject.toml
│   └── src/
│       ├── router/                 # Intent classification
│       ├── ingestion/              # Fact storage
│       ├── query/                  # Knowledge retrieval
│       ├── calendar/               # Calendar sync
│       ├── briefing/               # Briefing generation
│       └── shared/
│           ├── tools/              # Agent tools
│           ├── database.py         # Connection management
│           └── models.py           # Pydantic models
│
├── migrations/                     # SQL migration scripts
│   ├── 001_extensions.sql          # pgvector, PostGIS, etc.
│   ├── 002_users_families.sql      # User hierarchy
│   ├── 003-015_*.sql               # Schema evolution
│
├── web/                            # Next.js web application
│   ├── src/
│   └── package.json
│
└── docs/                           # Documentation
    ├── requirements.md             # Detailed requirements
    └── implementation-plan.md      # Development roadmap
```

## Getting Started

### Prerequisites

- **Rust** 1.75+ with `cargo-lambda`
- **Python** 3.12+
- **Node.js** 18+ (for CDK and web app)
- **AWS CLI** configured with appropriate credentials
- **Docker** (for Python Lambda builds)

### AWS Account Setup

1. **Enable Bedrock models** in us-east-1:
   - Claude 3.5 Sonnet
   - Claude 3 Haiku
   - Titan Embeddings V2

2. **Create Cognito User Pool** (or let CDK create one)

3. **Configure Secrets Manager** with:
   - Discord bot token and application ID
   - Google OAuth client credentials (for calendar)

### Local Development Setup

```bash
# Clone the repository
git clone <repository-url>
cd second_brain

# Set up Python virtual environment for CDK
cd infra
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set up agents
cd ../agents
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Install Rust dependencies
cd ../lambdas
cargo build

# Install web dependencies
cd ../web
npm install
```

### Environment Variables

Create a `.env` file or configure in AWS:

```bash
# Database
DATABASE_HOST=<rds-endpoint>
DATABASE_NAME=second_brain
DATABASE_USER=<username>
DATABASE_PASSWORD=<from-secrets-manager>

# AWS
AWS_REGION=us-east-1
COGNITO_USER_POOL_ID=<pool-id>
COGNITO_CLIENT_ID=<client-id>

# Discord (optional)
DISCORD_APPLICATION_ID=<app-id>
DISCORD_BOT_TOKEN=<token>

# Google Calendar (optional)
GOOGLE_CLIENT_ID=<client-id>
GOOGLE_CLIENT_SECRET=<client-secret>
```

## Deployment

### Build Rust Lambdas

```bash
cd lambdas
cargo lambda build --release
```

### Deploy with CDK

```bash
cd infra
source .venv/bin/activate

# Synthesize CloudFormation
npx cdk synth

# Deploy all stacks
npx cdk deploy --all
```

### Run Database Migrations

```bash
aws lambda invoke \
  --function-name second-brain-db-migrator \
  --payload '{"action": "migrate"}' \
  response.json
```

## API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/ingest` | Store a new fact |
| POST | `/query` | Search knowledge base |
| GET | `/briefing` | Get morning briefing |
| GET/POST | `/entities` | Entity CRUD |
| GET/POST | `/relationships` | Entity relationships |
| GET/POST | `/tags` | Tag management |
| GET/POST | `/reminders` | Reminder management |
| GET | `/locations/nearby` | Proximity search |
| GET/POST | `/calendar/*` | Calendar operations |
| GET/POST | `/families` | Family management |

### Authentication

All endpoints require a valid JWT from Cognito in the `Authorization` header:

```bash
curl -X POST https://api.example.com/ingest \
  -H "Authorization: Bearer <jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"content": "Mom'\''s birthday is March 15th"}'
```

### Discord Commands

| Command | Description |
|---------|-------------|
| `/remember <fact>` | Store a fact |
| `/ask <question>` | Query knowledge base |
| `/briefing` | Get your morning briefing |

## Database Schema

### Core Tables

- **users** - User accounts linked to Cognito
- **families** - Family groups with shared access
- **facts** - Knowledge base entries with embeddings
- **entities** - People, places, organizations, projects
- **entity_relationships** - Graph connections between entities
- **tags** - Hierarchical taxonomy
- **fact_tags** - Many-to-many fact-tag associations
- **calendar_events** - Synced calendar data
- **reminders** - Time and location-based reminders

### PostgreSQL Extensions

| Extension | Purpose |
|-----------|---------|
| pgvector | 1024-dim vector embeddings for semantic search |
| PostGIS | Geographic data and spatial queries |
| btree_gist | Temporal range queries |
| pg_trgm | Fuzzy text matching |

## Testing

See [TESTING_PLAN.md](./TESTING_PLAN.md) for comprehensive test scenarios.

### Quick Test

```bash
# Get auth token
TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id <client-id> \
  --auth-parameters USERNAME=<user>,PASSWORD=<pass> \
  --query 'AuthenticationResult.IdToken' \
  --output text)

# Test ingestion
curl -X POST https://<api-endpoint>/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Test fact for the knowledge base"}'

# Test query
curl -X POST https://<api-endpoint>/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "What test facts do I have?"}'
```

## Cost Estimate

Optimized for family use (~4 users):

| Service | Monthly Cost |
|---------|--------------|
| RDS PostgreSQL (db.t4g.micro) | $14.00 |
| Bedrock (Claude Sonnet) | $5.50 |
| Transcribe (voice input) | $2.70 |
| Polly (voice output) | $2.20 |
| Bedrock (Haiku + Titan) | $0.50 |
| AWS Location Service | $1.00 |
| Lambda/API Gateway | ~$0 (free tier) |
| **Total** | **~$26/month** |

## Roadmap

- [x] **Phase 1**: Core knowledge operations
- [x] **Phase 2**: Tags, locations, reminders
- [x] **Phase 3**: Calendar integration, briefings
- [x] **Phase 4**: Discord bot
- [ ] **Phase 5**: Multi-user family features
- [ ] **Phase 6**: Alexa skill
- [ ] **Phase 7**: Smart Mirror integration
- [ ] **Phase 8**: Advanced analytics

## Documentation

- [Requirements](./docs/requirements.md) - Detailed system requirements
- [Implementation Plan](./docs/implementation-plan.md) - Development roadmap
- [Testing Plan](./TESTING_PLAN.md) - Test scenarios and status

## License

[Add license information]

## Contributing

[Add contribution guidelines]

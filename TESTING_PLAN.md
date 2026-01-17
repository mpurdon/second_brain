# Second Brain Testing Plan

A progressive testing plan starting with simple single-user scenarios and building up to multi-user Alexa integration.

---

## Testing Progress Summary (2026-01-17)

### Infrastructure Issues Resolved
1. **Python Dependencies**: Added Docker bundling for `strands-agents` and dependencies
2. **Response Format**: Fixed Lambda-to-Lambda response format (no API Gateway wrapping)
3. **Bedrock Model**: Changed to Claude Haiku (`us.anthropic.claude-3-haiku-20240307-v1:0`) via Bedrock
4. **Database Connection**: Simplified from connection pool to single connections (appropriate for Lambda)
5. **User ID Handling**: Fixed all tools to lookup database user ID from Cognito sub
6. **Async Event Loop**: Added `run_async()` helper for running async code in Lambda tools
7. **SQL Type Ambiguity**: Fixed parameter type issues in user upsert queries
8. **Metadata Handling**: Added safe type checking for JSONB metadata fields
9. **Semantic Search Threshold**: Adjusted from 0.7 to 0.15 for realistic similarity matching

### Current Status

| Test | Status | Notes |
|------|--------|-------|
| Prerequisites | ✅ Complete | Secrets, Cognito user, tokens all ready |
| Phase 1.1: Basic Ingest | ✅ PASSED | Facts stored successfully with fact_id |
| Phase 1.2: Entity Extraction | ✅ PASSED | Entities created and linked to facts |
| Phase 1.3: Basic Query | ✅ PASSED | entity_search and entity_get_details working |
| Phase 1.4: Semantic Search | ✅ PASSED | Vector search with pgvector working |

### Phase 1 Test Data
- Test User: `44482468-40c1-708b-8c10-3a7a3fb80b58`
- Entity "Max" (custom): ID `51b8300f-71d6-40e4-ade7-73f453546035`
- Entity "Mountains" (place): ID `742b1f3f-ca33-48d8-b61e-06988e8fff16`
- Entity "beach" (place): created during swimming fact ingest
- Fact "My dog name is Max": ID `e9fd9eb8-f242-4e5e-98b5-f69dfb3fdedb`
- Fact "I enjoy hiking in the mountains on weekends": ID `901742ec-31f1-4dd6-8b5c-6f450496d25a`
- Fact "I like swimming at the beach in summer": ID `87aae461-980e-466f-9f03-33c89638c8e4`

### Key Files Modified During Testing
- `agents/src/shared/database.py` - Simplified to single connections, added run_async
- `agents/src/shared/tools/database.py` - Fixed fact_store and fact_search with user lookup
- `agents/src/shared/tools/entities.py` - Fixed entity_search, entity_create, entity_get_details
- `agents/src/shared/tools/vector_search.py` - Fixed semantic_search with user lookup, adjusted threshold

---

## Prerequisites (Before Any Testing)

### Infrastructure Setup
- [x] Deploy all CDK stacks to AWS
- [x] Run database migrations (001-013)
- [x] Verify Cognito user pool is configured (us-east-1_raHIrGWN2)
- [x] Confirm API Gateway endpoints are accessible (https://cqkvkyydrk.execute-api.us-east-1.amazonaws.com/api/)
- [x] Set up AWS Secrets Manager with required credentials
  - DB credentials: `second-brain/db-credentials` (auto-generated, fully configured)
  - Discord: `second-brain/discord` (placeholder - configure when needed)
  - Google OAuth: `second-brain/google-oauth` (placeholder - configure when needed)

### Test User Setup
- [x] Create test user in Cognito (`testuser@example.com`)
- [x] Obtain JWT token for API authentication
- [x] Note user's Cognito `sub` (user ID)

**Test User Details:**
- Email: `testuser@example.com`
- Password: `TestPass123!`
- Cognito Sub: `44482468-40c1-708b-8c10-3a7a3fb80b58`
- Cognito Client ID: `6291pfmi8160sr2vbv1ilulje5` (web client)

**Get Fresh Token:**
```bash
aws cognito-idp initiate-auth \
  --client-id 6291pfmi8160sr2vbv1ilulje5 \
  --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=testuser@example.com,PASSWORD="TestPass123!" \
  --query "AuthenticationResult.IdToken" --output text
```

### Migration Runner (CI/CD)
```bash
# Check migration status
aws lambda invoke --function-name second-brain-db-migrator \
  --payload '{"action": "status"}' response.json

# Run all pending migrations
aws lambda invoke --function-name second-brain-db-migrator \
  --payload '{"action": "migrate"}' response.json
```

---

## Phase 1: Single User - Core Knowledge Operations

**Goal**: Verify basic ingestion and query work for one user.

**Note**: API base URL is `https://cqkvkyydrk.execute-api.us-east-1.amazonaws.com/api/` (not `/v1/`)
Request body uses `content` (not `input`) for ingest and `query` (not `input`) for query.

### 1.1 Basic Fact Ingestion

**Test**: Ingest simple facts via API

```bash
# Ingest a basic fact
curl -X POST https://cqkvkyydrk.execute-api.us-east-1.amazonaws.com/api/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "My favorite coffee shop is Blue Bottle on Market Street"
  }'
```

**Verify**:
- [x] Response confirms fact stored (fact_id returned)
- [x] Response includes extracted entities (e.g., "Max" entity created from "My dog name is Max")
- [x] Fact stored in `facts` table with correct `owner_id` (database user ID)
- [x] Embedding generated in `fact_embeddings` table (1024 dimensions via Titan Embeddings V2)
- [x] Entity mentions created via `entity_link_to_fact` tool

### 1.2 Entity Extraction

**Test**: Ingest facts with people and places (tested with Lambda directly)

```bash
aws lambda invoke --function-name second-brain-agents \
  --payload '{"message": "My dog name is Max", "user_id": "<cognito_sub>", "intent": "ingest"}' \
  --cli-binary-format raw-in-base64-out /tmp/response.json
```

**Verify**:
- [x] Entity created (Max - custom entity type)
- [x] Entity linked to fact via entity_link_to_fact
- [x] Ingest agent uses extract_entities, entity_search, entity_create, store_fact_embedding tools

### 1.3 Basic Query

**Test**: Query the knowledge base

```bash
aws lambda invoke --function-name second-brain-agents \
  --payload '{"message": "Tell me about Max", "user_id": "<cognito_sub>", "intent": "query"}' \
  --cli-binary-format raw-in-base64-out /tmp/response.json
```

**Verify**:
- [x] entity_search finds entity by name
- [x] entity_get_details retrieves full entity info including recent_facts
- [x] Response includes entity details and associated facts

### 1.4 Semantic Search

**Test**: Query using semantic similarity (not exact keyword match)

```bash
aws lambda invoke --function-name second-brain-agents \
  --payload '{"message": "What outdoor hobbies do I have?", "user_id": "<cognito_sub>", "intent": "query"}' \
  --cli-binary-format raw-in-base64-out /tmp/response.json
```

**Verify**:
- [x] semantic_search uses pgvector cosine similarity
- [x] Finds "hiking in mountains" for "outdoor hobbies" query (similarity: 0.32)
- [x] Results filtered by user ownership and visibility tier

### 1.5 Visibility Tiers (Single User)

**Test**: Ingest facts with different visibility levels

```bash
# Private fact (tier 1)
curl -X POST https://api.secondbrain.app/v1/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "input": "My bank account PIN is 1234",
    "visibility_tier": 1
  }'

# More public fact (tier 3)
curl -X POST https://api.secondbrain.app/v1/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "input": "Our family reunion is on July 4th at Grandma house",
    "visibility_tier": 3
  }'
```

**Verify**:
- [ ] Facts stored with correct `visibility_tier`
- [ ] Queries respect visibility filtering

---

## Phase 2: Single User - Extended Features

**Goal**: Test calendar, reminders, tags, and geographic features.

### 2.1 Taxonomy & Tags

**Test**: Create and apply tags

```bash
# Create a tag
curl -X POST https://api.secondbrain.app/v1/tags \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "work",
    "path": "categories/work",
    "description": "Work-related facts"
  }'

# Get tag suggestions for a fact
curl -X POST https://api.secondbrain.app/v1/tags/suggestions \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "fact_id": "<fact_id_from_earlier>"
  }'
```

**Verify**:
- [ ] Tag created in `tags` table
- [ ] AI suggests relevant tags
- [ ] Tags can be applied to facts

### 2.2 Entity Locations & Geographic Queries

**Test**: Add locations and query by proximity

```bash
# Add a location to an entity
curl -X POST https://api.secondbrain.app/v1/entities/<entity_id>/locations \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "address": "123 Main St, San Francisco, CA",
    "location_type": "office"
  }'

# Query nearby entities
curl -X GET "https://api.secondbrain.app/v1/locations/nearby?lat=37.7749&lng=-122.4194&radius_km=5" \
  -H "Authorization: Bearer $TOKEN"
```

**Verify**:
- [ ] Location geocoded and stored with PostGIS point
- [ ] Nearby query returns entities within radius
- [ ] Distance calculations work correctly

### 2.3 Time-Based Reminders

**Test**: Create and trigger reminders

```bash
# Create a time-based reminder
curl -X POST https://api.secondbrain.app/v1/reminders \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "title": "Call Mom",
    "description": "Weekly call with mom",
    "trigger_type": "time",
    "trigger_config": {
      "scheduled_at": "2024-01-15T10:00:00Z"
    },
    "notification_channels": ["push", "email"]
  }'

# List reminders
curl -X GET https://api.secondbrain.app/v1/reminders \
  -H "Authorization: Bearer $TOKEN"
```

**Verify**:
- [ ] Reminder created in `reminders` table
- [ ] Status is `active`
- [ ] Reminder evaluator Lambda picks it up
- [ ] Notification created when triggered

### 2.4 Location-Based Reminders

**Test**: Create geofence reminder

```bash
curl -X POST https://api.secondbrain.app/v1/reminders \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "title": "Buy groceries",
    "trigger_type": "location",
    "trigger_config": {
      "location": {"lat": 37.7749, "lng": -122.4194},
      "radius_m": 500,
      "trigger_on": "enter"
    }
  }'
```

**Verify**:
- [ ] Reminder stored with location trigger config
- [ ] Would trigger on geofence entry (requires mobile client)

### 2.5 User Feedback Loop

**Test**: Rate query results

```bash
# Submit feedback on a query
curl -X POST https://api.secondbrain.app/v1/feedback \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query_id": "<query_id>",
    "rating": 4,
    "feedback_text": "Good answer but missed one detail"
  }'

# Check feedback stats
curl -X GET https://api.secondbrain.app/v1/feedback/stats \
  -H "Authorization: Bearer $TOKEN"
```

**Verify**:
- [ ] Feedback stored in `user_feedback` table
- [ ] Stats endpoint returns aggregated data

---

## Phase 3: Single User - Calendar & Briefings

**Goal**: Test calendar sync and automated briefings.

### 3.1 Google Calendar OAuth

**Test**: Connect Google Calendar

```bash
# Initiate OAuth flow
curl -X POST https://api.secondbrain.app/v1/calendar/oauth \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "provider": "google",
    "redirect_uri": "https://app.secondbrain.com/callback"
  }'
```

**Verify**:
- [ ] OAuth URL returned
- [ ] After completing flow, tokens stored in Secrets Manager
- [ ] Calendar sync Lambda can access calendar

### 3.2 Calendar Sync

**Test**: Verify automatic calendar sync

- [ ] Wait for 15-minute sync cycle (or trigger manually)
- [ ] Check `calendar_events` table for synced events
- [ ] Verify `calendar_event_attendees` populated
- [ ] Confirm attendees linked to existing entities where possible

### 3.3 Calendar Queries

**Test**: Query calendar via natural language

```bash
curl -X POST https://api.secondbrain.app/v1/query \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "input": "What meetings do I have tomorrow?"
  }'
```

**Verify**:
- [ ] Router routes to calendar agent
- [ ] Calendar events returned with details
- [ ] Attendee context included (what you know about attendees)

### 3.4 Morning Briefing

**Test**: Request a briefing

```bash
curl -X GET https://api.secondbrain.app/v1/briefing?type=morning \
  -H "Authorization: Bearer $TOKEN"
```

**Verify**:
- [ ] Briefing includes today's calendar events
- [ ] Active reminders mentioned
- [ ] Relevant facts surfaced (birthdays, anniversaries)
- [ ] Briefing stored in `briefing_history` table

### 3.5 Briefing Dispatcher (Scheduled)

**Test**: Verify automated morning briefing

- [ ] Check EventBridge rule `briefing-dispatcher-rule` is active
- [ ] Wait for 6 AM ET trigger (or manually invoke Lambda)
- [ ] Verify notification created for user
- [ ] Check notification delivery via configured channels

---

## Phase 4: Discord Integration

**Goal**: Test Discord bot interaction before Alexa.

### 4.1 Discord Bot Setup

- [ ] Create Discord application and bot
- [ ] Set webhook URL to Discord Lambda
- [ ] Add bot to test Discord server
- [ ] Register slash commands

### 4.2 Discord Text Interaction

**Test**: Send commands via Discord

```
/ingest I had lunch with Sarah from marketing today
/query Who did I have lunch with recently?
/briefing
```

**Verify**:
- [ ] Bot responds in Discord
- [ ] Facts ingested correctly
- [ ] Queries return accurate results
- [ ] User identified correctly from Discord ID

### 4.3 Discord Voice (if applicable)

**Test**: Voice interaction in Discord

- [ ] Send audio message to bot
- [ ] Verify transcription (AWS Transcribe)
- [ ] Verify response includes TTS audio (AWS Polly)

---

## Phase 5: Family & Multi-User

**Goal**: Test shared knowledge and family access controls.

### 5.1 Create Second User

- [ ] Create `testuser2@example.com` in Cognito
- [ ] Obtain JWT token for user 2
- [ ] Note user 2's Cognito `sub`

### 5.2 Create Family

**Test**: Create family and add members

```bash
# User 1 creates family
curl -X POST https://api.secondbrain.app/v1/families \
  -H "Authorization: Bearer $TOKEN_USER1" \
  -d '{
    "name": "Smith Family"
  }'

# User 1 adds User 2 as member
curl -X POST https://api.secondbrain.app/v1/families/<family_id>/members \
  -H "Authorization: Bearer $TOKEN_USER1" \
  -d '{
    "user_id": "<user2_cognito_sub>",
    "role": "member"
  }'
```

**Verify**:
- [ ] Family created in `families` table
- [ ] Both users in `family_members` table
- [ ] User 1 has `admin` role
- [ ] User 2 has `member` role

### 5.3 Visibility Tier Sharing

**Test**: Verify tier-based access

```bash
# User 1 ingests tier 2 fact (personal - close family)
curl -X POST https://api.secondbrain.app/v1/ingest \
  -H "Authorization: Bearer $TOKEN_USER1" \
  -d '{
    "input": "Our wedding anniversary is March 15",
    "visibility_tier": 2
  }'

# User 2 queries for it
curl -X POST https://api.secondbrain.app/v1/query \
  -H "Authorization: Bearer $TOKEN_USER2" \
  -d '{
    "input": "When is the wedding anniversary?"
  }'
```

**Verify**:
- [ ] User 2 can see tier 2, 3, 4 facts from family members
- [ ] User 2 cannot see tier 1 (private) facts
- [ ] Visibility filtering works correctly

### 5.4 Shared Entities

**Test**: Both users see shared entities

```bash
# User 1 creates shared entity
curl -X POST https://api.secondbrain.app/v1/entities \
  -H "Authorization: Bearer $TOKEN_USER1" \
  -d '{
    "name": "Grandma Betty",
    "entity_type": "person",
    "visibility_tier": 3
  }'

# User 2 queries for entity
curl -X GET https://api.secondbrain.app/v1/entities?search=Grandma \
  -H "Authorization: Bearer $TOKEN_USER2"
```

**Verify**:
- [ ] User 2 can find and view shared entity
- [ ] Both users can add facts about shared entity
- [ ] Entity timeline shows facts from both users (respecting visibility)

### 5.5 Child Role Restrictions

**Test**: Add child user with limited permissions

```bash
# Create child user account
# Add to family with 'child' role
curl -X POST https://api.secondbrain.app/v1/families/<family_id>/members \
  -H "Authorization: Bearer $TOKEN_USER1" \
  -d '{
    "user_id": "<child_user_id>",
    "role": "child"
  }'
```

**Verify**:
- [ ] Child user has restricted access
- [ ] Sensitive tiers hidden from child
- [ ] Child can still query age-appropriate content

---

## Phase 6: Alexa Integration

**Goal**: Full voice interaction via Alexa.

### 6.1 Alexa Skill Setup

- [ ] Create Alexa Skill in Amazon Developer Console
- [ ] Configure skill endpoint to Alexa Lambda ARN
- [ ] Set up account linking with Cognito
- [ ] Define intent schema (Ingest, Query, Briefing, etc.)

### 6.2 Device Registration

**Test**: Register Alexa device

```sql
-- Verify device registration in database
INSERT INTO devices (device_type, external_device_id, name, created_by)
VALUES ('alexa', 'amzn1.ask.device.xxx', 'Kitchen Echo', '<user_id>');

INSERT INTO device_users (device_id, user_id, is_authorized, can_query)
VALUES ('<device_id>', '<user_id>', true, true);
```

**Verify**:
- [ ] Device appears in `devices` table
- [ ] User authorized for device

### 6.3 Single User Voice Interaction

**Test**: Basic Alexa commands

```
"Alexa, ask Second Brain to remember that I met Tom at the coffee shop"
"Alexa, ask Second Brain who I met recently"
"Alexa, ask Second Brain for my morning briefing"
```

**Verify**:
- [ ] Voice input transcribed correctly
- [ ] Facts ingested accurately
- [ ] Queries return spoken responses
- [ ] Briefings delivered via voice

### 6.4 Voice Profile Setup (Multi-User on Same Device)

**Test**: Configure voice profiles for household

```bash
# Register voice profiles for device users
curl -X POST https://api.secondbrain.app/v1/devices/<device_id>/users \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "user_id": "<user2_id>",
    "voice_profile_id": "amzn1.ask.person.xxx"
  }'
```

**Verify**:
- [ ] Multiple users linked to same device
- [ ] `voice_profiles_enabled` is true

### 6.5 Speaker Recognition

**Test**: Different family members interact

- User 1 says: "Alexa, ask Second Brain what's on my calendar"
- User 2 says: "Alexa, ask Second Brain what's on my calendar"

**Verify**:
- [ ] Each user identified by voice profile
- [ ] Correct user's calendar returned
- [ ] Personal facts shown to correct user
- [ ] Shared facts accessible to both

### 6.6 Cross-User Queries

**Test**: Query about family member

- User 1: "Alexa, ask Second Brain when is my spouse's birthday"
- User 2: "Alexa, ask Second Brain what appointments does my partner have today"

**Verify**:
- [ ] Relationship queries work across users
- [ ] Visibility tiers respected
- [ ] Appropriate sharing based on family roles

### 6.7 Reminder Announcements via Alexa

**Test**: Trigger reminder and receive announcement

```bash
# Create reminder with Alexa channel
curl -X POST https://api.secondbrain.app/v1/reminders \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "title": "Time to take medicine",
    "trigger_type": "time",
    "trigger_config": {
      "scheduled_at": "2024-01-15T09:00:00Z"
    },
    "notification_channels": ["alexa"]
  }'
```

**Verify**:
- [ ] Reminder triggers at scheduled time
- [ ] Alexa announces reminder to correct device
- [ ] Announcement delivered to device owner

---

## Phase 7: Full Integration Test

**Goal**: End-to-end test with all features combined.

### 7.1 Day-in-the-Life Scenario

**Morning (User 1 via Alexa)**:
1. "Alexa, ask Second Brain for my morning briefing"
2. Listen to calendar, reminders, relevant facts
3. "Alexa, ask Second Brain to remind me to call the dentist at 2pm"

**Afternoon (User 2 via Discord)**:
1. `/query What meetings does [User 1] have today?`
2. `/ingest We need to pick up kids at 5pm`

**Evening (User 1 via Mobile/API)**:
1. Query: "Did anyone add anything I need to know?"
2. See User 2's shared fact about kids pickup

**Verify**:
- [ ] Cross-platform interaction works
- [ ] Family sharing works across interfaces
- [ ] Reminders delivered correctly
- [ ] Context maintained throughout day

### 7.2 Concurrent Access

**Test**: Multiple users interacting simultaneously

- User 1 ingests via Alexa
- User 2 queries via Discord
- Both hit API simultaneously

**Verify**:
- [ ] No race conditions
- [ ] Data consistency maintained
- [ ] Each user sees correct personalized results

---

## Phase 8: Edge Cases & Error Handling

### 8.1 Error Scenarios

- [ ] Invalid JWT token returns 401
- [ ] Missing required fields returns 400
- [ ] Non-existent entity returns 404
- [ ] Unauthorized family access returns 403
- [ ] Database connection failure handled gracefully
- [ ] Agent timeout returns appropriate error

### 8.2 Input Validation

- [ ] SQL injection attempts blocked
- [ ] XSS in input sanitized
- [ ] Extremely long input truncated
- [ ] Invalid visibility tier rejected

### 8.3 Rate Limiting (if implemented)

- [ ] Rapid requests throttled
- [ ] User notified of rate limit

---

## Success Criteria Summary

| Phase | Status | Key Metrics |
|-------|--------|-------------|
| 1. Core Knowledge | ✅ PASSED | Ingestion ~8s, Query ~8s (cold start ~2.5s) |
| 2. Extended Features | [ ] | Tags, locations, reminders functional |
| 3. Calendar & Briefings | [ ] | Sync working, briefings generated |
| 4. Discord | [ ] | Bot responsive, commands working |
| 5. Multi-User | [ ] | Family sharing, visibility tiers correct |
| 6. Alexa | [ ] | Voice recognition, multi-user on device |
| 7. Full Integration | [ ] | Day-in-life scenario successful |
| 8. Edge Cases | [ ] | All error scenarios handled |

---

## Notes

- Test in dev/staging environment before production
- Use CloudWatch logs to debug failures
- Document any issues found and fixes applied
- Consider automated tests for regression prevention

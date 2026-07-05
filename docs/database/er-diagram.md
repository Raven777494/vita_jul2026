# Entity-Relationship Diagram

Version: 0.2 (P4-4)

Source of truth for columns and constraints: SQLAlchemy models in `app/services/db_manager.py`.

## Scope

| Layer | Storage | Managed by |
|-------|---------|------------|
| Relational ORM tables | PostgreSQL `public` | `db_manager.py` + Alembic revisions |
| Vector index (HNSW) | `gsw_eternal_echoes.embedding` | `init-db/02-gsw-hnsw-index.sql` + bootstrap |
| Apache AGE graph | `vita_memory_graph` (separate from `memory_graph` table) | `init-db/03-age-graph.sql` — **read-only reserve** (ADR-002) |
| pg_cron jobs | `cron.job` | `init-db/04-pg-cron-jobs.sql` |

The relational table `memory_graph` stores JSONB node documents per user (primary structured graph path when feature writes ship). Semantic recall uses `gsw_eternal_echoes` with pgvector HNSW. The AGE graph `vita_memory_graph` is provisioned as an empty read-only shell per [ADR-002](../architecture/adr-002-memory-model.md); it is not used by GSW or memory_chain runtime code.

## Core user and session cluster

```mermaid
erDiagram
    users {
        string id PK
        text alias
        datetime created_at
        datetime deleted_at
        float trust_score
        jsonb thought_fingerprint
        jsonb dark_triad_scores
        jsonb session_metadata
        float intimacy
        int total_turns
        int total_sessions
    }

    active_sessions {
        uuid session_id PK
        string user_id FK
        string conversation_id
        datetime created_at
        datetime last_updated_at
        int turn_count
        int risk_level
        float walker_score
        boolean is_active
        boolean is_escalated
        json messages
        jsonb session_metadata
    }

    turns {
        int turn_id PK
        uuid session_id FK
        string user_id FK
        int session_seq
        string role
        text text
        jsonb emotions_vsc
        float valence
        float arousal
        vector embedding
        jsonb emotion_vector
        int risk_level
        jsonb safety_audit
        float butterfly_impact
        jsonb metadata
        datetime created_at
        datetime updated_at
    }

    session_history {
        int id PK
        uuid session_id UK
        string user_id
        datetime created_at
        datetime ended_at
        string end_reason
        int peak_risk_level
        boolean is_escalated
        jsonb session_summary
    }

    risk_assessments {
        int id PK
        uuid session_id FK
        int turn_number
        int risk_level
        jsonb flags
        float confidence
        vector embedding
        jsonb emotion_vector
        datetime created_at
    }

    users ||--o{ active_sessions : "user_id CASCADE"
    users ||--o{ turns : "user_id CASCADE"
    active_sessions ||--o{ turns : "session_id CASCADE"
    active_sessions ||--o{ risk_assessments : "session_id CASCADE"
    users ||..o{ session_history : "user_id logical"
    active_sessions ||..o| session_history : "session_id logical"
```

`session_history` stores archived session summaries. It has no database FK to `users` or `active_sessions`; application code and retention jobs must keep `user_id` / `session_id` consistent.

## Safety, escalation, and clinical audit

```mermaid
erDiagram
    users {
        string id PK
    }

    crisis_events {
        int event_id PK
        string user_id FK
        datetime timestamp
        string trigger_type
        float arousal_score
        text user_input_snippet
        text hil_response
        boolean hotline_provided
        string hotline_name
        text additional_context
        boolean intervention_success
        datetime created_at
    }

    escalation_events {
        int id PK
        uuid session_id
        int risk_level
        string escalation_reason
        float walker_score
        string escalated_to
        string escalation_status
        datetime escalated_at
        boolean escalation_confirmed
        int turn_number
    }

    psych_assessments {
        uuid assessment_id PK
        string user_id FK
        int phase_stage
        jsonb joker_patterns
        jsonb shame_triggers
        jsonb dark_triad
        jsonb attachment_style
        float sexualization_index
        float trauma_bond_risk
        float genuine_help_intent
        jsonb butterfly_prediction
        jsonb manipulation_tactics
        float inner_void_index
        jsonb positive_glimmers
        float emotion_regulation_capacity
        jsonb defense_mechanisms_usage
        float detox_progress
        string user_category
        int reverse_joker_stage
        datetime last_update
    }

    users ||--o{ crisis_events : "user_id CASCADE"
    users ||--o{ psych_assessments : "user_id CASCADE"
    active_sessions ||..o{ escalation_events : "session_id logical"
```

`escalation_events.session_id` is not enforced by FK. Retention and user erasure must delete or anonymize these rows explicitly.

## Memory, GSW, and KAG

```mermaid
erDiagram
    users {
        string id PK
    }

    gsw_eternal_echoes {
        string id PK
        string user_id FK
        text user_input
        text response
        text content
        vector embedding
        float echo_score
        float weight
        jsonb metadata
        datetime created_at
        datetime updated_at
    }

    memory_graph {
        uuid node_id PK
        string user_id FK
        string node_type
        text content
        jsonb attributes
        jsonb connections
        string status
        datetime created_at
    }

    reality_facts {
        int fact_id PK
        string user_id FK
        string subject
        string predicate
        text object_value
        float confidence
        string source
        uuid session_id
        jsonb meta
        boolean is_seed
        datetime expires_at
        datetime created_at
        datetime updated_at
    }

    users ||--o{ gsw_eternal_echoes : "user_id CASCADE"
    users ||--o{ memory_graph : "user_id CASCADE"
    users ||--o{ reality_facts : "user_id CASCADE"
```

GSW echo retention: 30-day rolling delete via pg_cron job `clean-old-gsw-echoes` (see [retention-policy.md](retention-policy.md)).

## Companion state and navigation

```mermaid
erDiagram
    users {
        string id PK
    }

    user_fracture_points {
        int id PK
        string user_id FK
        string trigger_keyword
        jsonb context_tags
        float emotion_spike_score
        float comfort_efficiency
        datetime last_triggered
        float decay_rate
        int trigger_count
        boolean is_active
        datetime created_at
        datetime updated_at
    }

    user_safe_anchors {
        int id PK
        string user_id FK
        string anchor_type
        text content
        float effectiveness_score
        int usage_count
        datetime last_used
        string island_association
        datetime created_at
        datetime updated_at
    }

    user_navigation_history {
        int history_id PK
        string user_id FK
        datetime timestamp
        string fracture_detected
        text fast_think_decision
        text slow_think_decision
        text final_decision
        float user_satisfaction
    }

    intimacy_timeline {
        int record_id PK
        string user_id FK
        datetime timestamp
        float intimacy_score
        float intimacy_delta
        string change_reason
    }

    user_shadow_state {
        string user_id PK_FK
        float pain
        float trust
        float hope
        float loneliness
        jsonb emotion_snapshot
        uuid last_session_id
        int turn_count
        datetime updated_at
        datetime created_at
    }

    psychological_milestones {
        int milestone_id PK
        string user_id FK
        uuid session_id
        string milestone_type
        string title
        text description
        int severity
        jsonb meta
        datetime created_at
    }

    reminders {
        int reminder_id PK
        string user_id FK
        text reminder_text
        datetime target_datetime
        jsonb context
        boolean is_triggered
        datetime created_at
    }

    users ||--o| user_shadow_state : "user_id CASCADE"
    users ||--o{ user_fracture_points : "user_id CASCADE"
    users ||--o{ user_safe_anchors : "user_id CASCADE"
    users ||--o{ user_navigation_history : "user_id CASCADE"
    users ||--o{ intimacy_timeline : "user_id CASCADE"
    users ||--o{ psychological_milestones : "user_id CASCADE"
    users ||--o{ reminders : "user_id CASCADE"
```

## Reference and operations tables (no user FK)

```mermaid
erDiagram
    fracture_maps {
        int fracture_id PK
        string fracture_name UK
        text description
        int severity_level
        jsonb keywords
        jsonb risk_indicators
        jsonb intervention_prompts
        text clinical_guidelines
        datetime created_at
        datetime updated_at
    }

    action_cards {
        int card_id PK
        int stage
        string title
        text content
        jsonb target_emotions
        jsonb trigger_conditions
        datetime created_at
    }

    judgment_room_logs {
        int log_id PK
        string date
        int processed_users
        float duration_sec
        jsonb anomalies
        datetime created_at
    }

    system_errors {
        int id PK
        string error_type
        text error_message
        boolean resolved
        datetime occurred_at
    }
```

## Cascade summary (user deletion)

Deleting a row in `users` cascades (ON DELETE CASCADE) to all tables with FK `users.id` listed above. Additional explicit deletes required for:

| Table | Reason |
|-------|--------|
| `session_history` | No FK to `users` |
| `escalation_events` | No FK; match by `session_id` from user sessions |

Full erasure API design: [data-classification.md](data-classification.md#user-erasure-design-p4-1).

## Related documents

- [schema-overview.md](schema-overview.md)
- [migrations.md](migrations.md)
- [retention-policy.md](retention-policy.md)
- [data-classification.md](data-classification.md)

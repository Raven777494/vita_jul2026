# ADR-002: Memory Model — Relational Primary, AGE Read-Only Reserve

Status: Accepted (P4-4)  
Date: 2026-07-05  
Deciders: Engineering (VITA Platform / Logic Engine)  
Closes: TD-001

## Context

VITA historically provisioned two graph-like stores:

| Store | Technology | Purpose (as documented) |
|-------|------------|-------------------------|
| `gsw_eternal_echoes` | PostgreSQL + pgvector (HNSW) | Semantic turn recall (GSW / memory chain) |
| `memory_graph` | PostgreSQL relational (JSONB nodes) | Structured graph nodes per user (ORM ready) |
| `vita_memory_graph` | Apache AGE graph | Future graph-RAG (extension-backed) |

**Gap (TD-001):** Documentation implied GSW/memory pipelines might write to AGE, while runtime code only writes to `gsw_eternal_echoes`. The AGE graph was provisioned (`init-db/03-age-graph.sql`, `db_manager._ensure_age_graph`) but received **zero application writes**. The relational `memory_graph` table has an ORM model but **no runtime writes yet**. This dual-model ambiguity blocked governance sign-off and user-erasure design.

## Decision

### 1. Primary write path (authoritative)

All application memory **writes** use **relational PostgreSQL**:

| Data | Table | Access layer | Status |
|------|-------|--------------|--------|
| Semantic recall (embeddings) | `gsw_eternal_echoes` | `db_manager`, `memory_chain_service`, GSW background persist | **Active** |
| Structured graph nodes | `memory_graph` | `MemoryGraphNode` ORM | **Schema ready**; feature writes deferred |
| Session / turns | `turns`, `active_sessions`, etc. | `db_manager` | Active |

Vector search uses **pgvector HNSW** on `gsw_eternal_echoes.embedding` (not AGE).

### 2. Apache AGE `vita_memory_graph` — read-only reserve

- The **AGE extension** remains a Platform Engine requirement (`vector`, `age`, `pg_cron` in custom Postgres image).
- The empty graph `vita_memory_graph` may be **provisioned** at init (`init-db/03-age-graph.sql`, `db_manager._ensure_age_graph`) for future graph-RAG experiments.
- **No runtime cypher writes** in `app/` or `PersonalityModule/` until a future ADR explicitly re-opens AGE as a write path.
- Alignment checker enforces this (`app/governance/memory_model_alignment.py`).

### 3. Schema change policy

- Relational DDL: **Alembic** (`docs/database/migrations.md`).
- Platform objects (extensions, HNSW, AGE graph shell, pg_cron): **`init-db/*.sql`** + idempotent `db_manager` bootstrap only.

### 4. User erasure (design alignment)

Per `docs/database/data-classification.md#user-erasure-design-p4-1`:

- Relational tables: cascade via FK + explicit deletes on `memory_graph`, `gsw_eternal_echoes`.
- AGE vertices (if ever populated): delete via graph API in the erasure job — **not required today** because the graph is empty and read-only.

## Consequences

### Positive

- Single authoritative write model for audits and SLO/memory retention
- TD-001 closed; alignment checker can PASS without dual-model ambiguity
- Platform Engine checks unchanged (AGE extension + empty graph still verified)
- Zero-Truncation: no removal of working pgvector path

### Negative / follow-up

- `memory_graph` table writes still to be implemented when graph-node features ship
- AGE graph-RAG requires ADR-003 before any cypher write path
- `data-flow.md` and ER docs updated to stop claiming GSW uses AGE

## Verification

```powershell
# Static alignment (CI + local)
python -m pytest tests/governance/test_memory_model_alignment.py -q
python app/tests/system_alignment_checker.py

# Runtime row counts (optional, requires Postgres)
python scripts/db/memory_model_status.py
```

## References

- `docs/database/er-diagram.md`
- `docs/database/data-classification.md`
- `app/services/memory_chain_service.py`
- `app/governance/memory_model_alignment.py`
- `init-db/03-age-graph.sql`

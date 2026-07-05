# Data Flow (Chat Turn)

Version: 0.2 (P4-4)

## Request path

1. Client `POST /chat` -> `app/main.py`
2. Session load/create -> `session_manager` / `db_manager`
3. Orchestrator `process()` -> emotion, risk, memory retrieval
4. KAG reality layer (non-sensitive facts) -> `kag_reality_service`
5. GSW vector search (HNSW) -> `gsw_eternal_echoes`
6. LLM draft -> personality anchor -> safety validation
7. Response + metadata; turn persisted to DB
8. Logs: app (shipped), private events (not shipped) as applicable

## Persistence

| Data | Store | Index | Write path (ADR-002) |
|------|-------|-------|----------------------|
| Turns | PostgreSQL conversation tables | session_id | Active |
| Semantic recall | `gsw_eternal_echoes` | HNSW cosine (pgvector) | **Primary** — GSW / memory chain |
| Structured graph nodes | `memory_graph` table | user_id | Schema ready; writes deferred |
| AGE graph shell | `vita_memory_graph` | AGE extension | **Read-only reserve** — provisioned, no app writes |
| Session cache | Redis | TTL keys | Active |

## Observability flow

App loggers -> local files -> VictoriaLogs shipper (non-private) -> VictoriaLogs UI

## Migration strategy

- SQL bootstrap: `init-db/*.sql` on first Postgres volume init (extensions, HNSW, AGE graph shell, pg_cron)
- Runtime ensure: `db_manager` (_ensure_platform_extensions, HNSW, AGE graph shell, pg_cron)
- Relational DDL: Alembic (`docs/database/migrations.md`, ADR-002)

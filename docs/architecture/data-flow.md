# Data Flow (Chat Turn)

Version: 0.1 (P1)

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

| Data | Store | Index |
|------|-------|-------|
| Turns | PostgreSQL conversation tables | session_id |
| Embeddings | gsw_eternal_echoes | HNSW cosine |
| Graph memory (AGE) | vita_memory_graph | AGE (when Platform image used) |
| Relational graph | memory_graph table | SQL |
| Session cache | Redis | TTL keys |

## Observability flow

App loggers -> local files -> VictoriaLogs shipper (non-private) -> VictoriaLogs UI

## Migration strategy (P1)

- SQL bootstrap: `init-db/*.sql` on first Postgres volume init
- Runtime ensure: `db_manager` (_ensure_platform_extensions, HNSW, AGE graph, pg_cron)
- Future: Alembic migrations for schema changes (tracked in tech-debt register)

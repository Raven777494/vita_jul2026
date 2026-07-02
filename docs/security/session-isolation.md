# Session Isolation and Log Shipping

Version: 0.1 (P1)

## Session boundaries

- Conversations keyed by `user_id` and `session_id` / `conversation_id`
- DB queries must filter by session or user scope (orchestrator, db_manager)
- Redis cache keys must include user/session prefix where applicable

## Log tiers and shipping

| Logger / log_type | File | VictoriaLogs shipper |
|-------------------|------|----------------------|
| private | logs/private.log | **Never** |
| crisis | logs/crisis.log | Yes (operational, non-institutional content) |
| critical | logs/critical.log | Yes |
| app / audit / health | respective files | Yes |

Implementation: `app/logger.py` — `_VICTORIA_EXCLUDED_LOG_TYPES = frozenset({'private'})`

## API error responses

HTTP 5xx responses must not include phone numbers or emergency instructions (`app/main.py`).

## KAG reality layer

Seed facts must not inject hotlines into model context (`config/reality_seed.json` companion guidance only).

## Operator access

- T3 log access: restricted operators only; no export to unsecured channels
- VictoriaLogs queries for crisis metrics must not include raw private log fields

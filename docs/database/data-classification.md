# Data Classification

Version: 0.2 (P4-1)

| Tier | Label | Examples | Storage | VictoriaLogs |
|------|-------|----------|---------|--------------|
| T0 | Public | Product docs, public API metadata | Repo / public logs | Yes |
| T1 | Operational | Latency, error rates, health checks | app.log, health.log | Yes |
| T2 | Personal | Conversation summaries, emotion scores, embeddings | PostgreSQL, app logs | Yes with care; minimize content |
| T3 | Clinical sensitive | Suicidal content, crisis details, private sessions | private.log, crisis.log | **private: Never**; crisis: operational only |

## Handling rules

- T3 raw content: `get_private_logger` only
- User-facing outputs: never echo T3 verbatim to logs shipped externally without redaction policy
- KAG seeds: no hotline numbers (companion guidance only)

## Retention

See [retention-policy.md](retention-policy.md).

## User erasure design (P4-1)

Planned API: `DELETE /user/{id}` (implementation target P4/P5). Design-only at P4-1.

### Preconditions

- Authenticate caller (admin/service account or verified self-delete token).
- Reject if user id unknown; return 404.
- Optional soft-delete phase: set `users.deleted_at` before hard purge (not implemented yet).

### Hard delete transaction order

Execute in a single database transaction:

| Step | Target | Mechanism |
|------|--------|-----------|
| 1 | `escalation_events` | `DELETE WHERE session_id IN (...)` — collect session IDs from `active_sessions` and `session_history` for user |
| 2 | `session_history` | `DELETE WHERE user_id = :id` (no FK) |
| 3 | `users` | `DELETE WHERE id = :id` |

Step 3 cascades (ON DELETE CASCADE) to:

- `active_sessions`, `turns`, `risk_assessments`
- `psych_assessments`, `reminders`, `memory_graph`
- `user_fracture_points`, `user_safe_anchors`, `crisis_events`
- `gsw_eternal_echoes`, `user_navigation_history`, `intimacy_timeline`
- `user_shadow_state`, `psychological_milestones`, `reality_facts`

### Out of scope for DB cascade (manual / future)

| Asset | Action |
|-------|--------|
| Apache AGE graph nodes | No action required while graph is read-only empty (ADR-002); if populated in future, delete vertices/edges via graph API |
| VictoriaLogs | Separate retention / delete-by-user query (ops runbook) |
| Filesystem private logs | Redaction or log rotation policy; no automatic wipe in P4-1 |
| Redis session cache | Invalidate keys matching user/session prefix |

### Audit

- Log erasure request id, user id hash, row counts per table, timestamp to audit log (no T3 content).
- Retain minimal operational record that erasure completed (compliance window TBD).

### Related schema

See cascade summary in [er-diagram.md](er-diagram.md).

## Related

- [../security/session-isolation.md](../security/session-isolation.md)
- [../security/threat-model.md](../security/threat-model.md)
- [retention-policy.md](retention-policy.md)

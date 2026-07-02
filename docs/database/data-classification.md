# Data Classification

Version: 0.1 (P1)

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

## Related

- [../security/session-isolation.md](../security/session-isolation.md)
- [../security/threat-model.md](../security/threat-model.md)

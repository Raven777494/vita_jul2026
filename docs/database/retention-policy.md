# Retention Policy

Version: 0.2 (P4-1)

## Database

| Data | Retention | Mechanism |
|------|-----------|-----------|
| gsw_eternal_echoes | 30 days rolling | pg_cron job `clean-old-gsw-echoes` (`init-db/04-pg-cron-jobs.sql`) |
| Session turns, inactive sessions, session archives, escalation events | Config `SESSION_MAX_RETENTION_DAYS` (default 90) | `scripts/db/retention_batch.py` |
| crisis_events | Operational review window | Manual export policy TBD; not purged by retention batch |
| User profile / psych / memory nodes | Until user erasure | See [data-classification.md](data-classification.md#user-erasure-design-p4-1) |

### Retention batch (P4-1)

Script: `scripts/db/retention_batch.py`

Purges (by age cutoff = now minus `SESSION_MAX_RETENTION_DAYS`):

1. `active_sessions` where `is_active = false` and `last_updated_at` before cutoff (CASCADE `turns`, `risk_assessments`)
2. `turns` where `created_at` before cutoff (remaining old turns in active sessions)
3. `session_history` where `COALESCE(ended_at, created_at)` before cutoff
4. `escalation_events` where `escalated_at` before cutoff

```powershell
# Report eligible row counts (safe default)
python scripts/db/retention_batch.py --dry-run

# Delete eligible rows
python scripts/db/retention_batch.py --apply
```

Configure window via `SESSION_MAX_RETENTION_DAYS` in `.env.local` / compose env (default 90 in `app/config.py`).

### Scheduling

Recommended: daily pg_cron or external scheduler (GitHub Actions cron on staging, systemd timer, or K8s CronJob):

```sql
-- Example: daily 03:00 UTC (requires pg_cron; run --dry-run manually first)
SELECT cron.schedule(
    'vita-session-retention',
    '0 3 * * *',
    $$python /app/scripts/db/retention_batch.py --apply$$
);
```

On hosts without pg_cron invoking Python, use OS scheduler calling the same script against production DSN with secrets from GitHub Encrypted Secrets / vault — never inline credentials in the job definition.

## Logs (filesystem)

| Log | Rotation | Default |
|-----|----------|---------|
| app, audit, error, etc. | RotatingFileHandler 10MB x 30 | `app/logger.py` |

## VictoriaLogs

- Container volume `victorialogs_data` — size managed by VictoriaLogs storage settings
- Query retention: configure on VictoriaLogs server (ops)

## User deletion

Formal API and cascade rules: [data-classification.md](data-classification.md#user-erasure-design-p4-1).

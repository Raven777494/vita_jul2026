# Retention Policy

Version: 0.1 (P1)

## Database

| Data | Retention | Mechanism |
|------|-----------|-----------|
| gsw_eternal_echoes | 30 days rolling | pg_cron job `clean-old-gsw-echoes` (`init-db/04-pg-cron-jobs.sql`) |
| Session turns | Config `SESSION_MAX_RETENTION_DAYS` (default 90) | Application / future batch job |
| crisis_events | Operational review window | Manual export policy TBD |

## Logs (filesystem)

| Log | Rotation | Default |
|-----|----------|---------|
| app, audit, error, etc. | RotatingFileHandler 10MB x 30 | `app/logger.py` |

## VictoriaLogs

- Container volume `victorialogs_data` — size managed by VictoriaLogs storage settings
- Query retention: configure on VictoriaLogs server (ops)

## User deletion

P2: formal user data erasure API and cascade rules.

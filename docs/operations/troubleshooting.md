# Operations Troubleshooting Index

Version: 1.0 (P5-2)  
Audience: On-call engineers, operators

Symptom → command → expected output. Commands assume repo root and `.engine7b` venv active.

## Quick health sweep

| Step | Command | Expected |
|------|---------|----------|
| Platform Postgres | `python scripts/dev/verify_platform_postgres.py` | `[OK] Platform Engine verified` |
| P5 monitoring stack | `python scripts/observability/verify_p5_monitoring.py --skip-steady-state` | All `[OK]`, final `[OK] P5-1 monitoring verification passed` |
| System alignment | `python app/tests/system_alignment_checker.py` | `pass_rate: 100.0%` |
| Clinical policy | `python -m pytest tests/clinical/test_companion_language_policy.py -q` | `passed` |

## Database

| Symptom | Command | Expected |
|---------|---------|----------|
| Password authentication failed | `python scripts/dev/verify_platform_postgres.py` | Actionable hint (port 5433, compose creds) |
| Platform extensions missing | Same as above | Lists missing vector/age/pg_cron |
| Memory model drift | `python scripts/db/memory_model_status.py` | `Database reachable: yes`, ADR-002 counts |
| Wrong Postgres on 5432 (Windows) | Check `config/.env.local` `DB_PORT=5433` | Connects to Docker vita-postgres |

## Redis

| Symptom | Command | Expected |
|---------|---------|----------|
| Cache/session errors | `docker compose --env-file config/.env.compose ps redis` | `healthy` |
| Connection refused | `docker compose --env-file config/.env.compose up -d redis` | Container starts |

## LLM (Seele host)

| Symptom | Command | Expected |
|---------|---------|----------|
| All LLM FAIL at startup | `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8081/health` | `200` when Seele running |
| vita-api cannot reach LLM in Docker | Confirm `host.docker.internal:8081` in compose | `/health/engines` shows compute status |

Note: LLM offline is non-blocking for `/health`; chat will fail until Seele is up.

## Metrics and monitoring (P5-1)

| Symptom | Command | Expected |
|---------|---------|----------|
| Empty Grafana panels | `curl -s http://127.0.0.1:8428/api/v1/targets` | `vita-api` job `health: up` |
| Missing crisis metrics | `curl -s http://127.0.0.1:8080/metrics` | Contains `vita_crisis_interception_rate`, `# TYPE vita_crisis_signals_total` |
| Steady-state missed FAIL | `python scripts/observability/verify_p5_monitoring.py` | See [crisis-playbook.md](crisis-playbook.md) missed section |
| Grafana down | `curl -s http://127.0.0.1:3001/api/health` | `{"database":"ok",...}` |

VictoriaLogs UI: `http://127.0.0.1:9428/select/vmui`

Missed interceptions query:

```
_time:15m service:"vita-api" log_type:"crisis" event_type:"crisis_interception" outcome:"missed" source:"safety_hub"
| stats count() as missed
```

Expected in steady-state: `missed` = 0.

## Escalation webhook

| Symptom | Command | Expected |
|---------|---------|----------|
| L4–5 not notifying | `python scripts/observability/drill_escalation_webhook.py --dry-run` | `[OK] Log backend delivered` |
| Webhook drill | `python scripts/observability/drill_escalation_webhook.py` | `[OK] Escalation drill complete` when URL set |
| Solo HSS webhook | `python scripts/observability/drill_escalation_webhook.py --local-capture` | Proof JSONL `ok=true` |

## Clinical / companion language

| Symptom | Command | Expected |
|---------|---------|----------|
| Forbidden text in responses | `python -m pytest tests/clinical/ -q` | All pass |
| CI clinical gate | `python scripts/governance/check_traceability.py` | Exit 0 |
| S2 tabletop | Follow [tabletop-s2-language-regression.md](tabletop-s2-language-regression.md) | Completed in < 30 min |

## Personality / vocal layer (development)

For VocalPersonalityLayer-specific issues, see `app/tests/troubleshooting_guide.py` (in-repo diagnostic catalog for dev).

## Related

- [monitoring.md](monitoring.md)
- [incident.md](incident.md)
- [crisis-playbook.md](crisis-playbook.md)
- [on-call.md](on-call.md)

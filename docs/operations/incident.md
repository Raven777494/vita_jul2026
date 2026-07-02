# Incident Response

Version: 0.1 (P1)

## Severity levels

| Level | Example | Response time target |
|-------|---------|----------------------|
| S1 | Active data breach, widespread outage | Immediate |
| S2 | Crisis language policy bypass in production | Same day |
| S3 | Single service degraded (Redis, one LLM) | Next business day |
| S4 | CI failure, non-prod | Backlog |

## S1 / S2 playbook

1. **Identify** — VictoriaLogs, `/health/engines`, user report
2. **Contain** — disable affected endpoint or feature flag if available
3. **Preserve** — private/crisis logs; do not delete evidence
4. **Communicate** — internal stakeholders; no public detail on T3 content
5. **Remediate** — patch, redeploy, rotate secrets if needed ([../security/secrets-policy.md](../security/secrets-policy.md))
6. **Review** — post-incident note; update threat model or tests

## Crisis language regression (S2)

1. Run `pytest tests/clinical/`
2. grep app for forbidden patterns (2389, 熱線, For emergency)
3. Roll back deploy if production affected
4. Add regression test case

## Contacts

Configure in operator runbook (not in repo): on-call, clinical supervisor.

## Related

- [crisis-playbook.md](crisis-playbook.md)
- [monitoring.md](monitoring.md)

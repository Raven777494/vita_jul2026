# Key Rotation Runbook

Version: 0.1 (P4-2)

Audience: Platform operators, release managers, on-call engineers.

Scope: staging drill first, then production. Never commit secret values to the repository.

## Principles

1. Rotate on compromise immediately; otherwise on the cadence in [secrets-policy.md](secrets-policy.md).
2. Use GitHub Encrypted Secrets (production/staging) or `config/.env.compose` (local Docker) as the authoritative write location.
3. Application host development reads DB credentials from `config/.env.compose` (see P4-1 credential authority). Remove stale Machine-scope `DB_PASSWORD` on Windows if present.
4. Document every rotation in [../operations/incident.md](../operations/incident.md) or change ticket.

## Pre-rotation checklist

- [ ] Maintenance window communicated (production only)
- [ ] Staging environment available for drill
- [ ] Backup of current secret values stored in approved vault (not repo)
- [ ] Rollback plan documented (previous secret retained until verification passes)
- [ ] CI green on target branch

---

## 1. Database password (`POSTGRES_PASSWORD` / `DB_PASSWORD`)

### Staging drill

1. Generate a new password (32+ chars, no `{` `}` `$` that break compose interpolation).
2. Update staging secret:
   - GitHub: Settings -> Secrets and variables -> Actions -> update `DB_PASSWORD` / `POSTGRES_PASSWORD`
   - Or staging host: update `config/.env.compose` via [../../scripts/deploy/write_compose_env.py](../../scripts/deploy/write_compose_env.py)
3. On Postgres host (or container):

```sql
ALTER USER postgres WITH PASSWORD 'NEW_PASSWORD_FROM_VAULT';
```

4. Restart dependent services:

```powershell
docker compose --env-file config/.env.compose up -d postgres vita-api
```

5. Verify:

```powershell
python scripts/dev/verify_platform_postgres.py
python -m pytest tests/platform/test_compose_env.py -q
```

6. Sign drill checklist (operator initials, date, environment).

### Production

Same steps with production secrets and approved change window. Run `alembic current` after restart to confirm connectivity.

### Rollback

Restore previous password in vault and Postgres `ALTER USER`, restart services, re-verify.

---

## 2. JWT secret (`JWT_SECRET`)

Impact: all outstanding JWT tokens invalidated immediately.

### Staging drill

1. Generate new secret (minimum 32 characters; not prefixed `dev_`).
2. Update GitHub Encrypted Secret `JWT_SECRET` or staging `config/.env.compose` / host env.
3. Restart `vita-api` (no DB migration required).
4. Verify:
   - Existing token rejected (401)
   - New login/session obtains valid token
   - `config.validate()` passes in staging profile (`ENV=staging`)

### Production

Schedule during low traffic. Notify clients that re-authentication is required.

### Rollback

Restore previous `JWT_SECRET` from vault; restart API. Users who received tokens under the new secret must re-authenticate again.

---

## 3. API key (`API_KEY`)

Impact: programmatic clients using `Authorization` / API key header must update.

### Staging drill

1. Generate new `API_KEY` (32+ chars).
2. Update GitHub Secret or staging env; never commit literal value.
3. Restart `vita-api`.
4. Verify protected endpoint with old key -> 401/403; new key -> 200.
5. Update internal client configs (n8n, monitoring probes) in vault-backed config only.

### Production

Rotate during maintenance window; update all consumers before revoking old key (dual-key window optional — not implemented in codebase; use sequential cutover).

---

## 4. Encryption keys (`ENCRYPT_KEY`, `SECRET_KEY`)

Used by audit field encryption and session signing helpers.

1. Rotate in vault/env same as JWT procedure.
2. Restart API.
3. Verify audit log writes still succeed (`logs/audit.log` receives JSON events).
4. Note: previously encrypted audit fields cannot be decrypted with the new key (plan archival before rotation if forensic access required).

---

## 5. Escalation webhook (`ESCALATION_WEBHOOK_URL`)

Non-credential URL, but treat as sensitive infrastructure.

1. Configure new webhook endpoint in Slack/Teams/PagerDuty (non-production channel for staging).
2. Set env var (no URL in repo):

```powershell
# staging example — value from vault, not committed
$env:ESCALATION_WEBHOOK_URL = "https://hooks.example.com/..."
```

3. Trigger test notification:

```powershell
python -c "
import asyncio
from app.services.escalation_notifier import EscalationNotifier, LogEscalationBackend, WebhookEscalationBackend
from app.config import config
async def main():
    n = EscalationNotifier(enabled=True, webhook_url=config.ESCALATION_WEBHOOK_URL)
    print(await n.notify('drill-user', 'drill-session', 4, 0.5))
asyncio.run(main())
"
```

4. Confirm webhook receiver logged the event (hashed `user_id`, no raw user content).

---

## Staging rotation drill sign-off

| Item | Operator | Date | Pass |
|------|----------|------|------|
| DB password rotated and verified | | | |
| JWT_SECRET rotated; re-auth verified | | | |
| API_KEY rotated; client updated | | | |
| Escalation webhook test event received | | | |
| Incident/ticket reference | | | |

Store signed checklist in ops ticket system (not in git).

## Related

- [secrets-policy.md](secrets-policy.md)
- [prompt-injection-mitigations.md](prompt-injection-mitigations.md)
- [../operations/crisis-playbook.md](../operations/crisis-playbook.md)
- TD-004 / TD-005 closed at P4-2

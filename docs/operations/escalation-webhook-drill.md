# Escalation Webhook Live Drill (Go-Live 2.3)

Version: 1.0  
Date: 2026-07-19  
Aligns: [go-live-checklist.md](../governance/go-live-checklist.md) item **2.3**

## Purpose

Prove L4/L5 escalation notifier can **POST** a webhook payload end-to-end
(not dry-run log-only). Evidence is a proof JSONL line under `logs/`
(gitignored) plus optional external archive `WEBHOOK-DRILL-YYYY-MM-NNN`.

Companion safety note: this is internal ops delivery, **not** user-visible
clinical paging. Solo-operator HSS may use `--local-capture`.

## Modes

| Mode | Command | When |
|------|---------|------|
| Dry-run | `--dry-run` | Safe pre-check only; **does not** satisfy 2.3 |
| Live | (no flags) | Requires `ESCALATION_WEBHOOK_URL` (Slack/Teams/PagerDuty/etc.) |
| Local capture | `--local-capture` | Solo HSS: temporary local HTTP receiver + proof file |

## BUG fixed (2026-07-19)

Previous live path could print `[OK]` when `ESCALATION_WEBHOOK_URL` was empty
(only log backend ran). Live / local-capture now **require**
`WebhookEscalationBackend` success and exit non-zero otherwise.

## Prerequisites

```powershell
cd D:\vita   # or D:\Desktop\engine7b
python scripts/observability/drill_escalation_webhook.py --dry-run
```

Expected:

```
[OK] Escalation drill (dry-run) complete
```

## Path A — Solo HSS (recommended for single operator)

```powershell
cd D:\vita
python scripts/observability/drill_escalation_webhook.py --local-capture
```

Expected:

```
[INFO] Local capture listening: http://127.0.0.1:<port>/vita-escalation-drill
  [OK] LogEscalationBackend_0: True
  [OK] WebhookEscalationBackend_1: True
[OK] Local capture received payload: risk_level=4 action=DRILL_ESCALATION_P5_2:...
[OK] Proof written: D:\vita\logs\webhook-drill-proof.jsonl
[OK] Escalation drill complete (local-capture) drill_id=WEBHOOK-DRILL-...
```

Archive proof (creates `_ops_archive` if needed):

```powershell
.\scripts\ops\archive_ops_record.ps1 `
  -Source "logs\webhook-drill-proof.jsonl" `
  -Name "WEBHOOK-DRILL-2026-07-001.jsonl"
```

Do **not** use `D:\ops\...` unless that directory exists on your machine.

## Path B — External webhook URL

1. Create a non-production channel webhook (Slack Incoming Webhook / Teams / etc.).
2. Set env (never commit the URL):

```powershell
$env:ESCALATION_WEBHOOK_URL = "https://hooks.example.com/..."
$env:ESCALATION_NOTIFIER_ENABLED = "true"
python scripts/observability/drill_escalation_webhook.py
```

Or one-shot override:

```powershell
python scripts/observability/drill_escalation_webhook.py --webhook-url "https://hooks.example.com/..."
```

3. Confirm channel received JSON with `source=vita_escalation_notifier`, hashed `user_id_hash`, no chat body.
4. Proof JSONL is still written under `logs/webhook-drill-proof.jsonl`.

## Acceptance (checklist 2.3)

| Field | Value |
|-------|-------|
| Record ID | WEBHOOK-DRILL-YYYY-MM-NNN |
| Mode | `local-capture` or `live` |
| Exit | 0 |
| Proof | `logs/webhook-drill-proof.jsonl` last line `ok=true` |
| External archive | optional encrypted ops copy |

Mark [go-live-checklist.md](../governance/go-live-checklist.md) **2.3** complete when acceptance filed.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `[FAIL] ESCALATION_WEBHOOK_URL not set` | Live without URL | Set URL or use `--local-capture` |
| `[FAIL] Webhook backend delivery failed` | HTTP 4xx/5xx or network | Check URL, TLS, firewall |
| `No module named 'httpx'` on host Python | Host missing httpx | Fixed: notifier falls back to urllib; prefer `.engine7b` venv or Docker |
| `[FAIL] Local capture server received no POST` | httpx/path issue | Re-run; confirm no proxy intercepting localhost |
| Dry-run OK but live FAIL | Expected until URL configured | Path A or B above |

## Related

- [deploy-d-zone.md](deploy-d-zone.md) — D4-B
- [crisis-playbook.md](crisis-playbook.md) — L4–5 procedure
- [incident.md](incident.md) — drill acceptance
- `app/services/escalation_notifier.py`

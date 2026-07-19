# MON Steady-State 7-Day Record (Go-Live 2.4)

Version: 1.0  
Date: 2026-07-13  
Aligns: [go-live-checklist.md](../governance/go-live-checklist.md) item **2.4**

## Purpose

Prove **7 consecutive calendar days** with `missed=0` in VictoriaLogs steady-state
(15m rolling window, `source:safety_hub` production events only).

Single-operator / HSS mode: records stay in local JSONL + optional external archive.
No clinical on-call required.

## Prerequisites

Monitoring stack running on HSS:

```powershell
cd D:\vita
docker compose --env-file config\.env.compose ps
# vita-api, victorialogs, vmsingle, grafana healthy
```

Do **not** run fire-test missed injection on days you want a passing record.
Wait 15m after any drill inject before recording.

## Daily procedure (once per day)

```powershell
cd D:\vita
python scripts/observability/record_mon_steady_state.py
```

Optional custom record path (local `_ops_archive`, gitignored):

```powershell
python scripts/observability/record_mon_steady_state.py `
  --record-file "_ops_archive\MON-RECORD-2026-07.jsonl" `
  --environment "HSS D:\vita"
```

Or archive after the fact:

```powershell
.\scripts\ops\archive_ops_record.ps1 `
  -Source "logs\mon-steady-state-record.jsonl" `
  -Name "MON-RECORD-2026-07-001.jsonl"
```

JSON output:

```powershell
python scripts/observability/record_mon_steady_state.py --json
```

### Expected (passing day)

```
[INFO] MON steady-state daily record (go-live 2.4)
  [OK] record file: D:\vita\logs\mon-steady-state-record.jsonl
  [OK] today 2026-07-13: missed=0 (LogsQL window 15m)
  [INFO] 7-day gate: 1/7 days passed (recorded 1)
[INFO] gate not met — need 6 more passing day(s)
```

### If today fails

```
  [FAIL] today 2026-07-13: missed=1 in VictoriaLogs
```

Run investigation:

```powershell
python scripts/observability/investigate_missed_interceptions.py --window 15m
```

Re-run record after fix. Same calendar day re-run **overwrites** that day's entry.

## 7-day gate completion

After **7 passing calendar days**:

```
[OK] 7-day steady-state gate met
```

Summary fields (`--json`):

| Field | Meaning |
|-------|---------|
| `days_passed` | Passing days in trailing 7 |
| `days_recorded` | Days with entries in file |
| `gate_met` | `true` when 7/7 passed |

## External archive (checklist evidence)

Copy `logs/mon-steady-state-record.jsonl` (or `--record-file` path) to
`_ops_archive/MON-RECORD-YYYY-MM-NNN.jsonl` (gitignored). Do **not** use a
non-existent `D:\ops` path unless you create that directory yourself.

Template line (one per day):

```json
{
  "record_type": "MON-STEADY-STATE",
  "date": "2026-07-13",
  "timestamp_utc": "2026-07-13T09:00:00+00:00",
  "environment": "HSS D:\\vita",
  "ok": true,
  "verify_ok": true,
  "steady_state_detail": "missed=0 (LogsQL window 15m)",
  "verify_checks_passed": 14,
  "verify_checks_total": 14
}
```

Update checklist **2.4** to **完成** when `gate_met=true` and external archive filed.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Connection refused :8080 | vita-api down | `docker compose up -d vita-api` |
| missed=1 after fire drill | Drill in 15m window | Wait 15m or exclude drill days |
| pytest pollution | Local pytest shipped crisis logs | steady-state filters `source:safety_hub` |
| Record file missing | First run | Script creates `logs/` automatically |

## Related

- [monitoring.md](monitoring.md) — stack URLs and LogsQL
- [deploy-d-zone.md](deploy-d-zone.md) — D4 monitoring section
- [mon-steady-state-7d.md](mon-steady-state-7d.md) — 7-day gate procedure
- `scripts/observability/verify_p5_monitoring.py` — underlying checks

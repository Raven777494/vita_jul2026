#!/usr/bin/env python3
"""Drill escalation webhook delivery (P5-2).

Sends a synthetic L4 escalation event through EscalationNotifier backends.
Use for on-call verification that ESCALATION_WEBHOOK_URL reaches the ops channel.

Usage:
    python scripts/observability/drill_escalation_webhook.py --dry-run
    python scripts/observability/drill_escalation_webhook.py
    python scripts/observability/drill_escalation_webhook.py --risk-level 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


async def _run_drill(*, risk_level: int, dry_run: bool) -> int:
    project_root = _project_root()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from app.services.escalation_notifier import (
        EscalationNotifier,
        LogEscalationBackend,
    )

    if dry_run:
        notifier = EscalationNotifier(backends=[LogEscalationBackend()])
        print("[INFO] Dry-run: log backend only (no webhook POST)")
    else:
        from app.config import config

        notifier = EscalationNotifier(
            enabled=config.ESCALATION_NOTIFIER_ENABLED,
            webhook_url=config.ESCALATION_WEBHOOK_URL,
        )
        if not config.ESCALATION_WEBHOOK_URL:
            print(
                "[WARN] ESCALATION_WEBHOOK_URL not set; only log backend will fire",
                file=sys.stderr,
            )

    results = await notifier.notify(
        user_id="drill-user-p5-2",
        session_id="drill-session-p5-2",
        risk_level=risk_level,
        walker_score=0.85,
        action="DRILL_ESCALATION_P5_2",
    )

    print("[INFO] Backend results:")
    all_ok = True
    for backend, ok in results.items():
        tag = "OK" if ok else "FAIL"
        print(f"  [{tag}] {backend}: {ok}")
        if not ok:
            all_ok = False

    if dry_run:
        if results.get("LogEscalationBackend_0"):
            print("[OK] Escalation drill (dry-run) complete")
            return 0
        print("[FAIL] Log backend did not deliver", file=sys.stderr)
        return 1

    webhook_keys = [k for k in results if k.startswith("WebhookEscalationBackend")]
    if webhook_keys and not any(results[k] for k in webhook_keys):
        print(
            "[FAIL] Webhook backend configured but delivery failed",
            file=sys.stderr,
        )
        return 1

    if all_ok:
        print("[OK] Escalation drill complete")
        return 0
    print("[FAIL] Escalation drill had backend failures", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drill escalation webhook (P5-2)")
    parser.add_argument("--dry-run", action="store_true", help="Log backend only")
    parser.add_argument("--risk-level", type=int, default=4, choices=(4, 5))
    args = parser.parse_args(argv)
    return asyncio.run(_run_drill(risk_level=args.risk_level, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())

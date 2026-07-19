#!/usr/bin/env python3
"""Drill escalation webhook delivery (P5-2 / go-live 2.3).

Sends a synthetic L4/L5 escalation event through EscalationNotifier backends.
Use for on-call verification that ESCALATION_WEBHOOK_URL receives the ops payload.

Usage:
    python scripts/observability/drill_escalation_webhook.py --dry-run
    python scripts/observability/drill_escalation_webhook.py
    python scripts/observability/drill_escalation_webhook.py --local-capture
    python scripts/observability/drill_escalation_webhook.py --risk-level 5

Modes:
  --dry-run         Log backend only (no HTTP POST). Safe pre-check.
  (default live)    Requires ESCALATION_WEBHOOK_URL; fails if missing/disabled.
  --local-capture   Solo-operator path: temporary local HTTP receiver + proof JSONL.

Exit codes:
    0 — drill accepted for the selected mode
    1 — delivery or contract failure
    2 — configuration / usage error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_sys_path() -> Path:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _default_proof_path() -> Path:
    return _project_root() / "logs" / "webhook-drill-proof.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class _CaptureState:
    def __init__(self) -> None:
        self.bodies: list[bytes] = []
        self.lock = threading.Lock()

    def append(self, body: bytes) -> None:
        with self.lock:
            self.bodies.append(body)

    def snapshot(self) -> list[bytes]:
        with self.lock:
            return list(self.bodies)


def _make_capture_handler(state: _CaptureState):
    class CaptureHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            state.append(body)
            payload = b'{"ok":true,"source":"vita_webhook_drill_capture"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return CaptureHandler


def start_local_capture_server(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[ThreadingHTTPServer, _CaptureState, str]:
    """Start a temporary POST capture server; port 0 binds an ephemeral port."""
    state = _CaptureState()
    server = ThreadingHTTPServer((host, port), _make_capture_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bound_port = int(server.server_address[1])
    url = f"http://{host}:{bound_port}/vita-escalation-drill"
    return server, state, url


def stop_local_capture_server(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def append_proof_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _print_results(results: dict[str, bool]) -> None:
    print("[INFO] Backend results:")
    for backend, ok in results.items():
        tag = "OK" if ok else "FAIL"
        print(f"  [{tag}] {backend}: {ok}")


async def _run_drill(
    *,
    risk_level: int,
    dry_run: bool,
    local_capture: bool,
    proof_file: Path | None,
    webhook_url_override: str | None = None,
) -> int:
    if dry_run and local_capture:
        print("[FAIL] Use either --dry-run or --local-capture, not both", file=sys.stderr)
        return 2

    _ensure_sys_path()
    from app.services.escalation_notifier import (
        EscalationNotifier,
        LogEscalationBackend,
    )

    drill_id = f"WEBHOOK-DRILL-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:8]}"
    action = f"DRILL_ESCALATION_P5_2:{drill_id}"
    capture_server: ThreadingHTTPServer | None = None
    capture_state: _CaptureState | None = None
    capture_url: str | None = None
    mode = "dry-run" if dry_run else ("local-capture" if local_capture else "live")

    try:
        if dry_run:
            notifier = EscalationNotifier(backends=[LogEscalationBackend()])
            print("[INFO] Dry-run: log backend only (no webhook POST)")
        elif local_capture:
            capture_server, capture_state, capture_url = start_local_capture_server()
            print(f"[INFO] Local capture listening: {capture_url}")
            notifier = EscalationNotifier(
                enabled=True,
                webhook_url=capture_url,
            )
        else:
            from app.config import config

            if webhook_url_override is not None:
                webhook_url = webhook_url_override.strip()
            else:
                webhook_url = (config.ESCALATION_WEBHOOK_URL or "").strip()
            if not config.ESCALATION_NOTIFIER_ENABLED and webhook_url_override is None:
                print(
                    "[FAIL] ESCALATION_NOTIFIER_ENABLED=false; live drill cannot pass",
                    file=sys.stderr,
                )
                return 2
            if not webhook_url:
                print(
                    "[FAIL] ESCALATION_WEBHOOK_URL not set. "
                    "Configure a real webhook URL, or use --local-capture for solo HSS.",
                    file=sys.stderr,
                )
                return 2
            notifier = EscalationNotifier(
                enabled=True,
                webhook_url=webhook_url,
            )
            print("[INFO] Live drill: webhook POST required")

        results = await notifier.notify(
            user_id="drill-user-p5-2",
            session_id=f"drill-session-{drill_id}",
            risk_level=risk_level,
            walker_score=0.85,
            action=action,
        )
        _print_results(results)

        if "disabled" in results:
            print("[FAIL] Notifier returned disabled=true", file=sys.stderr)
            return 1

        if dry_run:
            if results.get("LogEscalationBackend_0"):
                print("[OK] Escalation drill (dry-run) complete")
                return 0
            print("[FAIL] Log backend did not deliver", file=sys.stderr)
            return 1

        webhook_keys = [k for k in results if k.startswith("WebhookEscalationBackend")]
        if not webhook_keys:
            print(
                "[FAIL] Live/local-capture mode requires WebhookEscalationBackend",
                file=sys.stderr,
            )
            return 1
        if not any(results[k] for k in webhook_keys):
            print("[FAIL] Webhook backend delivery failed", file=sys.stderr)
            return 1

        captured_payload: dict[str, Any] | None = None
        if local_capture:
            assert capture_state is not None
            # Allow a short settle window for the HTTP handler thread.
            for _ in range(20):
                bodies = capture_state.snapshot()
                if bodies:
                    break
                await asyncio.sleep(0.05)
            bodies = capture_state.snapshot()
            if not bodies:
                print("[FAIL] Local capture server received no POST body", file=sys.stderr)
                return 1
            try:
                captured_payload = json.loads(bodies[-1].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                print(f"[FAIL] Captured body is not valid JSON: {exc}", file=sys.stderr)
                return 1
            if captured_payload.get("source") != "vita_escalation_notifier":
                print(
                    "[FAIL] Captured payload missing source=vita_escalation_notifier",
                    file=sys.stderr,
                )
                return 1
            if captured_payload.get("action") != action:
                print("[FAIL] Captured action does not match drill action", file=sys.stderr)
                return 1
            print(
                "[OK] Local capture received payload: "
                f"risk_level={captured_payload.get('risk_level')} "
                f"action={captured_payload.get('action')}"
            )

        if not all(results.values()):
            print("[FAIL] Escalation drill had backend failures", file=sys.stderr)
            return 1

        proof_path = proof_file or _default_proof_path()
        record = {
            "record_type": "WEBHOOK-DRILL",
            "drill_id": drill_id,
            "mode": mode,
            "timestamp_utc": _utc_now(),
            "risk_level": risk_level,
            "action": action,
            "ok": True,
            "backends": results,
            "capture_url": capture_url,
            "captured_payload": captured_payload,
        }
        append_proof_record(proof_path, record)
        print(f"[OK] Proof written: {proof_path}")
        print(f"[OK] Escalation drill complete ({mode}) drill_id={drill_id}")
        return 0
    finally:
        if capture_server is not None:
            stop_local_capture_server(capture_server)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drill escalation webhook (P5-2 / go-live 2.3)")
    parser.add_argument("--dry-run", action="store_true", help="Log backend only")
    parser.add_argument(
        "--local-capture",
        action="store_true",
        help="Solo-operator live path: temporary local HTTP capture + proof JSONL",
    )
    parser.add_argument("--risk-level", type=int, default=4, choices=(4, 5))
    parser.add_argument(
        "--proof-file",
        type=Path,
        default=None,
        help="JSONL proof path (default: logs/webhook-drill-proof.jsonl)",
    )
    parser.add_argument(
        "--webhook-url",
        default=None,
        help="Override ESCALATION_WEBHOOK_URL for this live run only",
    )
    args = parser.parse_args(argv)
    return asyncio.run(
        _run_drill(
            risk_level=args.risk_level,
            dry_run=args.dry_run,
            local_capture=args.local_capture,
            proof_file=args.proof_file,
            webhook_url_override=args.webhook_url,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

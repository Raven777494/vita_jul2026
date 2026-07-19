"""Tests for P5-2 / go-live 2.3 escalation webhook drill script."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts.observability.drill_escalation_webhook import (
    _run_drill,
    append_proof_record,
    start_local_capture_server,
    stop_local_capture_server,
)


def test_drill_escalation_dry_run_delivers_log_backend():
    code = asyncio.run(
        _run_drill(
            risk_level=4,
            dry_run=True,
            local_capture=False,
            proof_file=None,
        )
    )
    assert code == 0


def test_live_without_webhook_url_fails(tmp_path: Path):
    code = asyncio.run(
        _run_drill(
            risk_level=4,
            dry_run=False,
            local_capture=False,
            proof_file=tmp_path / "proof.jsonl",
            webhook_url_override="",
        )
    )
    assert code == 2
    assert not (tmp_path / "proof.jsonl").exists()


def test_local_capture_receives_webhook_and_writes_proof(tmp_path: Path):
    proof = tmp_path / "webhook-drill-proof.jsonl"
    code = asyncio.run(
        _run_drill(
            risk_level=4,
            dry_run=False,
            local_capture=True,
            proof_file=proof,
        )
    )
    assert code == 0
    assert proof.is_file()
    records = [
        json.loads(line)
        for line in proof.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["ok"] is True
    assert records[0]["mode"] == "local-capture"
    assert records[0]["captured_payload"]["source"] == "vita_escalation_notifier"
    assert records[0]["captured_payload"]["risk_level"] == 4


def test_append_proof_record_writes_jsonl(tmp_path: Path):
    path = tmp_path / "proof.jsonl"
    append_proof_record(path, {"record_type": "WEBHOOK-DRILL", "ok": True})
    line = path.read_text(encoding="utf-8").strip()
    assert json.loads(line)["ok"] is True


def test_local_capture_server_roundtrip():
    server, state, url = start_local_capture_server()
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=b'{"source":"test"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
        bodies = state.snapshot()
        assert len(bodies) == 1
        assert b"test" in bodies[0]
    finally:
        stop_local_capture_server(server)


def test_dry_run_and_local_capture_mutually_exclusive():
    code = asyncio.run(
        _run_drill(
            risk_level=4,
            dry_run=True,
            local_capture=True,
            proof_file=None,
        )
    )
    assert code == 2

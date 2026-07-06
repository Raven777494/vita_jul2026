"""Unit tests for P5-1 monitoring verification helpers."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.observability.render_grafana_alert_contact import (
    render_contactpoints_yaml,
    resolve_clinical_webhook_url,
)
from scripts.observability.verify_p5_monitoring import (
    check_metrics_endpoint,
    check_provisioning_files,
    check_victorialogs_missed_steady_state,
    check_vm_scrape_target,
    run_verification,
)


def test_check_metrics_endpoint_ok(monkeypatch):
    body = (
        "# HELP vita_crisis_interception_rate\n"
        "vita_crisis_interception_rate 1.0\n"
        "# TYPE vita_crisis_signals_total counter\n"
        "vita_crisis_signals_total{risk_band=\"moderate\"} 0\n"
        "vita_crisis_intercepted_total 0\n"
        "vita_crisis_missed_total 0\n"
    )

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body.encode()

    import scripts.observability.verify_p5_monitoring as mod

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    result = check_metrics_endpoint("http://test/metrics")
    assert result.ok


def test_check_vm_scrape_target_parses_vita_api(monkeypatch):
    payload = {
        "data": {
            "activeTargets": [
                {
                    "labels": {"job": "vita-api"},
                    "health": "up",
                }
            ]
        }
    }
    body = json.dumps(payload)

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body.encode()

    import scripts.observability.verify_p5_monitoring as mod

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    result = check_vm_scrape_target("http://vm")
    assert result.ok
    assert "up" in result.detail.lower()


def test_provisioning_files_present():
    root = Path(__file__).resolve().parents[2]
    results = check_provisioning_files(root)
    assert all(r.ok for r in results), [r for r in results if not r.ok]


def test_run_verification_skip_remote(tmp_path: Path):
    report = run_verification(
        skip_steady_state=True,
        skip_grafana=True,
        skip_vm=True,
        project_root=tmp_path,
    )
    assert not report.ok


def test_render_contactpoints_yaml_escapes_url():
    text = render_contactpoints_yaml("https://hooks.example.com/clinical")
    assert "https://hooks.example.com/clinical" in text
    assert "vita-clinical-webhook" in text


def test_resolve_clinical_webhook_prefers_grafana_var(monkeypatch):
    monkeypatch.setenv("GRAFANA_CLINICAL_ALERT_WEBHOOK_URL", "https://a")
    monkeypatch.setenv("ESCALATION_WEBHOOK_URL", "https://b")
    url, source = resolve_clinical_webhook_url()
    assert url == "https://a"
    assert "GRAFANA" in source


def test_steady_state_query_requires_safety_hub_source(monkeypatch):
    captured: dict[str, str] = {}

    def fake_post(url, body, timeout=12.0):
        captured["body"] = body
        return 200, '{"missed":"0"}'

    import scripts.observability.verify_p5_monitoring as mod

    monkeypatch.setattr(mod, "_http_post", fake_post)
    result = check_victorialogs_missed_steady_state("http://vl", window="15m")
    assert result.ok
    assert "source" in captured["body"]
    assert "safety_hub" in captured["body"]

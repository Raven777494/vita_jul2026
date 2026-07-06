#!/usr/bin/env python3
"""Verify P5-1 monitoring stack: VM scrape, Grafana, clinical alerts, steady-state.

Checks (host defaults assume docker-compose published ports):
  1. vita-api /metrics exposes vita_crisis_* series
  2. VictoriaMetrics scrape target vita-api is UP
  3. VM PromQL returns crisis metrics
  4. Grafana health + provisioning paths exist
  5. VictoriaLogs steady-state: no missed crisis interceptions in window
  6. Alert rule + contact point files present

Usage:
    python scripts/observability/verify_p5_monitoring.py
    python scripts/observability/verify_p5_monitoring.py --json
    python scripts/observability/verify_p5_monitoring.py --skip-steady-state

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class VerifyReport:
    ok: bool = True
    checks: List[CheckResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(CheckResult(name=name, ok=ok, detail=detail))
        if not ok:
            self.ok = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks
            ],
        }


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _http_get(url: str, timeout: float = 8.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def _http_post(url: str, body: str, timeout: float = 12.0) -> tuple[int, str]:
    data = body.encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def check_metrics_endpoint(api_metrics_url: str) -> CheckResult:
    try:
        status, body = _http_get(api_metrics_url)
    except Exception as exc:
        return CheckResult("vita-api /metrics", False, str(exc))
    if status != 200:
        return CheckResult("vita-api /metrics", False, f"HTTP {status}")
    required = (
        "vita_crisis_interception_rate",
        "# TYPE vita_crisis_signals_total counter",
        "vita_crisis_intercepted_total",
        "vita_crisis_missed_total",
    )
    missing = [m for m in required if m not in body]
    if missing:
        return CheckResult(
            "vita-api /metrics",
            False,
            f"missing series: {', '.join(missing)}",
        )
    return CheckResult("vita-api /metrics", True, "crisis metrics present")


def check_vm_scrape_target(vm_base: str) -> CheckResult:
    url = f"{vm_base.rstrip('/')}/api/v1/targets"
    try:
        status, body = _http_get(url)
    except Exception as exc:
        return CheckResult("VM scrape targets", False, str(exc))
    if status != 200:
        return CheckResult("VM scrape targets", False, f"HTTP {status}")
    payload = json.loads(body)
    active = payload.get("data", {}).get("activeTargets", [])
    vita_targets = [
        t for t in active if t.get("labels", {}).get("job") == "vita-api"
    ]
    if not vita_targets:
        return CheckResult("VM scrape targets", False, "no vita-api job in activeTargets")
    up = [t for t in vita_targets if t.get("health") == "up"]
    if not up:
        states = {t.get("health") for t in vita_targets}
        return CheckResult(
            "VM scrape targets",
            False,
            f"vita-api target not up (states: {states})",
        )
    return CheckResult("VM scrape targets", True, f"{len(up)} vita-api target(s) up")


def check_vm_promql(vm_base: str, query: str, name: str) -> CheckResult:
    params = urllib.parse.urlencode({"query": query})
    url = f"{vm_base.rstrip('/')}/api/v1/query?{params}"
    last_error = "empty result (no scraped samples yet)"
    for attempt in range(3):
        try:
            status, body = _http_get(url)
        except Exception as exc:
            return CheckResult(name, False, str(exc))
        if status != 200:
            return CheckResult(name, False, f"HTTP {status}")
        payload = json.loads(body)
        if payload.get("status") != "success":
            return CheckResult(name, False, payload.get("error", "query failed"))
        result = payload.get("data", {}).get("result", [])
        if result:
            return CheckResult(name, True, f"{len(result)} series")
        last_error = "empty result (waiting for scrape)"
        if attempt < 2:
            import time

            time.sleep(10)
    return CheckResult(name, False, last_error)


def check_grafana_health(grafana_base: str) -> CheckResult:
    url = f"{grafana_base.rstrip('/')}/api/health"
    try:
        status, body = _http_get(url)
    except Exception as exc:
        return CheckResult("Grafana health", False, str(exc))
    if status != 200:
        return CheckResult("Grafana health", False, f"HTTP {status}")
    try:
        payload = json.loads(body)
        if payload.get("database") != "ok":
            return CheckResult("Grafana health", False, body[:120])
    except json.JSONDecodeError:
        pass
    return CheckResult("Grafana health", True, "database ok")


def check_provisioning_files(project_root: Path) -> List[CheckResult]:
    required = [
        project_root / "grafana/provisioning/datasources/vita.yml",
        project_root / "grafana/provisioning/datasources/victoria-logs.yml",
        project_root / "grafana/provisioning/dashboards/json/vita_crisis_overview.json",
        project_root / "grafana/provisioning/dashboards/json/vita_slo_overview.json",
        project_root / "grafana/provisioning/alerting/crisis_interception_rate.yaml",
        project_root / "grafana/provisioning/alerting/contactpoints.yaml",
        project_root / "grafana/provisioning/alerting/policies.yaml",
        project_root / "config/observability/victoriametrics-scrape.yml",
        project_root / "config/observability/crisis_interception_missed.logsql",
    ]
    results: List[CheckResult] = []
    for path in required:
        ok = path.is_file()
        results.append(
            CheckResult(
                f"provisioning file {path.name}",
                ok,
                str(path.relative_to(project_root)) if ok else "missing",
            )
        )
    return results


def check_victorialogs_missed_steady_state(
    vl_base: str,
    window: str = "15m",
) -> CheckResult:
    """Steady-state: no missed crisis interceptions in the rolling window."""
    query = (
        f'_time:{window} service:"vita-api" log_type:"crisis" '
        'event_type:"crisis_interception" outcome:"missed" source:"safety_hub" '
        "| stats count() as missed"
    )
    url = f"{vl_base.rstrip('/')}/select/logsql/query"
    try:
        status, body = _http_post(url, f"query={urllib.parse.quote(query)}")
    except Exception as exc:
        return CheckResult("steady-state missed interceptions", False, str(exc))
    if status != 200:
        return CheckResult(
            "steady-state missed interceptions",
            False,
            f"HTTP {status}: {body[:200]}",
        )
    missed = 0
    for line in body.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            missed = int(row.get("missed", row.get("count", 0)))
            break
        except json.JSONDecodeError:
            continue
    if missed > 0:
        return CheckResult(
            "steady-state missed interceptions",
            False,
            f"missed={missed} in VictoriaLogs",
        )
    return CheckResult(
        "steady-state missed interceptions",
        True,
        f"missed=0 (LogsQL window {window})",
    )


def run_verification(
    *,
    api_metrics_url: str = "http://127.0.0.1:8080/metrics",
    vm_base: str = "http://127.0.0.1:8428",
    grafana_base: str = "http://127.0.0.1:3001",
    vl_base: str = "http://127.0.0.1:9428",
    skip_steady_state: bool = False,
    skip_grafana: bool = False,
    skip_vm: bool = False,
    steady_state_window: str = "15m",
    project_root: Optional[Path] = None,
) -> VerifyReport:
    root = project_root or _project_root()
    report = VerifyReport()

    m = check_metrics_endpoint(api_metrics_url)
    report.add(m.name, m.ok, m.detail)

    if not skip_vm:
        for check in (
            check_vm_scrape_target(vm_base),
            check_vm_promql(
                vm_base,
                "vita_crisis_intercepted_total",
                "VM PromQL crisis counters",
            ),
        ):
            report.add(check.name, check.ok, check.detail)

    if not skip_grafana:
        g = check_grafana_health(grafana_base)
        report.add(g.name, g.ok, g.detail)

    for prov in check_provisioning_files(root):
        report.add(prov.name, prov.ok, prov.detail)

    if not skip_steady_state:
        s = check_victorialogs_missed_steady_state(vl_base, window=steady_state_window)
        report.add(s.name, s.ok, s.detail)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify P5-1 monitoring stack")
    parser.add_argument("--api-metrics-url", default="http://127.0.0.1:8080/metrics")
    parser.add_argument("--vm-url", default="http://127.0.0.1:8428")
    parser.add_argument("--grafana-url", default="http://127.0.0.1:3001")
    parser.add_argument("--victorialogs-url", default="http://127.0.0.1:9428")
    parser.add_argument("--skip-steady-state", action="store_true")
    parser.add_argument("--skip-grafana", action="store_true")
    parser.add_argument("--skip-vm", action="store_true")
    parser.add_argument("--steady-state-window", default="15m")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_verification(
        api_metrics_url=args.api_metrics_url,
        vm_base=args.vm_url,
        grafana_base=args.grafana_url,
        vl_base=args.victorialogs_url,
        skip_steady_state=args.skip_steady_state,
        skip_grafana=args.skip_grafana,
        skip_vm=args.skip_vm,
        steady_state_window=args.steady_state_window,
    )

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
        return 0 if report.ok else 1

    print("[INFO] P5-1 monitoring verification")
    for check in report.checks:
        tag = "OK" if check.ok else "FAIL"
        line = f"  [{tag}] {check.name}"
        if check.detail:
            line += f": {check.detail}"
        print(line)

    if report.ok:
        print("[OK] P5-1 monitoring verification passed")
        return 0
    print("[FAIL] P5-1 monitoring verification failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

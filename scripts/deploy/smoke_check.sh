#!/usr/bin/env bash
# Smoke checks after docker compose up (P3-5).
# Usage: SMOKE_BASE_URL=http://localhost:8080 bash scripts/deploy/smoke_check.sh

set -euo pipefail

BASE_URL="${SMOKE_BASE_URL:-http://localhost:8080}"
HEALTH_URL="${BASE_URL}/health"
METRICS_URL="${BASE_URL}/metrics"
MAX_WAIT_SEC="${SMOKE_MAX_WAIT_SEC:-180}"
INTERVAL_SEC="${SMOKE_INTERVAL_SEC:-5}"

echo "[SMOKE] Waiting for ${HEALTH_URL} (max ${MAX_WAIT_SEC}s)..."

elapsed=0
while [ "${elapsed}" -lt "${MAX_WAIT_SEC}" ]; do
  if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
    echo "[SMOKE] Health endpoint reachable after ${elapsed}s"
    break
  fi
  sleep "${INTERVAL_SEC}"
  elapsed=$((elapsed + INTERVAL_SEC))
done

if [ "${elapsed}" -ge "${MAX_WAIT_SEC}" ]; then
  echo "[FAIL] Health endpoint not reachable: ${HEALTH_URL}" >&2
  exit 1
fi

curl -fsS "${HEALTH_URL}" | head -c 512
echo ""

echo "[SMOKE] Checking Prometheus metrics for vita_crisis_* series..."
if ! curl -fsS "${METRICS_URL}" | grep -q 'vita_crisis'; then
  echo "[FAIL] /metrics missing vita_crisis counters" >&2
  exit 1
fi

echo "[OK] Smoke checks passed (${HEALTH_URL}, ${METRICS_URL})"

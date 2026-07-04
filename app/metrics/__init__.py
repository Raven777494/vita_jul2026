"""Clinical crisis interception metrics (Prometheus + VictoriaLogs)."""

import os as _os

# Prometheus multiprocess mode: when running multiple uvicorn/gunicorn workers,
# each worker has its own metric registry. PROMETHEUS_MULTIPROC_DIR aggregates
# them via a shared mmap directory so GET /metrics returns cluster-wide totals.
# The directory must exist before any metric is defined below.
_multiproc_dir = _os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if _multiproc_dir:
    _os.makedirs(_multiproc_dir, exist_ok=True)

from app.metrics.crisis_metrics import (
    crisis_interception_rate,
    record_crisis_interception_outcome,
    reset_crisis_metrics_for_tests,
)

__all__ = [
    "crisis_interception_rate",
    "record_crisis_interception_outcome",
    "reset_crisis_metrics_for_tests",
]

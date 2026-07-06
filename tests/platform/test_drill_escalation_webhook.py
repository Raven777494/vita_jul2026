"""Tests for P5-2 escalation webhook drill script."""

from __future__ import annotations

import pytest

from scripts.observability.drill_escalation_webhook import _run_drill


@pytest.mark.asyncio
async def test_drill_escalation_dry_run_delivers_log_backend():
    code = await _run_drill(risk_level=4, dry_run=True)
    assert code == 0

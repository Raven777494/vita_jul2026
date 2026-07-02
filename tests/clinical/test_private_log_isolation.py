"""Verify private logs are excluded from VictoriaLogs shipping (US-4 / PRD)."""

from __future__ import annotations

import logging

from app.logger import (
    LogTypeFilter,
    VictoriaLogsShipHandler,
    _VICTORIA_EXCLUDED_LOG_TYPES,
    setup_logger,
)


def test_private_log_type_in_exclusion_set() -> None:
    assert "private" in _VICTORIA_EXCLUDED_LOG_TYPES


def test_private_logger_does_not_attach_victoria_shipper() -> None:
    logger = setup_logger(
        "test_private_no_ship",
        "private",
        level="INFO",
        use_json=True,
    )
    ship_handlers = [h for h in logger.handlers if isinstance(h, VictoriaLogsShipHandler)]
    assert ship_handlers == [], "private log_type must not attach VictoriaLogs shipper"


def test_app_logger_attaches_victoria_shipper_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_VICTORIA_LOGS_SHIPPER", "true")
    logger = setup_logger(
        "test_app_ship",
        "app",
        level="INFO",
        use_json=True,
    )
    ship_handlers = [h for h in logger.handlers if isinstance(h, VictoriaLogsShipHandler)]
    assert ship_handlers, "app log_type should attach VictoriaLogs shipper when enabled"


def test_log_type_filter_tags_private() -> None:
    filt = LogTypeFilter("private")
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="x",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert getattr(record, "vita_log_type", None) == "private"

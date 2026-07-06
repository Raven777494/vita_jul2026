"""Pytest session hooks — disable VictoriaLogs shipping during tests."""

from __future__ import annotations

import os


def pytest_configure(config) -> None:
    """Prevent local pytest runs from polluting VictoriaLogs steady-state checks."""
    _ = config
    os.environ["ENABLE_VICTORIA_LOGS_SHIPPER"] = "false"
    try:
        from app.config import Config
        import app.logger as logger_module

        Config.ENABLE_VICTORIA_LOGS_SHIPPER = False
        handler = getattr(logger_module, "_victoria_ship_handler", None)
        if handler is not None:
            handler.close()
        logger_module._victoria_ship_handler = None
    except ImportError:
        pass

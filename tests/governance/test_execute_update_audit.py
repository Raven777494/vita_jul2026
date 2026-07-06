"""Tests for TD-003 execute_update audit and error propagation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.governance.audit_execute_update import (
    ALLOWED_CALL_SITES,
    audit_execute_update,
    find_execute_update_calls,
)


def test_allowed_call_sites_cover_db_manager_and_retention():
    assert "app/services/db_manager.py" in ALLOWED_CALL_SITES
    assert "scripts/db/retention_batch.py" in ALLOWED_CALL_SITES


def test_find_execute_update_calls_includes_retention_batch():
    sites = find_execute_update_calls()
    paths = {s.path for s in sites}
    assert "scripts/db/retention_batch.py" in paths


def test_audit_execute_update_passes_on_repo():
    errors, _warnings = audit_execute_update()
    assert errors == []


def test_execute_update_raises_database_update_error():
    from app.services.db_manager import DatabaseManager, DatabaseUpdateError

    mgr = object.__new__(DatabaseManager)
    session = MagicMock()
    session.execute.side_effect = RuntimeError("syntax error at line 1")

    with patch.object(mgr, "get_session", return_value=session):
        with pytest.raises(DatabaseUpdateError, match="execute_update failed"):
            mgr.execute_update("BAD SQL")

    session.rollback.assert_called_once()
    session.close.assert_called_once()

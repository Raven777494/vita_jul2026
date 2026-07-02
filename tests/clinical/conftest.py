"""Shared fixtures for clinical scenario tests (no Redis required)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict

import pytest

from app.services.emotional_safety_hub import EmotionalSafetyHub
from app.services.session_manager import SessionManager


@pytest.fixture
def session_manager() -> SessionManager:
    """Session manager using in-memory fallback when Redis is unavailable."""
    manager = SessionManager()
    manager.redis = None
    manager._memory_cache.clear()
    return manager


@pytest.fixture
def emotional_hub(session_manager: SessionManager) -> EmotionalSafetyHub:
    return EmotionalSafetyHub(
        session_manager=session_manager,
        llm_service=None,
        risk_assessor=None,
    )


@pytest.fixture
def base_session_state() -> Dict[str, Any]:
    return {
        "session_id": "clinical-test-session-001",
        "user_id": "clinical-user-001",
        "conversation_id": "clinical-conv-001",
        "created_at": datetime.now().isoformat(),
        "last_updated_at": datetime.now().isoformat(),
        "turn_count": 0,
        "risk_level": 1,
        "walker_score": 0.5,
        "messages": [],
        "is_active": True,
        "escalation_history": [],
    }


@pytest.fixture
def fresh_session(base_session_state: Dict[str, Any]) -> Dict[str, Any]:
    return deepcopy(base_session_state)

"""Tests for app/services/user_erasure.py (B-zone go-live)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from app.services.user_erasure import (
    UserErasureError,
    UserNotFoundError,
    erase_user,
    hash_user_id,
    invalidate_user_redis_keys,
    run_erasure_in_session,
)


class FakeResult:
    def __init__(self, rows: List[Tuple[Any, ...]], rowcount: int = 0) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeSession:
    def __init__(
        self,
        *,
        user_exists: bool = True,
        session_ids: Optional[List[str]] = None,
    ) -> None:
        self.user_exists = user_exists
        self.session_ids = session_ids or ["sess-1", "sess-2"]
        self.executed: List[Tuple[str, Optional[dict]]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement: Any, params: Optional[dict] = None) -> FakeResult:
        query = str(statement)
        self.executed.append((query, params))

        if "SELECT 1 FROM users WHERE id" in query:
            if not self.user_exists:
                return FakeResult([])
            return FakeResult([(1,)])

        if "active_sessions" in query and "UNION" in query:
            return FakeResult([(sid,) for sid in self.session_ids])

        if "DELETE FROM escalation_events" in query:
            return FakeResult([], rowcount=3)

        if "DELETE FROM session_history" in query:
            return FakeResult([], rowcount=1)

        if "DELETE FROM users" in query:
            return FakeResult([], rowcount=1)

        return FakeResult([])

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class FakeDb:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def get_session(self) -> FakeSession:
        return self._session


class FakeRedis:
    def __init__(self, keys: Optional[List[str]] = None) -> None:
        self.keys = list(keys or [])
        self.deleted: List[str] = []

    def scan(self, cursor: int = 0, match: str = "", count: int = 100):
        matched = [k for k in self.keys if k.startswith(match.replace("*", ""))]
        return 0, matched

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.keys:
                self.keys.remove(key)
                self.deleted.append(key)
                removed += 1
        return removed


def test_hash_user_id_is_stable_and_short() -> None:
    first = hash_user_id("user-abc")
    second = hash_user_id("user-abc")
    assert first == second
    assert len(first) == 16


def test_run_erasure_in_session_order_and_counts() -> None:
    session = FakeSession(user_exists=True, session_ids=["a", "b"])
    deleted = run_erasure_in_session(session, "user-123")

    assert deleted == {
        "escalation_events": 3,
        "session_history": 1,
        "users": 1,
    }
    delete_queries = [q for q, _ in session.executed if q.startswith("DELETE")]
    assert "escalation_events" in delete_queries[0]
    assert "session_history" in delete_queries[1]
    assert "users" in delete_queries[2]


def test_run_erasure_raises_when_user_missing() -> None:
    session = FakeSession(user_exists=False)
    with pytest.raises(UserNotFoundError):
        run_erasure_in_session(session, "missing-user")


def test_erase_user_commits_and_invalidates_redis() -> None:
    session = FakeSession()
    db = FakeDb(session)
    redis = FakeRedis(["session:user-1:conv-a", "session:user-1:conv-b", "session:other:conv"])

    result = erase_user(db, "user-1", redis_client=redis)

    assert session.committed is True
    assert session.closed is True
    assert result.deleted["users"] == 1
    assert result.redis_keys_removed == 2
    assert len(result.request_id) == 36


def test_erase_user_rolls_back_on_failure() -> None:
    session = FakeSession()

    def fail_users_delete(statement: Any, params: Optional[dict] = None) -> FakeResult:
        query = str(statement)
        session.executed.append((query, params))
        if "SELECT 1 FROM users" in query:
            return FakeResult([(1,)])
        if "UNION" in query:
            return FakeResult([])
        if "DELETE FROM escalation_events" in query:
            return FakeResult([], rowcount=0)
        if "DELETE FROM session_history" in query:
            return FakeResult([], rowcount=0)
        if "DELETE FROM users" in query:
            return FakeResult([], rowcount=0)
        return FakeResult([])

    session.execute = fail_users_delete  # type: ignore[method-assign]

    with pytest.raises(UserErasureError):
        erase_user(FakeDb(session), "user-1")

    assert session.rolled_back is True
    assert session.closed is True


def test_invalidate_user_redis_keys_noop_without_client() -> None:
    assert invalidate_user_redis_keys(None, "user-1") == 0

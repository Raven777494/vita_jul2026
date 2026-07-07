"""User data erasure per docs/database/data-classification.md."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from sqlalchemy import text as sql_text

logger = logging.getLogger("vita.user_erasure")


class UserErasureError(Exception):
    """Base error for user erasure failures."""


class UserNotFoundError(UserErasureError):
    """Raised when the target user id does not exist."""


@dataclass(frozen=True)
class ErasureResult:
    request_id: str
    user_id_hash: str
    deleted: Dict[str, int]
    redis_keys_removed: int


class _DbSession(Protocol):
    def execute(self, statement: Any, params: Optional[dict] = None) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class _DbManager(Protocol):
    def get_session(self) -> _DbSession: ...


def hash_user_id(user_id: str) -> str:
    """Return a short hash for audit logs (no raw user id in shipped logs)."""
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def _user_exists(session: _DbSession, user_id: str) -> bool:
    row = session.execute(
        sql_text("SELECT 1 FROM users WHERE id = :uid LIMIT 1"),
        {"uid": user_id},
    ).fetchone()
    return row is not None


def _collect_session_ids(session: _DbSession, user_id: str) -> List[str]:
    rows = session.execute(
        sql_text(
            """
            SELECT session_id::text AS sid FROM active_sessions WHERE user_id = :uid
            UNION
            SELECT session_id::text AS sid FROM session_history WHERE user_id = :uid
            """
        ),
        {"uid": user_id},
    ).fetchall()
    return [str(row[0]) for row in rows if row[0] is not None]


def run_erasure_in_session(session: _DbSession, user_id: str) -> Dict[str, int]:
    """Execute hard-delete steps in order inside an open transaction."""
    if not _user_exists(session, user_id):
        raise UserNotFoundError(user_id)

    deleted: Dict[str, int] = {}
    session_ids = _collect_session_ids(session, user_id)

    if session_ids:
        result = session.execute(
            sql_text(
                "DELETE FROM escalation_events WHERE session_id::text = ANY(:sids)"
            ),
            {"sids": session_ids},
        )
        deleted["escalation_events"] = int(result.rowcount or 0)
    else:
        deleted["escalation_events"] = 0

    result = session.execute(
        sql_text("DELETE FROM session_history WHERE user_id = :uid"),
        {"uid": user_id},
    )
    deleted["session_history"] = int(result.rowcount or 0)

    result = session.execute(
        sql_text("DELETE FROM users WHERE id = :uid"),
        {"uid": user_id},
    )
    deleted["users"] = int(result.rowcount or 0)

    if deleted["users"] != 1:
        raise UserErasureError(
            f"Expected to delete exactly one user row, got {deleted['users']}"
        )

    return deleted


def invalidate_user_redis_keys(redis_client: Any, user_id: str) -> int:
    """Remove cached session keys for the user (best-effort)."""
    if redis_client is None:
        return 0

    removed = 0
    cursor = 0
    pattern = f"session:{user_id}:*"
    while True:
        cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            removed += int(redis_client.delete(*keys))
        if cursor == 0:
            break
    return removed


def erase_user(
    db: _DbManager,
    user_id: str,
    *,
    redis_client: Any = None,
) -> ErasureResult:
    """Hard-delete user data per data-classification cascade rules."""
    if not user_id or not str(user_id).strip():
        raise UserErasureError("user_id is required")

    request_id = str(uuid.uuid4())
    user_id_hash = hash_user_id(user_id)
    session = db.get_session()
    try:
        deleted = run_erasure_in_session(session, user_id)
        session.commit()
    except UserNotFoundError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise UserErasureError(str(exc)) from exc
    finally:
        session.close()

    redis_keys_removed = invalidate_user_redis_keys(redis_client, user_id)

    logger.info(
        "[ERASURE] request_id=%s user_id_hash=%s deleted=%s redis_keys=%s",
        request_id,
        user_id_hash,
        deleted,
        redis_keys_removed,
    )

    return ErasureResult(
        request_id=request_id,
        user_id_hash=user_id_hash,
        deleted=deleted,
        redis_keys_removed=redis_keys_removed,
    )

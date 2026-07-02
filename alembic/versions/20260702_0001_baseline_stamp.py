"""Baseline stamp — ORM schema bootstrapped by db_manager + init-db.

Revision ID: 20260702_0001
Revises:
Create Date: 2026-07-02

Platform extensions (vector, age, pg_cron) and AGE graph vita_memory_graph
are provisioned by init-db/*.sql and db_manager bootstrap, not Alembic.
Use `alembic revision --autogenerate` for subsequent ORM changes.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260702_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

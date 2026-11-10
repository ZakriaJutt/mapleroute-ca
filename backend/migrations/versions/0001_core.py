"""0001 core tables, row-level security and triggers (T-2.2.1).

Revision ID: 0001_core
Revises:
"""

from pathlib import Path

from alembic import op

revision = "0001_core"
down_revision = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parent.parent / "sql" / "0001_core.sql").read_text()
    # Driver-level execute without parameters, so "%" in PL/pgSQL RAISE is not a placeholder.
    op.get_bind().connection.driver_connection.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("one linear history; roll forward")

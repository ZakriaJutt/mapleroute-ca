"""0006 per-binding check generation; database clock app_now().

B1 fix round 4: B1-012 under clock skew.

Revision ID: 0006_check_generation_db_clock
Revises: 0005_check_lease_mismatch_fence
"""

from pathlib import Path

from alembic import op

revision = "0006_check_generation_db_clock"
down_revision = "0005_check_lease_mismatch_fence"


def upgrade() -> None:
    sql = (Path(__file__).resolve().parent.parent / "sql" / "0006_check_generation_db_clock.sql").read_text()
    op.get_bind().connection.driver_connection.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("one linear history; roll forward")

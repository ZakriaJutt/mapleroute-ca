"""0005 per-binding check lease; mismatch fence on binding; verification start; tenant-scoped job keys.

B1 fix round 3: B1-003, B1-012, B1-005 part.

Revision ID: 0005_check_lease_mismatch_fence
Revises: 0004_observation_order_job_rls
"""

from pathlib import Path

from alembic import op

revision = "0005_check_lease_mismatch_fence"
down_revision = "0004_observation_order_job_rls"


def upgrade() -> None:
    sql = (Path(__file__).resolve().parent.parent / "sql" / "0005_check_lease_mismatch_fence.sql").read_text()
    op.get_bind().connection.driver_connection.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("one linear history; roll forward")

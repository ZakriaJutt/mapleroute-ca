"""0004 observation ordering column on binding; row-level security on job.

B1 fix round 2: B1-012, B1-005 part.

Revision ID: 0004_observation_order_job_rls
Revises: 0003_process_roles
"""

from pathlib import Path

from alembic import op

revision = "0004_observation_order_job_rls"
down_revision = "0003_process_roles"


def upgrade() -> None:
    sql = (Path(__file__).resolve().parent.parent / "sql" / "0004_observation_order_job_rls.sql").read_text()
    op.get_bind().connection.driver_connection.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("one linear history; roll forward")

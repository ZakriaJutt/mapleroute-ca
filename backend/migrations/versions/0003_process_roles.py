"""0003 per-process roles, definer-owned functions, verification tied to the binding's route.

B1 fix round 1: B1-004, B1-005.

Revision ID: 0003_process_roles
Revises: 0002_app_role_grants
"""

from pathlib import Path

from alembic import op

revision = "0003_process_roles"
down_revision = "0002_app_role_grants"


def upgrade() -> None:
    sql = (Path(__file__).resolve().parent.parent / "sql" / "0003_process_roles.sql").read_text()
    op.get_bind().connection.driver_connection.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("one linear history; roll forward")

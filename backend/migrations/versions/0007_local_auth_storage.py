"""0007 local sign-in, sessions, invitations, report table (B2).

Build milestone B2: T-4.1.1, T-4.1.2 (local provider), report storage.

Revision ID: 0007_local_auth_storage
Revises: 0006_check_generation_db_clock
"""

from pathlib import Path

from alembic import op

revision = "0007_local_auth_storage"
down_revision = "0006_check_generation_db_clock"


def upgrade() -> None:
    sql = (Path(__file__).resolve().parent.parent / "sql" / "0007_local_auth_storage.sql").read_text()
    op.get_bind().connection.driver_connection.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("one linear history; roll forward")

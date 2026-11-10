"""0002 grants for the application role (T-2.2.1).

The role is created by tools/db_bootstrap (NOSUPERUSER NOBYPASSRLS). B1 uses one application
role for all three processes; the per-process split of schema.md is recorded as not yet built.
No DELETE is granted on any table: append-only and transition rules are enforced by triggers.

Revision ID: 0002_app_role_grants
Revises: 0001_core
"""

from alembic import op

revision = "0002_app_role_grants"
down_revision = "0001_core"

APP_ROLE = "mapleroute_app"
TABLES = [
    "tenant", "user_account", "membership", "form_token", "project", "provider_connection",
    "connection_secret", "api_key", "allowlist_version", "route", "allowlist_route", "binding",
    "verification", "logging_observation", "request_log", "alert", "audit_event", "job",
]


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    for table in TABLES:
        bind.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
    bind.exec_driver_sql(f"GRANT DELETE ON form_token TO {APP_ROLE}")
    for fn in ("app_tenant_id()", "resolve_api_key(bytea)", "tenants_bound_to_route(text)"):
        bind.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION {fn} TO {APP_ROLE}")


def downgrade() -> None:
    raise NotImplementedError("one linear history; roll forward")

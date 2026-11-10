"""Tenant context: set once per request or job, from the authenticated key, session or job row.

Never from a request parameter. The setting is transaction-local, so a pooled connection cannot
carry one tenant's context into another request (R-05).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_tenant(session: Session, tenant_id: uuid.UUID) -> None:
    session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})


def current_tenant(session: Session) -> uuid.UUID | None:
    value = session.execute(text("SELECT app_tenant_id()")).scalar()
    return value if isinstance(value, uuid.UUID) or value is None else uuid.UUID(str(value))

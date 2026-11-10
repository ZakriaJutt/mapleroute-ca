"""Audit events: actor, tenant, time, correlation ID; never secrets or content (TRD.md audit events).

Inserted without RETURNING: operator-global rows (tenant NULL) are writable but not readable
through the tenant policy, and RETURNING would need read access.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from core.logging import get_correlation_id
from core.models import AuditEvent


def record(session: Session, tenant_id: uuid.UUID | None, actor_kind: str, actor_user_id: uuid.UUID | None,
           action: str, target: str, detail: dict[str, Any] | None = None) -> None:
    session.flush()
    session.execute(
        insert(AuditEvent).values(
            id=uuid.uuid4(), tenant_id=tenant_id, actor_kind=actor_kind, actor_user_id=actor_user_id, action=action,
            target=target, correlation_id=get_correlation_id(), detail=detail or {},
        )
    )

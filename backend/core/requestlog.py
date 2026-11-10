"""Request log: audit-before-forward and the state machine (T-3.1.3, T-3.1.7, AD-04, R-01, R-02).

The row is committed before any upstream byte is sent. State changes are compare-and-set on the
current state; the database trigger enforces the same transitions. No content is stored.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, update
from sqlalchemy.orm import Session

from core.config import ALIAS_MAX_LEN
from core.models import RequestLog

STATES = ("rejected", "forwarding", "completed", "upstream_error", "client_aborted", "unknown_outcome")
TRANSITIONS: dict[str, frozenset[str]] = {
    "forwarding": frozenset({"completed", "upstream_error", "client_aborted", "unknown_outcome"}),
    "unknown_outcome": frozenset({"completed", "upstream_error"}),
}


def allowed(old: str, new: str) -> bool:
    return new in TRANSITIONS.get(old, frozenset())


@dataclass(frozen=True)
class NewRow:
    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    api_key_id: uuid.UUID
    received_at: datetime
    endpoint: str
    alias: str
    state: str
    code: str | None = None
    http_status: int | None = None
    route_id: str | None = None
    allowlist_version: str | None = None
    route_status: str | None = None
    binding_verified_at: datetime | None = None
    request_bytes: int | None = None


def insert(session: Session, row: NewRow) -> None:
    session.add(
        RequestLog(
            id=row.id, tenant_id=row.tenant_id, project_id=row.project_id, api_key_id=row.api_key_id,
            received_at=row.received_at, endpoint=row.endpoint, alias=row.alias[:ALIAS_MAX_LEN],
            route_id=row.route_id, allowlist_version=row.allowlist_version, route_status=row.route_status,
            binding_verified_at=row.binding_verified_at, state=row.state, code=row.code,
            http_status=row.http_status, request_bytes=row.request_bytes,
        )
    )
    session.flush()


def transition(session: Session, request_id: uuid.UUID, received_at: datetime, new_state: str, now: datetime,
               **fields: object) -> bool:
    """Compare-and-set to ``new_state``. False if the row was not in a state that may move to it.

    A late completion of an ``unknown_outcome`` row also records ``reconciled_at`` (R-02).
    """
    sources = [s for s, targets in TRANSITIONS.items() if new_state in targets]
    values: dict[str, object] = {"state": new_state, **fields}
    if new_state in ("completed", "upstream_error", "client_aborted"):
        values.setdefault("completed_at", now)
    key = and_(RequestLog.id == request_id, RequestLog.received_at == received_at)
    for source in sources:
        extra = {"reconciled_at": now} if source == "unknown_outcome" else {}
        stmt = update(RequestLog).where(key, RequestLog.state == source).values(**values, **extra)
        if session.execute(stmt).rowcount:  # type: ignore[attr-defined]
            return True
    return False


def sweep_forwarding(session: Session, cutoff: datetime) -> int:
    """Rows still `forwarding` since before ``cutoff`` become `unknown_outcome` (sweep_outcomes, R-02).

    Runs under the tenant context set by the caller.
    """
    stmt = (
        update(RequestLog)
        .where(RequestLog.state == "forwarding", RequestLog.received_at < cutoff)
        .values(state="unknown_outcome")
    )
    return int(session.execute(stmt).rowcount)  # type: ignore[attr-defined]

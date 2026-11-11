"""Per-binding locks (B1-001, B1-003).

Two mechanisms:

- ``binding_lock``: advisory transaction lock. The worker holds it exclusively while it applies a
  verification result; the gateway holds it shared while it evaluates ``forwardable`` and commits
  the log row. No request is decided on a binding's old status while a mismatch for it is being
  applied, and every request committed before the mismatch is visible to the window flagging.
  Advisory locks need no table privilege, so the gateway needs no UPDATE right on ``binding``.
- ``claim_check`` / ``holds_check`` / ``release_check``: the check lease, a claimed row in
  ``binding_check_lease`` identified by a random token (``holder``). At most one check of a binding
  runs at a time, from before its first provider read until its result is recorded. The claim
  commits in its own transaction so every other worker sees it; a second check is skipped, never
  overlaps. The claim records the binding's ``check_generation``. Lease times are the database
  clock (``app_now()``), never a worker's: a lease is taken over only when the database clock has
  passed ``expires_at`` (``CHECK_LEASE``), so a dead worker blocks a binding for at most that long
  and no worker's clock can make a live lease look expired. A worker whose lease was taken over no
  longer holds its token: ``holds_check`` is false (B1-012, fix round 4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from core import tenancy
from core.config import CHECK_LEASE


def binding_lock(session: Session, project_id: uuid.UUID, alias: str, *, shared: bool) -> None:
    fn = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    session.execute(text(f"SELECT {fn}(hashtextextended(:k, 0))"), {"k": f"binding:{project_id}:{alias}"})


@dataclass(frozen=True)
class CheckLease:
    binding_id: uuid.UUID
    holder: uuid.UUID  # the token
    generation: int  # binding.check_generation when the lease was claimed
    started_at: datetime  # database clock
    expires_at: datetime  # database clock


def _engine(session: Session) -> Engine:
    bind = session.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind


_CLAIM = text(
    "INSERT INTO binding_check_lease (binding_id, tenant_id, holder, generation, started_at, expires_at) "
    "SELECT b.id, b.tenant_id, :h, b.check_generation, n.at, n.at + make_interval(secs => :lease) "
    "FROM binding b CROSS JOIN (SELECT app_now() AS at) n WHERE b.id = :b "
    "ON CONFLICT (binding_id) DO UPDATE SET holder = EXCLUDED.holder, generation = EXCLUDED.generation, "
    "started_at = EXCLUDED.started_at, expires_at = EXCLUDED.expires_at "
    "WHERE binding_check_lease.expires_at <= app_now() "
    "RETURNING holder, generation, started_at, expires_at"
)


def claim_check(session: Session, tenant_id: uuid.UUID, binding_id: uuid.UUID,
                now: datetime | None = None) -> CheckLease | None:
    """Claim the binding's check lease in a separate, committed transaction. None while another
    check holds an unexpired lease. ``now`` is ignored: every time here is the database clock."""
    token = uuid.uuid4()
    with Session(_engine(session)) as own, own.begin():
        tenancy.set_tenant(own, tenant_id)
        row = own.execute(_CLAIM, {"b": binding_id, "h": token, "lease": CHECK_LEASE.total_seconds()}).first()
    if row is None or row[0] != token:
        return None
    return CheckLease(binding_id, token, int(row[1]), row[2], row[3])


def holds_check(session: Session, lease: CheckLease) -> bool:
    """In the result transaction: lock the lease row and say whether this check's token still holds it."""
    row = session.execute(
        text("SELECT holder FROM binding_check_lease WHERE binding_id = :b FOR UPDATE"), {"b": lease.binding_id}
    ).first()
    return row is not None and row[0] == lease.holder


def release_check(session: Session, lease: CheckLease) -> None:
    """Release in the result transaction (atomic with the result). Only this token's row is removed."""
    session.execute(text("DELETE FROM binding_check_lease WHERE binding_id = :b AND holder = :h"),
                    {"b": lease.binding_id, "h": lease.holder})


def release_check_detached(session: Session, tenant_id: uuid.UUID, lease: CheckLease) -> None:
    """Release in a separate transaction; used when the check failed before taking the row lock."""
    with Session(_engine(session)) as own, own.begin():
        tenancy.set_tenant(own, tenant_id)
        release_check(own, lease)


def db_now(session: Session) -> datetime:
    """The database clock (``app_now()``), the only clock a safety decision uses."""
    value: datetime = session.execute(text("SELECT app_now()")).scalar_one()
    return value

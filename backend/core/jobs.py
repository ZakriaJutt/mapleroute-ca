"""Job table with FOR UPDATE SKIP LOCKED (AD-07). Unique (kind, dedupe_key): re-enqueue is a no-op."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.logging import get_correlation_id
from core.models import Job

MAX_ATTEMPTS = {"verify_binding": 3, "notify_route_suspended": 5}
DEFAULT_MAX_ATTEMPTS = 3


def enqueue(session: Session, kind: str, dedupe_key: str, *, tenant_id: uuid.UUID | None = None,
            payload: dict[str, Any] | None = None, run_after: datetime | None = None) -> uuid.UUID | None:
    values: dict[str, Any] = {
        "kind": kind, "dedupe_key": dedupe_key, "tenant_id": tenant_id, "payload": payload or {},
        "correlation_id": get_correlation_id(),
    }
    if run_after is not None:
        values["run_after"] = run_after
    row = session.execute(
        insert(Job).values(**values).on_conflict_do_nothing(constraint="uq_job_kind_dedupe").returning(Job.id)
    ).first()
    return row[0] if row else None


def claim(session: Session, now: datetime) -> Job | None:
    job = session.execute(
        select(Job).where(Job.state == "queued", Job.run_after <= now)
        .order_by(Job.run_after).limit(1).with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is not None:
        job.state = "running"
        job.locked_at = now
        job.attempts += 1
        session.flush()
    return job


def finish(session: Session, job: Job) -> None:
    job.state = "done"
    session.flush()


def fail(session: Session, job: Job, now: datetime, error_code: str) -> None:
    """Retry with backoff 1, 4, 15 minutes up to the kind's limit; then `failed`."""
    job.last_error_code = error_code
    if job.attempts >= MAX_ATTEMPTS.get(job.kind, DEFAULT_MAX_ATTEMPTS):
        job.state = "failed"
    else:
        job.state = "queued"
        job.run_after = now + timedelta(minutes=(1, 4, 15)[min(job.attempts - 1, 2)])
    session.flush()

"""Stored report files (B2): the row in ``report`` and the object in storage under the tenant's
prefix (R-13). Report generation itself (T-5.1.x) is not built; this module stores a finished file
and reads it back for the tenant that owns it.

Every call runs inside a transaction whose tenant context is already set, so row-level security
hides other tenants' rows; the object store also refuses a key outside the tenant's prefix.
The stored SHA-256 is checked on every read, so an altered object is refused (TRD.md threat model).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from core.models import Report
from core.storage import ObjectStore, object_key


class ReportUnavailable(Exception):
    """Not found for this tenant, not ready, or the file no longer matches its hash."""


@dataclass(frozen=True)
class StoredReport:
    id: uuid.UUID
    object_key: str
    sha256_hex: str


def store_report(s: Session, store: ObjectStore, tenant_id: uuid.UUID, period_start: date, period_end: date,
                 kind: str, body: bytes, content_type: str, allowlist_versions: list[str],
                 totals: dict[str, Any]) -> StoredReport:
    """Insert the row as ``generating``, upload, then mark ``ready`` with the hash."""
    report_id = uuid.uuid4()
    s.execute(insert(Report).values(id=report_id, tenant_id=tenant_id, period_start=period_start,
                                    period_end=period_end, kind=kind, state="generating"))
    ext = "pdf" if content_type == "application/pdf" else "bin"
    key = object_key(tenant_id, "worker", "report", f"{report_id}.{ext}")
    digest = hashlib.sha256(body).digest()
    store.put(tenant_id, key, body, content_type)
    s.execute(update(Report).where(Report.id == report_id).values(
        state="ready", object_key=key, sha256=digest, allowlist_versions=allowlist_versions, totals=totals,
        content_type=content_type, byte_size=len(body)))
    return StoredReport(report_id, key, digest.hex())


def ready_report(s: Session, report_id: uuid.UUID) -> Report:
    row = s.execute(select(Report).where(Report.id == report_id)).scalar_one_or_none()
    if row is None or row.state != "ready" or row.object_key is None or row.sha256 is None:
        raise ReportUnavailable()
    return row


def read_report(s: Session, store: ObjectStore, tenant_id: uuid.UUID, report_id: uuid.UUID) -> tuple[Report, bytes]:
    row = ready_report(s, report_id)
    assert row.object_key is not None and row.sha256 is not None
    data = store.get(tenant_id, row.object_key)
    if not hmac.compare_digest(hashlib.sha256(data).digest(), row.sha256):
        raise ReportUnavailable()
    return row, data

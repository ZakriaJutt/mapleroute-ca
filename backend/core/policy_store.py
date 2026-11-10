"""Allow-list versions in the database: publish a draft, approve, load the active one (T-3.1.1, AD-12).

Versions are never edited. Re-publishing the same version with the same content is idempotent and
returns the existing record; the same version with different content is refused.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core import audit
from core.allowlist import AllowlistDoc, AllowlistError, PolicyUnavailable, build_version, load_verified
from core.models import AllowlistRoute, AllowlistVersion, Route, UserAccount

ROUTE_REMOVAL_NOTICE = timedelta(days=7)


class VersionConflict(AllowlistError):
    pass


class NotOperator(PermissionError):
    pass


@dataclass(frozen=True)
class PublishResult:
    version: str
    sha256_hex: str
    created: bool


def publish_draft(session: Session, version: str, routes: Iterable[Mapping[str, Any]],
                  actor: uuid.UUID) -> PublishResult:
    doc, digest = build_version(version, routes)
    existing = session.get(AllowlistVersion, version)
    if existing is not None:
        if bytes(existing.sha256) != digest:
            raise VersionConflict(f"version {version} exists with different content; publish a new version")
        return PublishResult(version, digest.hex(), created=False)
    session.add(AllowlistVersion(version=version, document=doc, sha256=digest, state="draft"))
    for r in doc["routes"]:
        session.execute(
            insert(Route)
            .values(
                id=r["id"], provider=r["provider"], source_region=r["source_region"], identifier=r["identifier"],
                deployment_class=r["deployment_class"], model_version=r["model_version"],
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
    session.flush()
    for r in doc["routes"]:
        session.add(AllowlistRoute(version=version, route_id=r["id"], destinations=r["destinations"]))
    audit.record(session, None, "operator", actor, "allowlist_publish", version, {"sha256": digest.hex()})
    session.flush()
    return PublishResult(version, digest.hex(), created=True)


def tenants_on_route(session: Session, route_id: str) -> list[uuid.UUID]:
    """Tenant IDs bound to a route (IDs only; SECURITY DEFINER function in 0001_core)."""
    rows = session.execute(text("SELECT tenant_id FROM tenants_bound_to_route(:r)"), {"r": route_id}).scalars()
    return list(rows)


def approve(session: Session, version: str, approver: uuid.UUID, now: datetime) -> AllowlistVersion:
    """Approve a draft. Activates now unless it removes a route in use that is not suspended;
    then activation waits 7 days (MH-08)."""
    user = session.get(UserAccount, approver)
    if user is None or not user.is_operator:
        raise NotOperator("only the operator approves allow-list versions")
    row = session.execute(
        select(AllowlistVersion).where(AllowlistVersion.version == version).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise AllowlistError(f"version {version} not found")
    if row.state != "draft":
        return row  # idempotent: already approved
    new_doc = load_verified(row.version, row.document, row.sha256)
    current = load_active(session)
    removed = {
        r for r in (set(current.entries) - set(new_doc.entries) if current else set()) if tenants_on_route(session, r)
    }
    waiting = False
    if removed:
        suspended = set(
            session.execute(
                select(Route.id).where(Route.id.in_(removed), Route.global_status == "suspended")
            ).scalars()
        )
        waiting = bool(removed - suspended)
    row.approved_by = approver
    row.approved_at = now
    if waiting:
        row.activate_after = now + ROUTE_REMOVAL_NOTICE
    else:
        _activate(session, row, now)
    audit.record(session, None, "operator", approver, "allowlist_approve", version,
                 {"activate_after": row.activate_after.isoformat() if row.activate_after else None})
    session.flush()
    return row


def _activate(session: Session, row: AllowlistVersion, now: datetime) -> None:
    session.execute(
        update(AllowlistVersion).where(AllowlistVersion.state == "active").values(state="superseded")
    )
    row.state = "active"
    row.activated_at = now


def activate_due(session: Session, now: datetime) -> list[str]:
    rows = session.execute(
        select(AllowlistVersion)
        .where(AllowlistVersion.state == "draft", AllowlistVersion.approved_at.is_not(None),
               AllowlistVersion.activate_after <= now)
        .order_by(AllowlistVersion.approved_at)
    ).scalars().all()
    for row in rows:
        _activate(session, row, now)
        session.flush()
    return [r.version for r in rows]


def load_active(session: Session) -> AllowlistDoc | None:
    """The active version, hash-checked. None when missing or unreadable (-> policy_unavailable)."""
    row = session.execute(
        select(AllowlistVersion.version, AllowlistVersion.document, AllowlistVersion.sha256).where(
            AllowlistVersion.state == "active"
        )
    ).one_or_none()
    if row is None:
        return None
    try:
        return load_verified(row.version, row.document, row.sha256)
    except PolicyUnavailable:
        return None

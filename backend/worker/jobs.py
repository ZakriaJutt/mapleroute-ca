"""Worker job handlers: verify_binding, schedule_verifications, sweep_outcomes, notify_route_suspended.

Imports only from ``core`` (R-03, R-04). No web-framework module is imported here (R-07).
Each job sets the tenant context from its own row; each binding is checked independently, so a
failure on one never stops the checks on the others.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import alerts, clock, jobs, locks, policy_store, requestlog, tenancy, verification
from core.allowlist import RouteKey
from core.config import CHECK_INTERVAL, FORWARDING_SWEEP_AFTER
from core.crypto import KeyService, decrypt_secret
from core.logging import log_event
from core.models import Binding, ConnectionSecret, Job, ProviderConnection, Route, Tenant
from core.providers import AwsControlReader, AwsTarget, AzureControlReader, AzureTarget


@dataclass
class WorkerServices:
    aws_reader: AwsControlReader
    azure_reader: AzureControlReader
    key_service: KeyService
    pager: alerts.Pager = field(default_factory=alerts.FakePager)


def verify_binding(session: Session, services: WorkerServices, tenant_id: uuid.UUID, binding_id: uuid.UUID,
                   now: datetime) -> verification.Applied:
    """Claim the binding's check lease, read the provider, then lock the binding and apply
    (B1-001, B1-002, B1-003).

    ``now`` is when the job started. At most one check of a binding runs at a time: if another check
    holds the lease, this one is skipped (result ``skipped``, nothing recorded). The reads run under
    the lease but without the binding lock; ``checked_at`` is the end of the reads; the result is
    decided only after the binding lock is held, and the lease is released in the same transaction.
    """
    tenancy.set_tenant(session, tenant_id)
    binding = session.execute(select(Binding).where(Binding.id == binding_id)).scalar_one()
    route = session.get(Route, binding.route_id)
    found_connection = session.get(ProviderConnection, binding.connection_id)
    if route is None or found_connection is None:
        raise LookupError("binding references a missing route or connection")
    connection: ProviderConnection = found_connection
    key = RouteKey(route.provider, route.source_region, route.deployment_class, route.identifier,
                   route.model_version)
    active = policy_store.load_active(session)
    entry = active.entries.get(key.id) if active else None
    version = active.version if active else "none"

    def run() -> verification.CheckOutcome:
        if entry is None or entry.key != key:
            return verification.CheckOutcome("error", ("route_not_listed",))
        if connection.state == "deleted":
            return verification.CheckOutcome("error", ("connection_deleted",))
        if connection.provider != key.provider or connection.source_region != key.source_region:
            return verification.CheckOutcome("config_mismatch", ("connection_region_differs",))
        if key.provider == "aws":
            assert connection.role_arn is not None and connection.external_id is not None
            target = AwsTarget(connection.id, connection.role_arn, connection.external_id, connection.source_region)
            return verification.check_aws(key, entry, target, services.aws_reader)
        secret_row = session.get(ConnectionSecret, connection.id)
        if secret_row is None:
            return verification.CheckOutcome("access_failed", ("no_credential",))
        credential = decrypt_secret(services.key_service, connection.tenant_id, connection.id,
                                    bytes(secret_row.ciphertext), bytes(secret_row.wrapped_data_key))
        assert connection.endpoint_host and connection.resource_group and binding.deployment_name
        target_az = AzureTarget(connection.id, connection.account_ref, connection.endpoint_host,
                                connection.resource_group, binding.deployment_name, credential)
        return verification.check_azure(key, target_az, services.azure_reader, binding.provider_modified_at,
                                         lookback)

    lease = locks.claim_check(session, tenant_id, binding_id, clock.now())
    if lease is None:  # another check of this binding is running: never overlap (B1-003)
        log_event("verification_skipped", tenant_id=tenant_id, binding_id=binding_id, route_id=route.id,
                  status="skipped")
        return verification.Applied("skipped", applied=False)
    try:
        # The activity look-back starts at the last check whose reads completed, never at a failed one.
        lookback = verification.lookback_start(session, binding.id) or binding.last_verified_at
        reads_started = min(now, lease.started_at)
        outcome = verification.guarded(run)
        checked_at = max(now, clock.now())  # coverage ends when the reads end
    except BaseException:
        locks.release_check_detached(session, tenant_id, lease)
        raise
    locks.binding_lock(session, binding.project_id, binding.alias, shared=False)
    binding = session.execute(
        select(Binding).where(Binding.id == binding_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    holds = locks.holds_check(session, lease)  # false if the lease expired and another check took it
    applied = verification.apply_outcome(session, binding, outcome, checked_at, version, services.pager,
                                         reads_started_at=reads_started, holds_lease=holds,
                                         recorded_at=clock.now())
    if holds:
        locks.release_check(session, lease)
    log_event("verification_applied", tenant_id=tenant_id, binding_id=binding_id, route_id=route.id,
              result=outcome.result, reason=outcome.reason, status="applied" if applied.applied else "stale")
    return applied


class CheckInProgress(RuntimeError):
    """A verify_binding job found another check of the binding running; the job is retried later."""


def schedule_verifications(session: Session, now: datetime) -> int:
    """Enqueue one verify_binding per binding per slot (dedupe: binding and scheduled slot)."""
    count = 0
    for tenant_id in session.execute(select(Tenant.id).where(Tenant.state == "active")).scalars().all():
        tenancy.set_tenant(session, tenant_id)
        rows = session.execute(select(Binding.id, Binding.route_id)).all()
        for binding_id, route_id in rows:
            provider = route_id.split(":", 1)[0]
            interval = CHECK_INTERVAL[provider].total_seconds()
            slot = int(now.timestamp() // interval)
            if jobs.enqueue(session, "verify_binding", f"{binding_id}:{slot}", tenant_id=tenant_id,
                            payload={"binding_id": str(binding_id)}):
                count += 1
    return count


def sweep_outcomes(session: Session, now: datetime) -> int:
    total = 0
    for tenant_id in session.execute(select(Tenant.id)).scalars().all():
        tenancy.set_tenant(session, tenant_id)
        total += requestlog.sweep_forwarding(session, now - FORWARDING_SWEEP_AFTER)
    return total


def notify_route_suspended(session: Session, payload: dict[str, Any]) -> int:
    """One alert per affected tenant, de-duplicated (MH-10)."""
    route_id = str(payload["route_id"])
    written = 0
    for tenant_id in policy_store.tenants_on_route(session, route_id):
        tenancy.set_tenant(session, tenant_id)
        dedupe = f"route_suspended:{route_id}:{payload['changed_at']}"
        if alerts.raise_alert(session, tenant_id, "route_suspended", dedupe,
                              {"route_id": route_id, "reason": payload.get("reason")}):
            written += 1
    return written


def run_job(session: Session, services: WorkerServices, job: Job, now: datetime) -> None:
    if job.kind == "verify_binding":
        assert job.tenant_id is not None
        applied = verify_binding(session, services, job.tenant_id, uuid.UUID(job.payload["binding_id"]), now)
        if applied.result == "skipped":
            raise CheckInProgress("check_in_progress")
    elif job.kind == "notify_route_suspended":
        notify_route_suspended(session, job.payload)
    else:
        raise ValueError(f"unknown job kind {job.kind}")

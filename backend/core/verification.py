"""Route verification: read the provider's own answer, decide one outcome, apply it (T-4.1.5, T-4.1.9).

One outcome per kind of mismatch (TRD.md, AD-14):
- ``config_mismatch``: something in the customer's own account. That binding becomes unverified,
  its requests since the last matching check are flagged ``config_changed_window``; the tenant is
  alerted. Other tenants on the same route are untouched.
- ``definition_mismatch``: the provider's shared definition (Bedrock system-defined profile)
  differs. The route's global status becomes ``suspended`` for every tenant.
- ``access_failed`` / ``error``: nothing usable. No status change; the binding ages out. Never a pass.

Ordering (R-01, B1-001, B1-003, B1-012): two rules, not timestamps alone.
1. Serialised: at most one check of a binding runs at a time; it holds the binding's check lease
   (``core.locks``, table ``binding_check_lease``) from before its first provider read until its
   result is recorded. A second check is skipped. A lease past ``CHECK_LEASE`` is taken over.
2. Asymmetric: any mismatch that arrives, whatever its timing and whether or not its check still
   holds the lease, un-verifies the binding (``config_mismatch``) or suspends the route
   (``definition_mismatch``), and moves the binding's ``last_mismatch_at`` to when it was recorded.
   A binding returns to ``verified`` only through a match whose check still holds the lease and
   STARTED after ``last_mismatch_at``.
``checked_at`` is the end of the reads; the result is decided under the binding lock. The window
flagged on a mismatch starts at the earlier of the last verification and the start of the latest
match that started before the mismatch's reads, and has no upper bound. A binding is ``verified``
only when L2 (the customer-side deny policy) was read in place at that same check.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from core import alerts, jobs
from core.allowlist import RouteEntry, RouteKey
from core.config import CANADA, CLASSES, FAILED_CHECKS_ALERT_THRESHOLD
from core.models import Binding, LoggingObservation, ProviderConnection, Route, Verification
from core.providers import (
    AccessDenied,
    AwsControlReader,
    AwsTarget,
    AzureControlReader,
    AzureTarget,
    LoggingAnswer,
)
from core.regions import regions_of_arns

FAILED_RESULTS = frozenset({"access_failed", "error"})
CHANGE_EVENT_KINDS = frozenset(
    {"deployment_write", "deployment_delete", "policy_assignment_change", "policy_exemption_change"}
)
WINDOW_FLAG = "config_changed_window"


@dataclass(frozen=True)
class CheckOutcome:
    result: str
    reasons: tuple[str, ...] = ()
    provider_answer: dict[str, Any] = field(default_factory=dict)
    grade: str = "EG-3"
    logging: LoggingAnswer | None = None
    provider_modified_at: datetime | None = None

    @property
    def reason(self) -> str | None:
        return ",".join(self.reasons) if self.reasons else None


def _logging_reasons(provider: str, log: LoggingAnswer) -> list[str]:
    if log.state != "on":
        return []
    if log.destination_region is None:
        return ["logging_destination_unknown"]
    if log.destination_region not in CANADA[provider]:
        return ["logging_outside_canada"]
    return []


def _log_answer(log: LoggingAnswer) -> dict[str, Any]:
    return {"state": log.state, "destination": log.destination, "destination_region": log.destination_region}


def check_aws(route: RouteKey, entry: RouteEntry, target: AwsTarget, reader: AwsControlReader) -> CheckOutcome:
    config: list[str] = []
    definition: list[str] = []
    answer: dict[str, Any] = {}
    if route.deployment_class == "geo_ca":
        profile = reader.get_inference_profile(target, route.identifier)
        regions = regions_of_arns(profile.model_arns)
        answer["profile"] = {"id": profile.profile_id, "type": profile.profile_type, "regions": sorted(regions)}
        if regions != entry.destinations:
            (definition if profile.profile_type == "SYSTEM_DEFINED" else config).append("destinations_differ")
        grade = "EG-3"
    else:
        model = reader.get_foundation_model(target, route.identifier)
        answer["model"] = {"id": model.model_id, "exists": model.exists, "enabled": model.enabled}
        if not (model.exists and model.enabled):
            config.append("model_not_enabled")
        grade = "EG-4"  # existence is EG-3; in-region processing rests on the provider's statement
    role = reader.read_role_policy(target)
    answer["role"] = {
        "us_profile_denied": role.us_profile_denied,
        "us_east_model_denied": role.us_east_model_denied,
        "broader_than_template": role.broader_than_template,
    }
    if role.broader_than_template:
        config.append("role_too_broad")
    if not (role.us_profile_denied and role.us_east_model_denied):
        config.append("l2_missing")
    log = reader.get_invocation_logging(target)
    answer["logging"] = _log_answer(log)
    config.extend(_logging_reasons("aws", log))
    if definition:
        return CheckOutcome("definition_mismatch", tuple(definition), answer, grade, log)
    if config:
        return CheckOutcome("config_mismatch", tuple(config), answer, grade, log)
    return CheckOutcome("match", (), answer, grade, log)


def check_azure(route: RouteKey, target: AzureTarget, reader: AzureControlReader,
                previous_modified_at: datetime | None, previous_check_at: datetime | None) -> CheckOutcome:
    config: list[str] = []
    dep = reader.get_deployment(target)
    answer: dict[str, Any] = {
        "deployment": {
            "name": target.deployment_name, "location": dep.location, "sku_name": dep.sku_name,
            "model": dep.model_name, "version": dep.model_version,
            "created_at": dep.created_at.isoformat(), "modified_at": dep.modified_at.isoformat(),
        }
    }
    # Read from Azure, never inferred from the deployment or host name.
    if dep.location not in CANADA["azure"] or dep.location != route.source_region:
        config.append("location_not_eligible")
    if dep.sku_name not in CLASSES["azure"] or dep.sku_name != route.deployment_class:
        config.append("sku_not_eligible")
    if dep.model_name != route.identifier or dep.model_version != route.model_version:
        config.append("model_differs")
    if previous_modified_at is not None and dep.modified_at != previous_modified_at:
        config.append("deployment_recreated")
    policy = reader.get_policy_state(target)
    answer["policy"] = {
        "deny_present": policy.deny_assignment_present, "enforced": policy.enforced,
        "exempted": policy.exempted, "assignment_ids": list(policy.assignment_ids),
    }
    if not (policy.deny_assignment_present and policy.enforced and not policy.exempted):
        config.append("l2_missing")
    if previous_check_at is not None:
        events = [e for e in reader.activity_since(target, previous_check_at) if e.kind in CHANGE_EVENT_KINDS]
        answer["activity"] = sorted({e.kind for e in events})
        if events:
            config.append("activity_change")
    log = reader.get_diagnostic_logging(target)
    answer["logging"] = _log_answer(log)
    config.extend(_logging_reasons("azure", log))
    result = "config_mismatch" if config else "match"
    return CheckOutcome(result, tuple(config), answer, "EG-3", log, dep.modified_at)


def guarded(fn: Callable[[], CheckOutcome]) -> CheckOutcome:
    """Run a check; no access or any failure is recorded, never treated as a pass."""
    try:
        return fn()
    except AccessDenied:
        return CheckOutcome("access_failed", ("access_denied",))
    except Exception as exc:  # noqa: BLE001 - every failure must become a recorded non-pass
        return CheckOutcome("error", (type(exc).__name__,))


@dataclass(frozen=True)
class Applied:
    result: str
    applied: bool
    flagged_requests: int = 0
    route_suspended: bool = False
    alert_raised: bool = False


def apply_outcome(session: Session, binding: Binding, outcome: CheckOutcome, checked_at: datetime,
                  allowlist_version: str, pager: alerts.Pager, *, reads_started_at: datetime | None = None,
                  holds_lease: bool, recorded_at: datetime | None = None) -> Applied:
    """Record the verification row and apply its effect. Caller holds the tenant context, the
    binding advisory lock and the binding row lock (SELECT ... FOR UPDATE).

    ``reads_started_at``..``checked_at`` is the interval in which the provider was read;
    ``holds_lease`` says whether this check still holds the binding's check lease (core.locks);
    ``recorded_at`` is when the result arrives (defaults to ``checked_at``).

    Asymmetric rule (B1-003): a mismatch always applies, whatever its timing or lease, and moves the
    binding's mismatch fence (``last_mismatch_at``) to when it was recorded. A match applies only if
    this check still holds the lease and started after the fence.
    """
    started = reads_started_at or checked_at
    recorded = max(recorded_at or checked_at, checked_at)
    answer = {**outcome.provider_answer,
              "coverage": {"reads_started_at": started.isoformat(), "reads_ended_at": checked_at.isoformat()}}
    session.add(
        Verification(
            tenant_id=binding.tenant_id, binding_id=binding.id, route_id=binding.route_id, checked_at=checked_at,
            started_at=started, result=outcome.result, reason=outcome.reason, provider_answer=answer,
            allowlist_version=allowlist_version, grade=outcome.grade,
        )
    )
    if outcome.logging is not None:
        session.add(
            LoggingObservation(
                tenant_id=binding.tenant_id, connection_id=binding.connection_id, observed_at=checked_at,
                state=outcome.logging.state, destination=outcome.logging.destination,
                destination_region=outcome.logging.destination_region,
            )
        )
    session.flush()
    if binding.last_checked_at is None or checked_at > binding.last_checked_at:
        binding.last_checked_at = checked_at
    fence = binding.last_mismatch_at
    connection = session.get(ProviderConnection, binding.connection_id)
    if outcome.result == "match":
        if not holds_lease or (fence is not None and started <= fence):
            session.flush()
            return Applied("match", applied=False)  # recorded, never applied (R-01, B1-003)
        binding.status = "verified"
        # Validity and the next window start from the start of the reads (conservative).
        binding.last_verified_at = started
        binding.l2_confirmed_at = started
        binding.provider_modified_at = outcome.provider_modified_at
        if connection is not None and connection.state != "deleted":
            connection.state, connection.last_read_ok_at = "connected", checked_at
        session.flush()
        return Applied("match", True)
    if outcome.result in ("config_mismatch", "definition_mismatch"):
        binding.last_mismatch_at = recorded if fence is None else max(fence, recorded)
    if outcome.result == "config_mismatch":
        # Window start: the start of the latest match whose reads started before this check's reads.
        starts = [t for t in (prior_match_observation(session, binding.id, started), binding.last_verified_at)
                  if t is not None]
        since = min(starts) if starts else None
        binding.status = "unverified"  # always: a mismatch is never discarded (B1-003)
        if holds_lease and outcome.provider_modified_at is not None:
            binding.provider_modified_at = outcome.provider_modified_at  # baseline for the next check
        session.flush()
        flagged = flag_window(session, binding, since) if since is not None else 0
        raised = alerts.raise_alert(
            session, binding.tenant_id, "config_mismatch", f"config_mismatch:{binding.id}:{since}",
            {"binding_id": str(binding.id), "route_id": binding.route_id, "reason": outcome.reason,
             "flagged_requests": flagged},
        )
        return Applied("config_mismatch", True, flagged_requests=flagged, alert_raised=raised)
    if outcome.result == "definition_mismatch":
        suspended = suspend_route(session, binding.route_id, checked_at, outcome.reason or "destinations_differ")
        if suspended:
            jobs.enqueue(session, "notify_route_suspended", f"{binding.route_id}:{checked_at.isoformat()}",
                         payload={"route_id": binding.route_id, "changed_at": checked_at.isoformat(),
                                  "reason": outcome.reason})
            pager.page_founder("route_suspended", {"route_id": binding.route_id, "reason": outcome.reason})
        session.flush()
        return Applied("definition_mismatch", True, route_suspended=suspended)
    # access_failed / error: no status change; count consecutive failed checks.
    if outcome.result == "access_failed" and connection is not None and connection.state != "deleted":
        connection.state = "access_failed"
    session.flush()
    recent = session.execute(
        select(Verification.result, Verification.checked_at)
        .where(Verification.binding_id == binding.id)
        .order_by(Verification.checked_at.desc())
        .limit(FAILED_CHECKS_ALERT_THRESHOLD)
    ).all()
    raised = False
    if len(recent) == FAILED_CHECKS_ALERT_THRESHOLD and all(r.result in FAILED_RESULTS for r in recent):
        payload = {"binding_id": str(binding.id), "route_id": binding.route_id,
                   "failed_checks": FAILED_CHECKS_ALERT_THRESHOLD,
                   "last_matching_check": binding.last_verified_at.isoformat() if binding.last_verified_at else None}
        raised = alerts.raise_alert(
            session, binding.tenant_id, "access_failed", f"access_failed:{binding.id}:{binding.last_verified_at}",
            payload,
        )
        if raised:
            pager.page_founder("access_failed", payload)
    return Applied(outcome.result, True, alert_raised=raised)


def flag_window(session: Session, binding: Binding, since: datetime) -> int:
    """Flag every served request since the start of the last matching check's reads (idempotent).

    No upper bound (B1-001): requests served while the mismatching reads ran, or after them and
    before this commit, are included; the binding lock keeps new decisions out until commit.
    """
    result = session.execute(
        text(
            "UPDATE request_log SET flags = array_append(flags, :flag) "
            "WHERE project_id = :p AND alias = :a AND route_id = :r AND state <> 'rejected' "
            "AND received_at >= :since AND NOT (:flag = ANY(flags))"
        ),
        {"flag": WINDOW_FLAG, "p": binding.project_id, "a": binding.alias, "r": binding.route_id,
         "since": since},
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def suspend_route(session: Session, route_id: str, checked_at: datetime, reason: str) -> bool:
    """Suspend for every tenant. A mismatch always suspends an active route, however late it arrives;
    only resuming is guarded (newer match, operator only)."""
    result = session.execute(
        update(Route)
        .where(Route.id == route_id, Route.global_status == "active")
        .values(global_status="suspended", status_reason=reason, status_changed_at=checked_at,
                status_checked_at=func.greatest(func.coalesce(Route.status_checked_at, checked_at), checked_at))
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def resume_route(session: Session, route_id: str, operator_id: uuid.UUID, now: datetime) -> None:
    """Operator resume. The database trigger refuses it unless a newer match exists (F-011)."""
    session.execute(
        update(Route).where(Route.id == route_id, Route.global_status == "suspended")
        .values(global_status="active", status_reason="operator_resume", status_changed_at=now)
    )
    session.flush()


COMPLETED_RESULTS = ("match", "config_mismatch", "definition_mismatch")


def lookback_start(session: Session, binding_id: uuid.UUID) -> datetime | None:
    """Start of the reads of the last check whose reads completed (B1-002).

    A failed check (``access_failed``/``error``) never moves the activity look-back forward: the
    period it did not read stays open until a completed check covers it.
    """
    row = session.execute(
        select(Verification.started_at, Verification.checked_at)
        .where(Verification.binding_id == binding_id, Verification.result.in_(COMPLETED_RESULTS))
        .order_by(Verification.checked_at.desc()).limit(1)
    ).first()
    if row is None:
        return None
    started: datetime | None = row[0]
    checked: datetime = row[1]
    return started or checked


def prior_match_observation(session: Session, binding_id: uuid.UUID, before: datetime) -> datetime | None:
    """Start of the reads of the latest matching check whose reads started before ``before``."""
    latest: datetime | None = session.execute(
        select(func.max(Verification.started_at))
        .where(Verification.binding_id == binding_id, Verification.result == "match",
               Verification.started_at < before)
    ).scalar_one_or_none()
    return latest

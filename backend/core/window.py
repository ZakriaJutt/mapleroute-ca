"""Azure route-line figures for the report (TRD.md "Residual window on Azure", MH-04).

Computed from the verification rows and the request log only. The full report generator
(T-5.1.2) is not built in B1; this is the line's data and wording, so IT-21 can check it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Binding, RequestLog, Verification
from core.verification import FAILED_RESULTS, WINDOW_FLAG


@dataclass(frozen=True)
class AzureLine:
    matching_checks: int
    failed_checks: int
    mismatched_checks: int
    longest_served_since_match: timedelta
    flagged_requests: int
    grade: str = "EG-3"

    def text(self) -> str:
        minutes = self.longest_served_since_match.total_seconds() / 60
        return (
            f"Configuration matched at each check: {self.matching_checks} matching checks, "
            f"{self.failed_checks} failed checks, {self.mismatched_checks} mismatches. "
            f"Longest time requests were served since a matching check: {minutes:.0f} minutes (limit 60). "
            f"Requests flagged {WINDOW_FLAG}: {self.flagged_requests}. [{self.grade}]"
        )


def azure_line(session: Session, binding_id: uuid.UUID, start: datetime, end: datetime) -> AzureLine:
    binding = session.get(Binding, binding_id)
    if binding is None:
        raise LookupError("binding not found")
    results = session.execute(
        select(Verification.result, func.count())
        .where(Verification.binding_id == binding_id, Verification.checked_at >= start,
               Verification.checked_at < end)
        .group_by(Verification.result)
    ).all()
    counts = {r: int(n) for r, n in results}
    served = (
        RequestLog.project_id == binding.project_id,
        RequestLog.alias == binding.alias,
        RequestLog.route_id == binding.route_id,
        RequestLog.state != "rejected",
        RequestLog.received_at >= start,
        RequestLog.received_at < end,
    )
    longest = session.execute(
        select(func.max(RequestLog.received_at - RequestLog.binding_verified_at)).where(*served)
    ).scalar()
    flagged = session.execute(
        select(func.count()).where(*served, RequestLog.flags.any(WINDOW_FLAG))  # type: ignore[arg-type]
    ).scalar_one()
    return AzureLine(
        matching_checks=counts.get("match", 0),
        failed_checks=sum(n for r, n in counts.items() if r in FAILED_RESULTS),
        mismatched_checks=counts.get("config_mismatch", 0) + counts.get("definition_mismatch", 0),
        longest_served_since_match=longest if isinstance(longest, timedelta) else timedelta(0),
        flagged_requests=int(flagged),
    )

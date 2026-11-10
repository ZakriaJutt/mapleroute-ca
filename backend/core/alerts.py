"""Alert rows, de-duplicated per tenant, and the founder pager interface (MH-10).

Payloads carry route, code, counts and IDs only; never content or secrets. Delivery by email and
paging is behind ``Pager``; B1 has only ``FakePager``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.models import Alert


class Pager(Protocol):
    def page_founder(self, kind: str, payload: dict[str, Any]) -> None: ...


@dataclass
class FakePager:
    pages: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def page_founder(self, kind: str, payload: dict[str, Any]) -> None:
        self.pages.append((kind, payload))


def raise_alert(session: Session, tenant_id: uuid.UUID, kind: str, dedupe_key: str,
                payload: dict[str, Any]) -> bool:
    """Insert once per (tenant, dedupe_key). Returns True when a new alert row was written."""
    result = session.execute(
        insert(Alert)
        .values(tenant_id=tenant_id, kind=kind, dedupe_key=dedupe_key, payload=payload)
        .on_conflict_do_nothing(constraint="uq_alert_dedupe")
        .returning(Alert.id)
    )
    return result.first() is not None

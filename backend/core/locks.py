"""Advisory lock per binding (B1-001, B1-003).

The worker holds it exclusively while it decides and applies a verification result; the gateway
holds it shared while it evaluates ``forwardable`` and commits the log row. So no request can be
decided on a binding's old status while a mismatch for it is being applied, and every request
committed before the mismatch is visible to the window flagging. Advisory locks need no table
privilege, so the gateway does not need UPDATE rights on ``binding`` to take it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def binding_lock(session: Session, project_id: uuid.UUID, alias: str, *, shared: bool) -> None:
    fn = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    session.execute(text(f"SELECT {fn}(hashtextextended(:k, 0))"), {"k": f"binding:{project_id}:{alias}"})

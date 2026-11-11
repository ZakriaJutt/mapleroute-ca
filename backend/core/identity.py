"""Console identities and server-side sessions, shared by every identity provider (B2, T-4.1.1).

An identity provider -- the local provider in ``core.local_idp`` today, OIDC later (deferred,
TRD.md AD-13) -- hands an ``Identity`` to ``sign_in``. The user is found by (provider, subject),
never by email (ASVS 6.8.1); a new identity creates a user. A session is an opaque 256-bit token in
a ``__Host-`` cookie; only its SHA-256 is stored (7.2.1-7.2.3). The anti-forgery token is derived
from the session token, so it changes whenever the session token does.

No web-framework imports. All times come from ``core.clock``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.orm import Session

from core.config import OPERATOR_REAUTH, SESSION_ABSOLUTE, SESSION_IDLE
from core.models import ConsoleSession, UserAccount

# amr values that show a second factor (RFC 8176). The local provider always sends pwd + otp.
MFA_AMR = frozenset({"mfa", "otp", "hwk", "swk", "fpt"})


@dataclass(frozen=True)
class Identity:
    idp: str
    subject: str
    email: str  # verified by the provider; the local provider verified it at enrolment
    display_name: str
    amr: tuple[str, ...]
    auth_time: datetime


@dataclass(frozen=True)
class Membership:
    tenant_id: uuid.UUID
    role: str
    require_mfa_claim: bool


@dataclass(frozen=True)
class SessionInfo:
    session_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str | None
    is_operator: bool
    amr: tuple[str, ...]
    auth_time: datetime
    csrf_token: str


@dataclass(frozen=True)
class NewSession:
    token: str  # cookie value; never stored or logged
    csrf_token: str
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str | None


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def csrf_for(token: str) -> str:
    return hmac.new(token.encode("ascii"), b"mapleroute-csrf-v1", hashlib.sha256).hexdigest()


def csrf_matches(token: str, presented: str | None) -> bool:
    return presented is not None and hmac.compare_digest(csrf_for(token), presented)


def has_mfa(amr: tuple[str, ...] | list[str]) -> bool:
    return bool(MFA_AMR.intersection(amr))


def recent_auth(auth_time: datetime | None, now: datetime) -> bool:
    return auth_time is not None and now - auth_time <= OPERATOR_REAUTH


def memberships(s: Session, user_id: uuid.UUID) -> list[Membership]:
    rows = s.execute(text("SELECT tenant_id, role, require_mfa_claim FROM memberships_for_user(:u)"),
                     {"u": user_id}).all()
    return [Membership(r.tenant_id, r.role, r.require_mfa_claim) for r in rows]


def membership_in(s: Session, user_id: uuid.UUID, tenant_id: uuid.UUID) -> Membership | None:
    return next((m for m in memberships(s, user_id) if m.tenant_id == tenant_id), None)


def user_for(s: Session, identity: Identity) -> uuid.UUID:
    """The user for (provider, subject); created on first sign-in. Email is stored, never matched."""
    found = s.execute(select(UserAccount.id).where(UserAccount.idp == identity.idp,
                                                   UserAccount.idp_subject == identity.subject)).scalar_one_or_none()
    if found is not None:
        return found
    new_id = uuid.uuid4()
    s.execute(insert(UserAccount).values(id=new_id, idp=identity.idp, idp_subject=identity.subject,
                                         email=identity.email, display_name=identity.display_name))
    return new_id


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def open_session(s: Session, user_id: uuid.UUID, identity: Identity, tenant_id: uuid.UUID | None,
                 role: str | None, now: datetime) -> NewSession:
    """A new token at every sign-in (7.2.4); the absolute lifetime counts from now."""
    token = _new_token()
    s.execute(insert(ConsoleSession).values(
        id=uuid.uuid4(), user_id=user_id, tenant_id=tenant_id, token_hash=token_hash(token), idp=identity.idp,
        amr=list(identity.amr), auth_time=identity.auth_time, expires_at=now + SESSION_ABSOLUTE, last_seen_at=now))
    return NewSession(token, csrf_for(token), user_id, tenant_id, role)


def resolve(s: Session, token: str | None, now: datetime) -> SessionInfo | None:
    """The live session for ``token``, or None. Expired sessions are deleted (7.3.1, 7.3.2, 7.4.1).
    The role is re-read from membership on every request, so a removed member loses access at once."""
    if not token or len(token) > 128:
        return None
    try:
        th = token_hash(token)
    except UnicodeEncodeError:
        return None
    row = s.execute(select(ConsoleSession).where(ConsoleSession.token_hash == th)).scalar_one_or_none()
    if row is None:
        return None
    if now >= row.expires_at or now - row.last_seen_at >= SESSION_IDLE:
        s.execute(delete(ConsoleSession).where(ConsoleSession.id == row.id))
        return None
    user = s.execute(select(UserAccount.is_operator).where(UserAccount.id == row.user_id)).scalar_one()
    role: str | None = None
    tenant_id = row.tenant_id
    if tenant_id is not None:
        m = membership_in(s, row.user_id, tenant_id)
        if m is None or (m.require_mfa_claim and not has_mfa(row.amr)):
            tenant_id = None
        else:
            role = m.role
    s.execute(update(ConsoleSession).where(ConsoleSession.id == row.id).values(last_seen_at=now))
    return SessionInfo(row.id, row.user_id, tenant_id, role, bool(user), tuple(row.amr), row.auth_time,
                       csrf_for(token))


def rotate(s: Session, session_id: uuid.UUID, *, tenant_id: uuid.UUID | None = None, set_tenant: bool = False,
           auth_time: datetime | None = None, amr: tuple[str, ...] | None = None) -> tuple[str, str]:
    """Replace the token of a live session (re-authentication, tenant switch); the old token stops working."""
    token = _new_token()
    values: dict[str, object] = {"token_hash": token_hash(token)}
    if set_tenant:
        values["tenant_id"] = tenant_id
    if auth_time is not None:
        values["auth_time"] = auth_time
    if amr is not None:
        values["amr"] = list(amr)
    s.execute(update(ConsoleSession).where(ConsoleSession.id == session_id).values(**values))
    return token, csrf_for(token)


def end_session(s: Session, session_id: uuid.UUID) -> None:
    s.execute(delete(ConsoleSession).where(ConsoleSession.id == session_id))


def end_all_sessions(s: Session, user_id: uuid.UUID, tenant_id: uuid.UUID | None = None) -> int:
    stmt = delete(ConsoleSession).where(ConsoleSession.user_id == user_id)
    if tenant_id is not None:
        stmt = stmt.where(ConsoleSession.tenant_id == tenant_id)
    return int(s.execute(stmt).rowcount)  # type: ignore[attr-defined]

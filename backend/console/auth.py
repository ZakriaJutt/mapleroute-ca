"""Console sign-in, sessions, tenants and members (B2: T-4.1.1, T-4.1.2; S-01, S-02, S-13, S-15).

The local identity provider (password + TOTP, ``core.local_idp``) is the only provider built; OIDC
is deferred (TRD.md AD-13) and would hand the same ``Identity`` to the same ``_complete_sign_in``.

Session cookie ``__Host-mr_session``: Secure, HttpOnly, SameSite=Lax, Path=/ (ASVS 3.3.1-3.3.4).
Every unsafe request carrying a session needs the ``X-CSRF-Token`` header, and a present ``Origin``
must be the console's own (3.5.1, 3.5.3). Sign-in requests are rate limited per client address and
per email, and a credential locks after repeated failures (6.3.1).
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core import audit, clock, identity, local_idp, permissions, tenancy
from core.config import INVITE_TTL, SESSION_COOKIE
from core.crypto import KeyService
from core.identity import Identity, NewSession, has_mfa, token_hash
from core.logging import log_event
from core.mail import Mail, Mailer, MailUnavailable
from core.models import Membership, UserAccount
from core.passwords import PasswordRejected
from core.ratelimit import SlidingWindow
from core.secretvalue import SecretValue

UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str | None
    is_operator: bool = False
    amr: tuple[str, ...] = ()
    auth_time: datetime | None = None
    session_id: uuid.UUID | None = None


class Authenticator(Protocol):
    def __call__(self, request: Request) -> Principal | None: ...


@dataclass
class SignInLimits:
    """Anti-automation windows (ASVS 6.3.1, 2.4.1). In process memory; the lockout is in the database."""

    per_address: SlidingWindow = field(default_factory=lambda: SlidingWindow(30, timedelta(minutes=1)))
    per_email: SlidingWindow = field(default_factory=lambda: SlidingWindow(10, timedelta(minutes=15)))
    enrol_per_email: SlidingWindow = field(default_factory=lambda: SlidingWindow(3, timedelta(minutes=15)))


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class SessionAuthenticator:
    """The production authenticator: the session cookie, checked in the database on every request."""

    def __init__(self, factory: sessionmaker[Session], allowed_origin: str) -> None:
        self.factory = factory
        self.allowed_origin = allowed_origin

    def __call__(self, request: Request) -> Principal | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        with self.factory.begin() as s:
            info = identity.resolve(s, token, clock.now())
        if info is None:
            return None
        if request.method in UNSAFE:
            origin = request.headers.get("origin")
            if origin is not None and origin != self.allowed_origin:
                raise HTTPException(403, "cross-origin request refused")
            if not identity.csrf_matches(token, request.headers.get("x-csrf-token")):
                raise HTTPException(403, "anti-forgery token missing or wrong")
        return Principal(info.user_id, info.tenant_id, info.role, info.is_operator, info.amr, info.auth_time,
                         info.session_id)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, path="/", secure=True, httponly=True, samesite="lax")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


FORWARDING_HEADERS = ("forwarded", "x-forwarded-for", "x-real-ip")


def client_key(request: Request, trusted_proxies: frozenset[str]) -> str:
    """The address a rate-limit window is keyed on (B2-S02).

    With no trusted proxy configured (the default), console/main.py runs uvicorn with
    ``proxy_headers=False``, so ``request.client`` is the direct peer. Because the app may also be
    served by a server that rewrites the client from forwarding headers, a request that carries such a
    header from an untrusted source shares one window, whatever the header says: rotating it cannot
    buy new windows. With trusted proxies configured, uvicorn rewrites the client only for those peers
    (``forwarded_allow_ips``) and the rewritten address is used.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxies:
        return peer
    if any(h in request.headers for h in FORWARDING_HEADERS):
        return "untrusted-forwarded"
    return peer


def _str(body: dict[str, Any], key: str, max_len: int = 256) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise HTTPException(422, f"{key} required")
    return value


def register(app: FastAPI, *, factory: sessionmaker[Session], key_service: KeyService, mailer: Mailer,
             limits: SignInLimits, public_base_url: str, principal: Callable[[Request], Principal],
             trusted_proxies: frozenset[str] = frozenset()) -> None:
    """Add the /auth routes, onboarding and member management to the console app."""

    def _client(request: Request) -> str:
        return client_key(request, trusted_proxies)

    def audit_after(tenant_id: uuid.UUID | None, user_id: uuid.UUID, action: str, detail: dict[str, Any]) -> None:
        """Audit an action that has already been committed (B2-S01). Tenant context is set for the
        insert; a failure is retried once, then logged, and never undoes the committed action."""
        for attempt in (1, 2):
            try:
                with factory.begin() as s:
                    if tenant_id is not None:
                        tenancy.set_tenant(s, tenant_id)
                    audit.record(s, tenant_id, "user", user_id, action, str(user_id), detail)
                return
            except SQLAlchemyError:
                if attempt == 2:
                    log_event("audit_failed", reason=action, tenant_id=tenant_id)

    def session_response(body: dict[str, Any], new: NewSession | tuple[str, str], status: int = 200) -> JSONResponse:
        token, csrf = (new.token, new.csrf_token) if isinstance(new, NewSession) else new
        resp = JSONResponse({**body, "csrf_token": csrf}, status_code=status)
        set_session_cookie(resp, token)
        return resp

    def signed_in(request: Request) -> Principal:
        p = principal(request)
        if p.session_id is None:
            raise HTTPException(401, "sign-in required")
        return p

    def owner(request: Request, action: str) -> Principal:
        p = principal(request)
        if p.tenant_id is None or p.role is None:
            raise HTTPException(404, "not found")
        if not permissions.allowed(p.role, action):
            raise HTTPException(403, "role not permitted")
        return p

    # ------------------------------------------------------------------ enrolment (local provider)
    @app.post("/auth/local/enrol", status_code=202)
    def enrol(body: dict[str, Any], request: Request) -> dict[str, str]:
        now = clock.now()
        email = local_idp.normalise_email(body.get("email"))
        if email is None:
            raise HTTPException(422, "a valid email address is required")
        if not limits.per_address.allow(f"enrol:{_client(request)}", now) or \
                not limits.enrol_per_email.allow(email, now):
            raise HTTPException(429, "too many requests; wait and try again")
        try:
            with factory.begin() as s:
                local_idp.request_enrolment(s, mailer, email, now, public_base_url)
        except MailUnavailable as exc:
            raise HTTPException(503, "mail is unavailable; try again later") from exc
        # Same answer whether or not the address is enrolled (6.3.8).
        return {"status": "If this address can enrol, a link is on its way."}

    @app.post("/auth/local/enrol/complete", status_code=201)
    def enrol_complete(body: dict[str, Any], request: Request) -> JSONResponse:
        now = clock.now()
        if not limits.per_address.allow(f"enrol-complete:{_client(request)}", now):
            raise HTTPException(429, "too many requests; wait and try again")
        token, name = _str(body, "token"), _str(body, "display_name", 200)
        password = SecretValue(_str(body, "password", 1024))
        try:
            with factory.begin() as s:
                done = local_idp.complete_enrolment(s, key_service, token, name, password, now)
        except (local_idp.LinkInvalid, IntegrityError) as exc:
            # IntegrityError: a concurrent completion for the same address won the unique credential.
            raise HTTPException(400, "this link is not valid; it may have expired or been used") from exc
        except PasswordRejected as exc:
            raise HTTPException(422, str(exc)) from exc
        # The seed is shown once, for the authenticator app; it is never shown again.
        return JSONResponse({"totp_secret": done.totp_seed.reveal(), "otpauth_uri": done.provisioning_uri.reveal(),
                             "next": "sign-in"}, status_code=201, headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ sign-in
    def _complete_sign_in(request: Request, ident: Identity, wanted: uuid.UUID | None) -> JSONResponse:
        """Shared by every identity provider: user by (provider, subject), tenant by membership only."""
        now = clock.now()
        with factory.begin() as s:
            user_id = identity.user_for(s, ident)
            ms = identity.memberships(s, user_id)
            usable = [m for m in ms if not m.require_mfa_claim or has_mfa(ident.amr)]
            chosen = next((m for m in usable if m.tenant_id == wanted), None) if wanted else \
                (usable[0] if len(usable) == 1 else None)
            old = request.cookies.get(SESSION_COOKIE)
            if old:  # 7.2.4: the previous session ends at a new sign-in
                s.execute(text("DELETE FROM session WHERE token_hash = :h"), {"h": token_hash(old)})
            new = identity.open_session(s, user_id, ident, chosen.tenant_id if chosen else None,
                                        chosen.role if chosen else None, now)
            if chosen:
                tenancy.set_tenant(s, chosen.tenant_id)
            audit.record(s, chosen.tenant_id if chosen else None, "user", user_id, "sign_in", str(user_id),
                         {"idp": ident.idp})
        log_event("sign_in", result="ok", tenant_id=new.tenant_id)
        nxt = "app" if chosen else ("choose_tenant" if usable else "onboarding")
        return session_response({"user_id": str(user_id), "tenant_id": str(new.tenant_id) if new.tenant_id else None,
                                 "role": new.role, "next": nxt,
                                 "tenants": [{"tenant_id": str(m.tenant_id), "role": m.role} for m in usable]}, new)

    @app.post("/auth/local/sign-in")
    def local_sign_in(body: dict[str, Any], request: Request) -> JSONResponse:
        now = clock.now()
        email = local_idp.normalise_email(body.get("email"))
        password, code = body.get("password"), body.get("code")
        if email is None or not isinstance(password, str) or not isinstance(code, str) or len(password) > 1024:
            raise HTTPException(422, "email, password and code required")
        if not limits.per_address.allow(f"sign-in:{_client(request)}", now) or not limits.per_email.allow(email, now):
            log_event("sign_in", result="rate_limited")
            raise HTTPException(429, "too many sign-in attempts; wait and try again")
        wanted: uuid.UUID | None = None
        if body.get("tenant_id"):
            try:
                wanted = uuid.UUID(str(body["tenant_id"]))
            except ValueError as exc:
                raise HTTPException(422, "tenant_id must be a UUID") from exc
        with factory.begin() as s:  # commits the failure counter too
            ident = local_idp.authenticate(s, key_service, email, SecretValue(password), code, now)
            if ident is None:
                audit.record(s, None, "user", None, "sign_in_failed", "local", {"idp": "local"})
        if ident is None:
            log_event("sign_in", result="refused")
            raise HTTPException(401, "email, password or code is not correct, or sign-in is locked for a while")
        return _complete_sign_in(request, ident, wanted)

    @app.get("/auth/session")
    def current(request: Request) -> JSONResponse:
        p = signed_in(request)
        token = request.cookies.get(SESSION_COOKIE, "")
        return JSONResponse({"user_id": str(p.user_id), "tenant_id": str(p.tenant_id) if p.tenant_id else None,
                             "role": p.role, "is_operator": p.is_operator, "amr": list(p.amr),
                             "auth_time": p.auth_time.isoformat() if p.auth_time else None,
                             "csrf_token": identity.csrf_for(token)}, headers={"Cache-Control": "no-store"})

    @app.post("/auth/logout", status_code=204)
    def logout(request: Request) -> Response:
        p = signed_in(request)
        assert p.session_id is not None
        # 7.4.1: the session is deleted and committed first; the audit event follows and cannot undo it.
        with factory.begin() as s:
            identity.end_session(s, p.session_id)
        audit_after(p.tenant_id, p.user_id, "sign_out", {})
        resp = Response(status_code=204)
        clear_session_cookie(resp)
        return resp

    @app.post("/auth/logout-all", status_code=204)
    def logout_all(request: Request) -> Response:
        p = signed_in(request)
        with factory.begin() as s:
            ended = identity.end_all_sessions(s, p.user_id)
        audit_after(p.tenant_id, p.user_id, "sign_out_all", {"sessions_ended": ended})
        resp = Response(status_code=204)
        clear_session_cookie(resp)
        return resp

    @app.post("/auth/reauth")
    def reauth(body: dict[str, Any], request: Request) -> JSONResponse:
        """Fresh password + code before approve, suspend or resume (7.5.3); a new token (7.2.4)."""
        p = signed_in(request)
        assert p.session_id is not None
        now = clock.now()
        password, code = _str(body, "password", 1024), _str(body, "code", 16)
        if not limits.per_email.allow(f"reauth:{p.user_id}", now):
            raise HTTPException(429, "too many attempts; wait and try again")
        with factory.begin() as s:
            ident = local_idp.reauthenticate(s, key_service, p.user_id, SecretValue(password), code, now)
            new = identity.rotate(s, p.session_id, auth_time=now, amr=ident.amr) if ident else None
        if new is None:
            raise HTTPException(401, "password or code is not correct")
        return session_response({"auth_time": now.isoformat()}, new)

    @app.post("/auth/tenant")
    def switch_tenant(body: dict[str, Any], request: Request) -> JSONResponse:
        p = signed_in(request)
        assert p.session_id is not None
        try:
            tid = uuid.UUID(str(body.get("tenant_id")))
        except ValueError as exc:
            raise HTTPException(422, "tenant_id must be a UUID") from exc
        with factory.begin() as s:
            m = identity.membership_in(s, p.user_id, tid)
            if m is None or (m.require_mfa_claim and not has_mfa(p.amr)):
                raise HTTPException(404, "not found")
            new = identity.rotate(s, p.session_id, tenant_id=tid, set_tenant=True)
        return session_response({"tenant_id": str(tid), "role": m.role}, new)

    # ------------------------------------------------------------------ onboarding and invitations
    @app.post("/api/onboarding", status_code=201)
    def onboarding(body: dict[str, Any], request: Request) -> JSONResponse:
        """S-02: a signed-in user creates a new organisation and becomes its owner."""
        p = signed_in(request)
        assert p.session_id is not None
        name = _str(body, "legal_name", 200)
        tid = uuid.uuid4()
        with factory.begin() as s:
            s.execute(text("INSERT INTO tenant (id, legal_name) VALUES (:id, :n)"), {"id": tid, "n": name})
            tenancy.set_tenant(s, tid)
            s.execute(insert(Membership).values(id=uuid.uuid4(), tenant_id=tid, user_id=p.user_id, role="owner"))
            audit.record(s, tid, "user", p.user_id, "tenant_create", str(tid))
            new = identity.rotate(s, p.session_id, tenant_id=tid, set_tenant=True)
        return session_response({"tenant_id": str(tid), "role": "owner"}, new, status=201)

    @app.post("/auth/invitations/accept")
    def accept(body: dict[str, Any], request: Request) -> JSONResponse:
        """Accepted only by a signed-in identity whose verified email equals the invited email."""
        p = signed_in(request)
        assert p.session_id is not None
        raw = _str(body, "token")
        now = clock.now()
        with factory.begin() as s:
            row = s.execute(text("SELECT tenant_id, role FROM accept_invitation(:h, :u, :now)"),
                            {"h": token_hash(raw), "u": p.user_id, "now": now}).first()
            if row is None:
                new = None
            else:
                tenancy.set_tenant(s, row.tenant_id)
                audit.record(s, row.tenant_id, "user", p.user_id, "member_join", str(p.user_id), {"role": row.role})
                new = identity.rotate(s, p.session_id, tenant_id=row.tenant_id, set_tenant=True)
        if row is None or new is None:
            raise HTTPException(404, "invitation not valid for this sign-in; it may have expired or been used")
        return session_response({"tenant_id": str(row.tenant_id), "role": row.role}, new)

    # ------------------------------------------------------------------ members (owner only, S-13)
    def member_rows(s: Session) -> list[Any]:
        return list(s.execute(
            select(Membership.id, Membership.user_id, Membership.role, Membership.invited_email,
                   Membership.invite_expires_at, Membership.accepted_at, UserAccount.email, UserAccount.display_name)
            .outerjoin(UserAccount, UserAccount.id == Membership.user_id).order_by(Membership.created_at)).all())

    @app.get("/api/members")
    def list_members(request: Request) -> dict[str, Any]:
        p = owner(request, "member.read")
        assert p.tenant_id is not None
        with factory.begin() as s:
            tenancy.set_tenant(s, p.tenant_id)
            rows = member_rows(s)
        return {"data": [{"id": str(r.id), "role": r.role, "state": "member" if r.user_id else "invited",
                          "email": r.email or r.invited_email, "display_name": r.display_name,
                          "invite_expires_at": r.invite_expires_at.isoformat() if r.invite_expires_at else None}
                         for r in rows]}

    @app.post("/api/members/invitations", status_code=201)
    def invite(body: dict[str, Any], request: Request) -> dict[str, Any]:
        p = owner(request, "member.write")
        assert p.tenant_id is not None
        email = local_idp.normalise_email(body.get("email"))
        role = body.get("role")
        if email is None or role not in permissions.ROLES:
            raise HTTPException(422, "a valid email and a role (owner, engineer, reviewer) are required")
        raw = secrets.token_urlsafe(32)
        mid = uuid.uuid4()
        expires = clock.now() + INVITE_TTL
        try:
            with factory.begin() as s:
                tenancy.set_tenant(s, p.tenant_id)
                s.execute(insert(Membership).values(id=mid, tenant_id=p.tenant_id, user_id=None, role=role,
                                                    invited_email=email, invite_token_hash=token_hash(raw),
                                                    invite_expires_at=expires))
                audit.record(s, p.tenant_id, "user", p.user_id, "member_invite", str(mid), {"role": role})
                mailer.send(Mail(email, "You are invited to MapleRoute", SecretValue(
                    f"You were invited to a MapleRoute organisation as {role}.\n\n"
                    f"Sign in, then open this link within {INVITE_TTL.days} days:\n\n"
                    f"{public_base_url.rstrip('/')}/invite#token={raw}\n\n"
                    "The link works once, and only for a sign-in with this email address.\n"), "invitation"))
        except MailUnavailable as exc:
            raise HTTPException(503, "mail is unavailable; try again later") from exc
        return {"id": str(mid), "role": role, "state": "invited", "invite_expires_at": expires.isoformat()}

    def _lock_owners(s: Session) -> list[uuid.UUID]:
        """Lock every owner row of the tenant before reading or changing a member (B2-S04). Concurrent
        demotions or removals queue on these locks, and the later one reads the owners as the earlier one
        committed them, so a race can never leave a tenant without an owner."""
        return list(s.execute(select(Membership.id).where(Membership.role == "owner", Membership.user_id.is_not(None))
                              .order_by(Membership.id).with_for_update()).scalars().all())

    @app.patch("/api/members/{mid}")
    def change_role(mid: uuid.UUID, body: dict[str, Any], request: Request) -> dict[str, Any]:
        p = owner(request, "member.write")
        assert p.tenant_id is not None
        role = body.get("role")
        if role not in permissions.ROLES:
            raise HTTPException(422, "role must be owner, engineer or reviewer")
        with factory.begin() as s:
            tenancy.set_tenant(s, p.tenant_id)
            owners = _lock_owners(s)
            row = s.get(Membership, mid)
            if row is None:
                raise HTTPException(404, "not found")
            if row.role == "owner" and role != "owner" and not [o for o in owners if o != mid]:
                raise HTTPException(409, "an organisation keeps at least one owner")
            s.execute(update(Membership).where(Membership.id == mid).values(role=role))
            audit.record(s, p.tenant_id, "user", p.user_id, "member_role_change", str(mid),
                         {"from": row.role, "to": role})
        return {"id": str(mid), "role": role}

    @app.delete("/api/members/{mid}")
    def remove_member(mid: uuid.UUID, request: Request) -> dict[str, Any]:
        p = owner(request, "member.write")
        assert p.tenant_id is not None
        with factory.begin() as s:
            tenancy.set_tenant(s, p.tenant_id)
            owners = _lock_owners(s)
            row = s.get(Membership, mid)
            if row is None:
                raise HTTPException(404, "not found")
            if row.role == "owner" and row.user_id is not None and not [o for o in owners if o != mid]:
                raise HTTPException(409, "an organisation keeps at least one owner")
            s.execute(delete(Membership).where(Membership.id == mid))
            ended = identity.end_all_sessions(s, row.user_id, p.tenant_id) if row.user_id else 0
            audit.record(s, p.tenant_id, "user", p.user_id, "member_remove", str(mid), {"sessions_ended": ended})
        return {"id": str(mid), "state": "removed"}


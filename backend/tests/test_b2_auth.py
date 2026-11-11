"""B2 console sign-in: local identity provider (password + TOTP), sessions, anti-forgery, roles,
invitations, operator re-authentication. Mail is the in-memory fake here; the Mailpit and MinIO
end-to-end runs are in test_b2_integration.py. All addresses and names are synthetic."""

from __future__ import annotations

import base64
import re
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from console.auth import SignInLimits
from core import permissions, totp
from core.mail import MemoryMailer
from core.models import Project, UserAccount
from core.passwords import PasswordRejected, check_policy
from core.ratelimit import SlidingWindow
from core.secretvalue import SecretValue
from tests.helpers import HAIKU, World, fixture_routes

PW = "correct horse battery staple 7"
TOKEN_RE = re.compile(r"#token=([A-Za-z0-9_-]+)")


def code_for(seed_b32: str, world: World, offset_steps: int = 0) -> str:
    seed = base64.b32decode(seed_b32 + "=" * (-len(seed_b32) % 8))
    return totp.code_at(seed, totp.step_of(world.clock()) + offset_steps)


def link_token(mailer: MemoryMailer) -> str:
    m = TOKEN_RE.search(mailer.sent[-1].body.reveal())
    assert m is not None
    return m.group(1)


def enrol(c: TestClient, mailer: MemoryMailer, email: str, password: str = PW) -> str:
    assert c.post("/auth/local/enrol", json={"email": email}).status_code == 202
    r = c.post("/auth/local/enrol/complete",
               json={"token": link_token(mailer), "display_name": "Synthetic User", "password": password})
    assert r.status_code == 201, r.text
    assert r.headers["cache-control"] == "no-store"
    return str(r.json()["totp_secret"])


def sign_in(c: TestClient, world: World, email: str, seed: str, password: str = PW, **extra: Any) -> Any:
    world.clock.advance(seconds=30)  # a fresh TOTP step: each code is accepted once
    r = c.post("/auth/local/sign-in", json={"email": email, "password": password, "code": code_for(seed, world),
                                            **extra})
    if r.status_code == 200:
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r


def onboard(c: TestClient, name: str = "Alpha Software Inc. (synthetic)") -> uuid.UUID:
    r = c.post("/api/onboarding", json={"legal_name": name})
    assert r.status_code == 201, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return uuid.UUID(r.json()["tenant_id"])


def project_in(world: World, tenant_id: uuid.UUID) -> uuid.UUID:
    with world.owner.begin() as s:
        p = Project(tenant_id=tenant_id, name="synthetic-project")
        s.add(p)
        s.flush()
        return p.id


def cookie(c: TestClient) -> str:
    value = c.cookies.get("__Host-mr_session")
    assert value is not None
    return value


def new_email(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.test"


# ---------------------------------------------------------------------------------- unit


def test_totp_rfc6238_vector_and_single_use(world: World) -> None:
    seed = b"12345678901234567890"  # RFC 6238 appendix B SHA-1 seed; T=59 -> 94287082 (8 digits)
    assert totp.code_at(seed, 59 // 30) == "287082"
    at = world.clock()
    step = totp.verify(seed, totp.code_at(seed, totp.step_of(at)), at, None)
    assert step == totp.step_of(at)
    assert totp.verify(seed, totp.code_at(seed, step), at, step) is None  # replay refused (ASVS 6.5.1)
    assert totp.verify(seed, totp.code_at(seed, step - 3), at, None) is None  # outside the drift window
    assert totp.verify(seed, "12345", at, None) is None


def test_password_policy() -> None:
    for weak in ("short", "password1234", "Mapleroute2026!", "x" * 129):
        with pytest.raises(PasswordRejected):
            check_policy(SecretValue(weak), "dana@example.test")
    check_policy(SecretValue(PW), "dana@example.test")
    check_policy(SecretValue("ÄÖÜ unicode and spaces ok"), "dana@example.test")  # no composition rules


def test_ut12_role_action_matrix_matches_prd() -> None:
    expected = {
        "owner": {"project.read", "request_log.read", "report.read", "connection.write", "route.write",
                  "key.write", "member.read", "member.write"},
        "engineer": {"project.read", "request_log.read", "report.read", "connection.write", "route.write",
                     "key.write"},
        "reviewer": {"project.read", "request_log.read", "report.read"},
    }
    for role in permissions.ROLES:
        assert {a for a in permissions.MATRIX if permissions.allowed(role, a)} == expected[role]
    assert not any(permissions.allowed(None, a) for a in permissions.MATRIX)
    with pytest.raises(KeyError):
        permissions.allowed("owner", "tenant.delete_everything")


def test_sliding_window(world: World) -> None:
    w = SlidingWindow(2, timedelta(minutes=1))
    now = world.clock()
    assert w.allow("k", now) and w.allow("k", now) and not w.allow("k", now)
    assert w.allow("k", now + timedelta(minutes=1, seconds=1))


# ---------------------------------------------------------------------------------- sign-in


def test_enrol_sign_in_session_cookie_and_logout(world: World) -> None:
    mailer = MemoryMailer()
    c = world.session_console(mailer)
    email = new_email("owner")
    seed = enrol(c, mailer, email)
    assert c.get("/auth/session").status_code == 401  # enrolment does not sign anyone in
    r = sign_in(c, world, email, seed)
    assert r.status_code == 200, r.text
    assert r.json()["next"] == "onboarding" and r.json()["tenant_id"] is None
    set_cookie = r.headers["set-cookie"]
    assert set_cookie.startswith("__Host-mr_session=")
    for attr in ("Secure", "HttpOnly", "SameSite=lax", "Path=/"):
        assert attr.lower() in set_cookie.lower(), attr
    assert "domain=" not in set_cookie.lower()
    for header in ("strict-transport-security", "x-content-type-options", "content-security-policy"):
        assert header in r.headers
    assert "max-age=31536000" in r.headers["strict-transport-security"]
    me = c.get("/auth/session").json()
    assert me["amr"] == ["pwd", "otp"] and me["csrf_token"] == r.json()["csrf_token"]
    token = cookie(c)
    with world.owner() as s:  # only the hash is stored
        assert s.execute(text("SELECT count(*) FROM session WHERE token_hash = sha256(:t)"),
                         {"t": token.encode()}).scalar() == 1
    assert c.post("/auth/logout").status_code == 204
    c.cookies.set("__Host-mr_session", token)  # replay the old cookie after logout (ASVS 7.4.1)
    assert c.get("/auth/session").status_code == 401


def test_enrolment_link_reused_and_expired_refused(world: World) -> None:
    mailer = MemoryMailer()
    c = world.session_console(mailer)
    email = new_email("reuse")
    assert c.post("/auth/local/enrol", json={"email": email}).status_code == 202
    token = link_token(mailer)
    body = {"token": token, "display_name": "Synthetic", "password": PW}
    assert c.post("/auth/local/enrol/complete", json={**body, "password": "short"}).status_code == 422
    assert c.post("/auth/local/enrol/complete", json=body).status_code == 201  # weak try did not use it
    assert c.post("/auth/local/enrol/complete", json=body).status_code == 400  # reused
    other = new_email("expired")
    assert c.post("/auth/local/enrol", json={"email": other}).status_code == 202
    expired = link_token(mailer)
    world.clock.advance(minutes=16)
    assert c.post("/auth/local/enrol/complete",
                  json={"token": expired, "display_name": "x", "password": PW}).status_code == 400
    # An enrolled address gets a notice, not a second link, and the answer is the same (6.3.6, 6.3.8).
    sent = len(mailer.sent)
    assert c.post("/auth/local/enrol", json={"email": email}).status_code == 202
    assert len(mailer.sent) == sent + 1 and mailer.sent[-1].purpose == "enrol_exists"
    assert TOKEN_RE.search(mailer.sent[-1].body.reveal()) is None


def test_wrong_factor_replayed_code_and_lockout(world: World) -> None:
    mailer = MemoryMailer()
    # Windows wide enough that the database lockout, not the rate limit, is what refuses here.
    c = world.session_console(mailer, limits=SignInLimits(per_email=SlidingWindow(100, timedelta(minutes=15))))
    email = new_email("lock")
    seed = enrol(c, mailer, email)
    world.clock.advance(seconds=30)
    good = code_for(seed, world)
    assert c.post("/auth/local/sign-in", json={"email": email, "password": PW + "x", "code": good}).status_code == 401
    assert c.post("/auth/local/sign-in", json={"email": email, "password": PW, "code": good}).status_code == 200
    # The same code again, still inside its 30 seconds: refused (6.5.1).
    assert c.post("/auth/local/sign-in", json={"email": email, "password": PW, "code": good}).status_code == 401
    unknown = c.post("/auth/local/sign-in", json={"email": new_email("nobody"), "password": PW, "code": good})
    assert unknown.status_code == 401  # same answer as a wrong factor (6.3.8)
    for _ in range(10):
        world.clock.advance(seconds=30)
        c.post("/auth/local/sign-in", json={"email": email, "password": "wrong password value", "code": "000000"})
    r = sign_in(c, world, email, seed)
    assert r.status_code == 401  # locked, even with both factors right (6.3.1)
    world.clock.advance(minutes=16)
    assert sign_in(c, world, email, seed).status_code == 200


def test_sign_in_rate_limit(world: World) -> None:
    mailer = MemoryMailer()
    limits = SignInLimits(per_email=SlidingWindow(3, timedelta(minutes=15)))
    c = world.session_console(mailer, limits=limits)
    email = new_email("rate")
    seed = enrol(c, mailer, email)
    for _ in range(3):
        assert c.post("/auth/local/sign-in", json={"email": email, "password": "nope nope nope",
                                                   "code": "000000"}).status_code == 401
    assert sign_in(c, world, email, seed).status_code == 429
    limits2 = SignInLimits(enrol_per_email=SlidingWindow(1, timedelta(minutes=15)))
    c2 = world.session_console(MemoryMailer(), limits=limits2)
    e2 = new_email("enrolrate")
    assert c2.post("/auth/local/enrol", json={"email": e2}).status_code == 202
    assert c2.post("/auth/local/enrol", json={"email": e2}).status_code == 429


def test_session_idle_and_absolute_expiry_and_new_token_per_sign_in(world: World) -> None:
    mailer = MemoryMailer()
    c = world.session_console(mailer)
    email = new_email("expiry")
    seed = enrol(c, mailer, email)
    assert sign_in(c, world, email, seed).status_code == 200
    first = cookie(c)
    assert sign_in(c, world, email, seed).status_code == 200
    second = cookie(c)
    assert first != second
    c.cookies.set("__Host-mr_session", first)
    assert c.get("/auth/session").status_code == 401  # the old session ended at the new sign-in (7.2.4)
    c.cookies.set("__Host-mr_session", second)
    world.clock.advance(minutes=31)
    assert c.get("/auth/session").status_code == 401  # idle timeout (7.3.1)
    assert sign_in(c, world, email, seed).status_code == 200
    for _ in range(37):  # active every 20 minutes for 12 h 20 min
        world.clock.advance(minutes=20)
        if c.get("/auth/session").status_code != 200:
            break
    else:
        pytest.fail("session outlived its absolute lifetime")
    assert c.get("/auth/session").status_code == 401  # absolute lifetime (7.3.2)


def test_anti_forgery_and_origin_on_mutations(world: World) -> None:
    mailer = MemoryMailer()
    c = world.session_console(mailer)
    email = new_email("csrf")
    seed = enrol(c, mailer, email)
    assert sign_in(c, world, email, seed).status_code == 200
    tid = onboard(c)
    pid = project_in(world, tid)
    csrf = c.headers.pop("X-CSRF-Token")
    assert c.post(f"/api/projects/{pid}/keys", headers={"Idempotency-Key": "k1"}).status_code == 403
    assert c.post(f"/api/projects/{pid}/keys", headers={"Idempotency-Key": "k1", "X-CSRF-Token": "0" * 64}
                  ).status_code == 403
    assert c.post(f"/api/projects/{pid}/keys", headers={"Idempotency-Key": "k1", "X-CSRF-Token": csrf,
                                                        "Origin": "https://evil.example.test"}).status_code == 403
    ok = c.post(f"/api/projects/{pid}/keys", headers={"Idempotency-Key": "k1", "X-CSRF-Token": csrf,
                                                      "Origin": "https://console.mapleroute.localhost"})
    assert ok.status_code == 200 and ok.json()["key"].startswith("mr_")
    assert c.post("/auth/logout").status_code == 403  # logout is a mutation too
    foreign = world.session_console(mailer)
    assert foreign.post("/auth/local/sign-in", json={"email": email, "password": PW, "code": "000000"},
                        headers={"Origin": "https://evil.example.test"}).status_code == 403  # sign-in CSRF
    assert c.get(f"/api/projects/{pid}/requests").status_code == 200  # reads need no token


def test_cross_tenant_session_refused(world: World) -> None:
    mailer = MemoryMailer()
    c = world.session_console(mailer)
    email = new_email("alpha")
    seed = enrol(c, mailer, email)
    assert sign_in(c, world, email, seed).status_code == 200
    a_tid = onboard(c)
    a_pid = project_in(world, a_tid)
    b = world.tenant("beta")
    assert c.get(f"/api/projects/{a_pid}/requests").status_code == 200
    assert c.get(f"/api/projects/{b.project_id}/requests").status_code == 404
    assert c.post(f"/api/projects/{b.project_id}/keys", headers={"Idempotency-Key": "x"}).status_code == 404
    # Switching to a tenant without a membership, or signing in "into" one, is refused.
    assert c.post("/auth/tenant", json={"tenant_id": str(b.tenant_id)}).status_code == 404
    r = sign_in(c, world, email, seed, tenant_id=str(b.tenant_id))
    assert r.status_code == 200 and r.json()["tenant_id"] is None
    assert c.get(f"/api/projects/{a_pid}/requests").status_code == 404  # no tenant chosen in this session


def test_invitation_flow_email_bound_one_use_and_expiry(world: World) -> None:
    mailer = MemoryMailer()
    c = world.session_console(mailer)
    owner_email = new_email("owner")
    owner_seed = enrol(c, mailer, owner_email)
    assert sign_in(c, world, owner_email, owner_seed).status_code == 200
    tid = onboard(c)
    pid = project_in(world, tid)
    invited = new_email("reviewer")
    r = c.post("/api/members/invitations", json={"email": invited, "role": "reviewer"})
    assert r.status_code == 201, r.text
    invite_token = link_token(mailer)
    assert mailer.sent[-1].to == invited

    # Another identity, same organisation domain, different address: refused (UT-13, no domain matching).
    other = world.session_console(mailer)
    other_email = invited.replace("reviewer-", "rev1ewer-")
    other_seed = enrol(other, mailer, other_email)
    assert sign_in(other, world, other_email, other_seed).status_code == 200
    assert other.post("/auth/invitations/accept", json={"token": invite_token}).status_code == 404

    invitee = world.session_console(mailer)
    seed = enrol(invitee, mailer, invited)
    assert sign_in(invitee, world, invited, seed).json()["next"] == "onboarding"
    acc = invitee.post("/auth/invitations/accept", json={"token": invite_token})
    assert acc.status_code == 200 and acc.json()["role"] == "reviewer"
    invitee.headers["X-CSRF-Token"] = acc.json()["csrf_token"]
    assert invitee.get(f"/api/projects/{pid}/requests").status_code == 200
    assert invitee.post(f"/api/projects/{pid}/keys", headers={"Idempotency-Key": "r"}).status_code == 403
    assert invitee.get("/api/members").status_code == 403
    assert invitee.post("/auth/invitations/accept", json={"token": invite_token}).status_code == 404  # one use

    # An expired invitation is refused.
    late = new_email("late")
    assert c.post("/api/members/invitations", json={"email": late, "role": "engineer"}).status_code == 201
    late_token = link_token(mailer)
    late_client = world.session_console(mailer)
    late_seed = enrol(late_client, mailer, late)
    world.clock.advance(days=8)
    assert sign_in(late_client, world, late, late_seed).status_code == 200
    assert late_client.post("/auth/invitations/accept", json={"token": late_token}).status_code == 404

    # The owner signs in again (the earlier session idled out), removes the reviewer: sessions end at once.
    assert sign_in(c, world, owner_email, owner_seed).status_code == 200
    members = c.get("/api/members").json()["data"]
    reviewer = next(m for m in members if m["email"] == invited)
    only_owner = next(m for m in members if m["role"] == "owner")
    assert c.patch(f"/api/members/{only_owner['id']}", json={"role": "engineer"}).status_code == 409
    assert sign_in(invitee, world, invited, seed).json()["tenant_id"] == str(tid)
    assert c.delete(f"/api/members/{reviewer['id']}").status_code == 200
    assert invitee.get("/auth/session").status_code == 401


def test_console_role_cannot_create_operator(world: World) -> None:
    with pytest.raises(DBAPIError), world.con.begin() as s:
        s.execute(text("INSERT INTO user_account (idp, idp_subject, email, display_name, is_operator) "
                       "VALUES ('local', 'x', 'x@example.test', 'x', true)"))
    with pytest.raises(DBAPIError), world.con.begin() as s:
        s.execute(text("UPDATE user_account SET is_operator = true"))


def test_operator_session_needs_recent_reauth(world: World) -> None:
    mailer = MemoryMailer()
    c = world.session_console(mailer)
    email = new_email("operator")
    seed = enrol(c, mailer, email)
    with world.owner.begin() as s:  # operators are seeded by the database owner, never by the console
        s.execute(text("UPDATE user_account SET is_operator = true WHERE email = :e"), {"e": email})
        op_id = s.execute(text("SELECT id FROM user_account WHERE email = :e"), {"e": email}).scalar_one()
    assert sign_in(c, world, email, seed).status_code == 200
    body = {"version": "2026.11.10-1", "routes": fixture_routes()}
    assert c.post("/api/ops/allowlist/versions", json=body).status_code == 201
    world.clock.advance(minutes=6)
    assert c.get("/auth/session").status_code == 200
    approve = {"confirm": "2026.11.10-1"}
    assert c.post("/api/ops/allowlist/versions/2026.11.10-1/approve", json=approve).status_code == 401
    world.clock.advance(seconds=30)
    bad = c.post("/auth/reauth", json={"password": PW, "code": "000000"})
    assert bad.status_code == 401
    r = c.post("/auth/reauth", json={"password": PW, "code": code_for(seed, world)})
    assert r.status_code == 200
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert c.post("/api/ops/allowlist/versions/2026.11.10-1/approve", json=approve).json()["state"] == "active"
    assert c.post(f"/api/ops/routes/{HAIKU}/suspend").status_code == 200
    with world.owner() as s:
        assert s.get(UserAccount, op_id) is not None


def test_secrets_never_logged(world: World) -> None:
    mailer = MemoryMailer()
    c = world.session_console(mailer)
    email = new_email("canary")
    assert c.post("/auth/local/enrol", json={"email": email}).status_code == 202
    enrol_token = link_token(mailer)
    done = c.post("/auth/local/enrol/complete", json={"token": enrol_token, "display_name": "x", "password": PW})
    seed = done.json()["totp_secret"]
    r = sign_in(c, world, email, seed)
    session_cookie = cookie(c)
    c.post("/auth/local/sign-in", json={"email": email, "password": "wrong canary password", "code": "123456"})
    logs = world.logs.getvalue()
    for secret in (PW, "wrong canary password", seed, enrol_token, session_cookie, r.json()["csrf_token"]):
        assert secret and secret not in logs
    with world.owner() as s:
        dump = " ".join(str(v) for row in s.execute(text(
            "SELECT password_hash, encode(totp_ciphertext, 'hex') FROM local_credential")).all() for v in row)
        audit = " ".join(str(r) for r in s.execute(text("SELECT detail::text, target FROM audit_event")).all())
    assert PW not in dump and seed not in dump and dump.count("$argon2id$") == 1
    assert PW not in audit and seed not in audit

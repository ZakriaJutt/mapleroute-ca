"""Regression tests for the B2 security review, round 1 (B2-S01 to B2-S05,
`_coordination/review/mapleroute-ca-b2-sec-round1.md`). Each test fails if its control is removed.
Synthetic data only; mail goes to the in-memory fake."""

from __future__ import annotations

import dataclasses
import socket
import statistics
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import httpx
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import text

from console.app import ConsoleServices
from console.app import create_app as create_console
from console.auth import SignInLimits
from console.main import server_config
from core.config import settings
from core.mail import MemoryMailer
from core.ratelimit import SlidingWindow
from core.storage import MemoryObjectStore
from tests.helpers import CONSOLE_PUBLIC_URL, World, fixture_routes
from tests.test_b2_auth import PW, code_for, cookie, enrol, new_email, onboard, sign_in

WIDE = SlidingWindow(10_000, timedelta(minutes=1))
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "sql"


def owner_with_tenant(world: World, mailer: MemoryMailer, tag: str) -> tuple[TestClient, str, str]:
    c = world.session_console(mailer)
    email = new_email(tag)
    seed = enrol(c, mailer, email)
    assert sign_in(c, world, email, seed).status_code == 200
    onboard(c)
    return c, email, seed


def session_rows(world: World, token: str) -> int:
    with world.owner() as s:
        return int(s.execute(text("SELECT count(*) FROM session WHERE token_hash = sha256(:t)"),
                             {"t": token.encode()}).scalar_one())


# ---------------------------------------------------------------------------------- B2-S01, 7.4.1


def test_b2_s01_logout_ends_a_tenant_session(world: World) -> None:
    mm = MemoryMailer()
    c, _, _ = owner_with_tenant(world, mm, "s01-logout")
    assert c.get("/auth/session").json()["tenant_id"] is not None
    token = cookie(c)
    r = c.post("/auth/logout")
    assert r.status_code == 204
    assert "__Host-mr_session=\"\"" in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert session_rows(world, token) == 0
    c.cookies.set("__Host-mr_session", token)
    assert c.get("/auth/session").status_code == 401
    with world.owner() as s:
        assert s.execute(text("SELECT count(*) FROM audit_event WHERE action = 'sign_out'")).scalar_one() == 1


def test_b2_s01_logout_all_ends_every_tenant_session(world: World) -> None:
    mm = MemoryMailer()
    c, email, seed = owner_with_tenant(world, mm, "s01-all")
    other = world.session_console(mm)
    assert sign_in(other, world, email, seed).json()["tenant_id"] is not None  # second device, same tenant
    tokens = [cookie(c), cookie(other)]
    r = c.post("/auth/logout-all")
    assert r.status_code == 204 and "set-cookie" in r.headers
    for t in tokens:
        assert session_rows(world, t) == 0
    assert other.get("/auth/session").status_code == 401


def test_b2_s01_logout_of_operator_session(world: World) -> None:
    mm = MemoryMailer()
    c = world.session_console(mm)
    email = new_email("s01-op")
    seed = enrol(c, mm, email)
    with world.owner.begin() as s:
        s.execute(text("UPDATE user_account SET is_operator = true WHERE email = :e"), {"e": email})
    assert sign_in(c, world, email, seed).status_code == 200
    onboard(c)  # an operator who also belongs to a tenant
    token = cookie(c)
    assert c.post("/auth/logout").status_code == 204
    assert session_rows(world, token) == 0
    assert sign_in(c, world, email, seed).status_code == 200
    token = cookie(c)
    assert c.post("/auth/logout-all").status_code == 204
    assert session_rows(world, token) == 0


def test_b2_s01_audit_failure_never_keeps_a_session(world: World) -> None:
    mm = MemoryMailer()
    c, _, _ = owner_with_tenant(world, mm, "s01-auditfail")
    token = cookie(c)
    with world.owner.begin() as s:  # make every audit insert fail
        s.execute(text("REVOKE INSERT ON audit_event FROM mapleroute_console"))
    try:
        r = c.post("/auth/logout")
    finally:
        with world.owner.begin() as s:
            s.execute(text("GRANT INSERT ON audit_event TO mapleroute_console"))
    assert r.status_code == 204 and "set-cookie" in r.headers
    assert session_rows(world, token) == 0
    assert "audit_failed" in world.logs.getvalue()


# ---------------------------------------------------------------------------------- B2-S02


def _free_port() -> int:
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return int(so.getsockname()[1])


@contextmanager
def live_console(world: World, limits: SignInLimits, trusted: frozenset[str] = frozenset()) -> Iterator[str]:
    """The console served by uvicorn with console/main.py's own server_config."""
    port = _free_port()
    cfg = dataclasses.replace(settings(), console_port=port, trusted_proxies=trusted)
    services = ConsoleServices(world.con, world.key_service, None, ops_factory=world.ops, mailer=MemoryMailer(),
                               store=MemoryObjectStore(), public_base_url=f"http://127.0.0.1:{port}", limits=limits,
                               trusted_proxies=trusted)
    server = uvicorn.Server(server_config(create_console(services), cfg))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        th.join(10)


def test_b2_s02_server_config_does_not_trust_proxy_headers_by_default() -> None:
    cfg = dataclasses.replace(settings(), trusted_proxies=frozenset())
    assert server_config(object(), cfg).proxy_headers is False
    pinned = server_config(object(), dataclasses.replace(cfg, trusted_proxies=frozenset({"10.0.0.5"})))
    assert pinned.proxy_headers is True and pinned.forwarded_allow_ips == ["10.0.0.5"]


def test_b2_s02_rotating_forwarded_for_does_not_bypass_the_address_limit(world: World) -> None:
    limits = SignInLimits(per_address=SlidingWindow(5, timedelta(minutes=1)), per_email=WIDE, enrol_per_email=WIDE)
    with live_console(world, limits) as base, httpx.Client(base_url=base, timeout=10) as h:
        rotated = [h.post("/auth/local/sign-in", json={"email": new_email("x"), "password": "p" * 12,
                                                       "code": "000000"},
                          headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code for i in range(7)]
    assert rotated[:5] == [401] * 5 and rotated[5:] == [429, 429]


def test_b2_s02_header_rewriting_server_still_shares_one_window(world: World) -> None:
    """Even under a server that rewrites the client from X-Forwarded-For (uvicorn's defaults), the app keys
    an untrusted forwarded request on one shared window."""
    limits = SignInLimits(per_address=SlidingWindow(3, timedelta(minutes=1)), per_email=WIDE, enrol_per_email=WIDE)
    services = ConsoleServices(world.con, world.key_service, None, mailer=MemoryMailer(), store=MemoryObjectStore(),
                               public_base_url=CONSOLE_PUBLIC_URL, limits=limits)
    c = TestClient(create_console(services), base_url="https://testserver")
    codes = [c.post("/auth/local/sign-in", json={"email": new_email("y"), "password": "p" * 12, "code": "000000"},
                    headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(5)]
    assert codes == [401, 401, 401, 429, 429]


# ---------------------------------------------------------------------------------- B2-S03, 6.3.8


def test_b2_s03_locked_unknown_and_wrong_password_take_the_same_work(world: World) -> None:
    mm = MemoryMailer()
    c = world.session_console(mm, limits=SignInLimits(per_address=WIDE, per_email=WIDE, enrol_per_email=WIDE))
    known, locked = new_email("t-known"), new_email("t-locked")
    enrol(c, mm, known)
    enrol(c, mm, locked)
    for i in range(10):
        c.post("/auth/local/sign-in", json={"email": locked, "password": f"bad-bad-bad-{i}", "code": "000000"})
    samples: dict[str, list[float]] = {"unknown": [], "wrong": [], "locked": []}
    answers = set()
    for _ in range(7):
        for label, em in (("unknown", new_email("ghost")), ("wrong", known), ("locked", locked)):
            t0 = time.perf_counter()
            r = c.post("/auth/local/sign-in", json={"email": em, "password": "wrong-password-x", "code": "000000"})
            samples[label].append(time.perf_counter() - t0)
            answers.add((r.status_code, r.text))
    med = {k: statistics.median(v) for k, v in samples.items()}
    assert len(answers) == 1
    assert med["locked"] > 0.5 * med["unknown"] and med["locked"] > 0.5 * med["wrong"], med


# ---------------------------------------------------------------------------------- B2-S04


def test_b2_s04_concurrent_mutual_demotion_leaves_an_owner(world: World) -> None:
    mm = MemoryMailer()
    a, _, _ = owner_with_tenant(world, mm, "s04-a")
    b_email = new_email("s04-b")
    assert a.post("/api/members/invitations", json={"email": b_email, "role": "owner"}).status_code == 201
    token = mm.sent[-1].body.reveal().split("#token=")[1].split()[0]
    b = world.session_console(mm)
    b_seed = enrol(b, mm, b_email)
    assert sign_in(b, world, b_email, b_seed).status_code == 200
    acc = b.post("/auth/invitations/accept", json={"token": token})
    assert acc.status_code == 200
    b.headers["X-CSRF-Token"] = acc.json()["csrf_token"]
    members = a.get("/api/members").json()["data"]
    ids = {m["email"]: m["id"] for m in members}
    a_id = next(m["id"] for m in members if m["email"] != b_email)
    for _ in range(4):
        barrier = threading.Barrier(2)
        codes: list[int] = []

        def demote(client: TestClient, target: str, barrier: threading.Barrier = barrier,
                   codes: list[int] = codes) -> None:
            barrier.wait()
            codes.append(client.patch(f"/api/members/{target}", json={"role": "engineer"}).status_code)

        t1 = threading.Thread(target=demote, args=(a, ids[b_email]))
        t2 = threading.Thread(target=demote, args=(b, a_id))
        for t in (t1, t2):
            t.start()
        for t in (t1, t2):
            t.join()
        with world.owner() as s:
            owners = s.execute(text("SELECT count(*) FROM membership WHERE role = 'owner' AND user_id IS NOT NULL"
                                    )).scalar_one()
        assert owners >= 1, codes
        # Restore two owners for the next round, through the database owner.
        with world.owner.begin() as s:
            s.execute(text("UPDATE membership SET role = 'owner' WHERE user_id IS NOT NULL"))


# ---------------------------------------------------------------------------------- B2-S05


def test_b2_s05_684_operator_without_second_factor_refused_even_when_recent(world: World) -> None:
    mm = MemoryMailer()
    c = world.session_console(mm)
    email = new_email("s05-amr")
    seed = enrol(c, mm, email)
    with world.owner.begin() as s:
        s.execute(text("UPDATE user_account SET is_operator = true WHERE email = :e"), {"e": email})
    assert sign_in(c, world, email, seed).status_code == 200
    assert c.post("/api/ops/allowlist/versions", json={"version": "2026.11.10-1", "routes": fixture_routes()}
                  ).status_code == 201
    with world.owner.begin() as s:  # the session says the provider sent only a password
        s.execute(text("UPDATE session SET amr = '{pwd}' WHERE token_hash = sha256(:t)"), {"t": cookie(c).encode()})
    approve = {"confirm": "2026.11.10-1"}
    assert c.post("/api/ops/allowlist/versions/2026.11.10-1/approve", json=approve).status_code == 401
    with world.owner.begin() as s:
        s.execute(text("UPDATE session SET amr = '{pwd,otp}' WHERE token_hash = sha256(:t)"),
                  {"t": cookie(c).encode()})
    assert c.post("/api/ops/allowlist/versions/2026.11.10-1/approve", json=approve).status_code == 200


def test_b2_s05_724_reauth_issues_a_new_token_and_ends_the_old(world: World) -> None:
    mm = MemoryMailer()
    c, _, seed = owner_with_tenant(world, mm, "s05-reauth")
    old = cookie(c)
    world.clock.advance(seconds=30)
    r = c.post("/auth/reauth", json={"password": PW, "code": code_for(seed, world)})
    assert r.status_code == 200
    new = cookie(c)
    assert new != old and session_rows(world, old) == 0 and session_rows(world, new) == 1
    c.cookies.set("__Host-mr_session", old)
    assert c.get("/auth/session").status_code == 401
    c.cookies.set("__Host-mr_session", new)
    assert c.get("/auth/session").status_code == 200


def test_b2_s05_345_346_referrer_policy_and_frame_ancestors(world: World) -> None:
    c = world.session_console()
    for r in (c.get("/healthz"), c.get("/auth/session"), c.post("/auth/local/enrol", json={"email": "bad"})):
        assert r.headers["referrer-policy"] == "no-referrer"
        csp = [d.strip() for d in r.headers["content-security-policy"].split(";")]
        assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "base-uri 'none'" in csp


def test_b2_s05_628_password_verified_exactly_as_typed(world: World) -> None:
    mm = MemoryMailer()
    c = world.session_console(mm, limits=SignInLimits(per_address=WIDE, per_email=WIDE, enrol_per_email=WIDE))
    email = new_email("s05-exact")
    password = "Exact Case Matters 42 "  # trailing space is part of it
    seed = enrol(c, mm, email, password=password)
    for variant in (password.lower(), password.upper(), password.strip(), password[:-2], password + "x"):
        assert sign_in(c, world, email, seed, password=variant).status_code == 401, repr(variant)
    assert sign_in(c, world, email, seed, password=password).status_code == 200


def test_b2_s05_629_passwords_of_64_to_128_characters_accepted(world: World) -> None:
    mm = MemoryMailer()
    c = world.session_console(mm, limits=SignInLimits(per_address=WIDE, per_email=WIDE, enrol_per_email=WIDE))
    for length in (64, 100, 128):
        email = new_email(f"s05-len{length}")
        password = ("long passphrase " * 10)[:length - 3] + "z9!"
        assert len(password) == length
        seed = enrol(c, mm, email, password=password)
        assert sign_in(c, world, email, seed, password=password).status_code == 200
    assert c.post("/auth/local/enrol", json={"email": new_email("s05-129")}).status_code == 202
    token = mm.sent[-1].body.reveal().split("#token=")[1].split()[0]
    assert c.post("/auth/local/enrol/complete",
                  json={"token": token, "display_name": "x", "password": "y" * 129}).status_code == 422


def test_b2_s05_632_no_default_accounts(world: World) -> None:
    for sql in MIGRATIONS.glob("*.sql"):
        body = sql.read_text().lower()
        for table in ("user_account", "local_credential", "membership", "session"):
            assert f"insert into {table}" not in body, (sql.name, table)
    c = world.session_console(limits=SignInLimits(per_address=WIDE, per_email=WIDE, enrol_per_email=WIDE))
    for email, password in (("admin@mapleroute.localhost", "admin"), ("root@localhost.test", "root"),
                            ("operator@mapleroute.localhost", "changeme"), ("admin@example.test", "password")):
        assert c.post("/auth/local/sign-in", json={"email": email, "password": password, "code": "000000"}
                      ).status_code == 401
    with world.owner() as s:  # the fixture truncated all rows: nothing re-creates an account by itself
        assert s.execute(text("SELECT count(*) FROM local_credential")).scalar_one() == 0

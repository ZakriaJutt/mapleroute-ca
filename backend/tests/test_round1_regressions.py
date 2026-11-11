"""Regression tests for B1 review round 1 (B1-001 to B1-010).

Each test reproduces an adversarial case from the independent review (A1-A9) against the fixed code.
Synthetic data only.
"""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import socket
import threading
import time
import uuid
from datetime import timedelta

import httpx
import pytest
import uvicorn
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from console.app import Principal
from core.fakes import FakeInference
from core.logging import quiet_server_loggers
from core.models import Binding, RequestLog, Route
from core.providers import ActivityEvent, AzureTarget, DeploymentAnswer, UpstreamRequest, UpstreamResponse
from core.verification import resume_route
from gateway.app import GatewayServices, RateLimiter, create_app
from tests.helpers import CONSOLE_URL, GATEWAY_URL, GPT4O, HAIKU, OPERATOR_URL, WORKER_URL, T, World
from worker.jobs import verify_binding

HOST = "synthetic-a.openai.azure.com"
DEP = "gpt4o-prod"


def code_of(r: httpx.Response) -> str:
    return "ok" if r.status_code == 200 else str(r.json()["error"]["code"])


def azure_setup(world: World) -> tuple[T, uuid.UUID]:
    world.activate()
    t = world.tenant("alpha")
    conn = world.azure_conn(t, HOST)
    world.azure_deployment(HOST, DEP)
    b = world.bind(t, conn, GPT4O, "gpt-4o", deployment_name=DEP)
    assert world.verify(t, b).result == "match"  # 10:00
    return t, b


def served(world: World) -> list[tuple[str, list[str]]]:
    with world.owner() as s:
        return [(r.state, list(r.flags)) for r in s.execute(
            select(RequestLog).order_by(RequestLog.received_at)).scalars()]


# ------------------------------------------------------------------------- B1-001 (A1)
def test_b1_001_request_served_during_the_check_reads_is_flagged(world: World) -> None:
    t, b = azure_setup(world)
    gw = world.gateway()
    world.clock.advance(minutes=5)
    world.azure_reader.recreate(HOST, DEP, "GlobalStandard", world.clock())
    world.clock.advance(minutes=10)
    original = world.azure_reader.get_deployment
    seen: list[str] = []

    def slow_read(target: AzureTarget) -> DeploymentAnswer:
        world.clock.advance(seconds=20)  # a request arrives while the provider is being read
        seen.append(code_of(world.chat(gw, t.key, "gpt-4o")))
        return original(target)

    world.azure_reader.get_deployment = slow_read  # type: ignore[method-assign]
    applied = world.verify(t, b)
    assert applied.result == "config_mismatch" and seen == ["ok"]
    assert applied.flagged_requests == 1
    assert served(world) == [("completed", ["config_changed_window"])]
    world.clock.advance(seconds=1)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "route_unverified"


# ------------------------------------------------------------------------- B1-002 (A2)
@pytest.mark.parametrize("failed_checks", [1, 2])
def test_b1_002_failed_check_never_moves_the_activity_lookback(world: World, failed_checks: int) -> None:
    t, b = azure_setup(world)
    gw = world.gateway()
    dep = world.azure_reader.deployments[(HOST, DEP)]
    baseline = dep.deployment
    world.clock.advance(minutes=5)  # swap, with deployment timestamps NOT changed (O-13 case)
    dep.deployment = dataclasses.replace(baseline, sku_name="GlobalStandard")
    dep.events += [ActivityEvent("deployment_delete", world.clock()), ActivityEvent("deployment_write", world.clock())]
    world.clock.advance(minutes=1)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"  # served while Global
    world.clock.advance(minutes=4)
    dep.deployment = baseline
    dep.events.append(ActivityEvent("deployment_write", world.clock()))
    dep.deny_access = True
    for _ in range(failed_checks):
        world.clock.advance(minutes=15)
        assert world.verify(t, b).result == "access_failed"
    dep.deny_access = False
    world.clock.advance(minutes=15)
    applied = world.verify(t, b)
    assert applied.result == "config_mismatch"
    assert applied.flagged_requests == 1
    assert served(world)[0] == ("completed", ["config_changed_window"])
    # Once a completed check covered the period, the next one starts after it and matches again.
    world.clock.advance(minutes=15)
    assert world.verify(t, b).result == "match"


# ------------------------------------------------------------------------- B1-003 (A3)
def test_b1_003_later_observed_mismatch_with_earlier_stamp_is_applied(world: World) -> None:
    t, b = azure_setup(world)
    gw = world.gateway()
    world.clock.advance(minutes=15)
    t_manual = world.clock()
    t_sched = t_manual + timedelta(seconds=1)
    with world.app.begin() as s:
        assert verify_binding(s, world.worker_services(), t.tenant_id, b, t_sched).result == "match"
    world.azure_reader.recreate(HOST, DEP, "GlobalStandard", t_sched + timedelta(seconds=2))
    world.clock.advance(seconds=3)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"  # served before the second job applies
    with world.app.begin() as s:
        applied = verify_binding(s, world.worker_services(), t.tenant_id, b, t_manual)
    assert applied.result == "config_mismatch" and applied.applied
    assert applied.flagged_requests == 1
    world.clock.advance(minutes=1)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "route_unverified"
    # A late *match* is still never applied after a newer mismatch (R-01, UT-06).
    with world.owner() as s:
        assert s.get(Binding, b).status == "unverified"  # type: ignore[union-attr]


def test_b1_003_gateway_waits_for_a_mismatch_being_applied(world: World) -> None:
    """While the worker holds the binding lock, a request is decided only after the commit."""
    t, b = azure_setup(world)
    world.clock.advance(minutes=15)
    world.azure_reader.recreate(HOST, DEP, "GlobalStandard", world.clock())
    gw = world.gateway()
    result: list[str] = []
    entered = threading.Event()
    original = world.azure_reader.get_diagnostic_logging

    def last_read(target: AzureTarget):  # type: ignore[no-untyped-def]
        entered.set()
        return original(target)

    world.azure_reader.get_diagnostic_logging = last_read  # type: ignore[method-assign]
    with world.app.begin() as s:
        applied = verify_binding(s, world.worker_services(), t.tenant_id, b, world.clock())
        assert applied.result == "config_mismatch"
        # The mismatch is applied but not committed; the lock is held. A request now must wait.
        th = threading.Thread(target=lambda: result.append(code_of(world.chat(gw, t.key, "gpt-4o"))))
        th.start()
        time.sleep(0.5)
        assert result == []  # blocked on the binding lock
    th.join(timeout=10)
    assert entered.is_set() and result == ["route_unverified"]


# ------------------------------------------------------------------------- B1-004 (A7)
@pytest.mark.parametrize("url", [GATEWAY_URL, CONSOLE_URL, WORKER_URL, OPERATOR_URL],
                         ids=["gateway", "console", "worker", "operator"])
def test_b1_004_temp_table_cannot_shadow_verification_in_resume_guard(world: World, url: str) -> None:
    world.activate()
    a = world.tenant("alpha")
    ba = world.bind(a, world.aws_conn(a), HAIKU, "haiku")
    assert world.verify(a, ba).result == "match"
    with world.owner.begin() as s:
        s.execute(text("UPDATE route SET global_status='suspended', status_changed_at=:t WHERE id=:r"),
                  {"r": HAIKU, "t": world.clock() + timedelta(hours=1)})
    eng = create_engine(url)
    try:
        with eng.begin() as c:
            c.execute(text("CREATE TEMP TABLE verification (route_id text, result text, checked_at timestamptz)"))
            c.execute(text("INSERT INTO pg_temp.verification VALUES (:r, 'match', :t)"),
                      {"r": HAIKU, "t": world.clock() + timedelta(hours=2)})
            with pytest.raises(DBAPIError):
                c.execute(text("UPDATE route SET global_status='active' WHERE id=:r"), {"r": HAIKU})
    finally:
        eng.dispose()
    with world.owner() as s:
        assert s.get(Route, HAIKU).global_status == "suspended"  # type: ignore[union-attr]
        funcs = s.execute(text(
            "SELECT p.proname, r.rolname, r.rolsuper, p.proconfig FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner "
            "WHERE p.prosecdef AND p.pronamespace = 'public'::regnamespace ORDER BY 1")).all()
    assert [f[0] for f in funcs] == ["resolve_api_key", "route_resume_guard", "tenants_bound_to_route"]
    for name, owner, is_super, config in funcs:
        assert owner == "mapleroute_definer" and not is_super, name
        assert config == ["search_path=pg_catalog, public, pg_temp"], name


def test_b1_004_only_the_operator_resumes(world: World) -> None:
    world.activate()
    a = world.tenant("alpha")
    ba = world.bind(a, world.aws_conn(a), HAIKU, "haiku")
    with world.owner.begin() as s:
        s.execute(text("UPDATE route SET global_status='suspended', status_changed_at=:t WHERE id=:r"),
                  {"r": HAIKU, "t": world.clock() - timedelta(minutes=1)})
    assert world.verify(a, ba).result == "match"  # a real, newer match exists
    with pytest.raises(DBAPIError, match="only the operator"), world.app.begin() as s:
        resume_route(s, HAIKU, world.operator(), world.clock())  # the worker may only suspend
    with world.ops.begin() as s:
        resume_route(s, HAIKU, world.operator(), world.clock())
    with world.owner() as s:
        assert s.get(Route, HAIKU).global_status == "active"  # type: ignore[union-attr]


# ------------------------------------------------------------------------- B1-005 (A8) and IT-07
def test_b1_005_gateway_role_cannot_list_tenants_users_or_forge_verification(world: World) -> None:
    world.activate()
    world.tenant("alpha")
    b = world.tenant("bravo")
    bb = world.bind(b, world.aws_conn(b), HAIKU, "haiku")  # never verified
    eng = create_engine(GATEWAY_URL)
    attacks: list[tuple[str, dict[str, object]]] = [
        ("SELECT legal_name FROM tenant", {}),
        ("SELECT email FROM user_account", {}),
        ("SELECT * FROM tenants_bound_to_route('x')", {}),
        ("UPDATE binding SET status='verified', last_verified_at=now(), l2_confirmed_at=now() WHERE id=:b",
         {"b": bb}),
        ("INSERT INTO verification (tenant_id, binding_id, route_id, checked_at, result, provider_answer, "
         "allowlist_version, grade) VALUES (:t, :b, :r, now(), 'match', '{}', 'x', 'EG-3')",
         {"t": b.tenant_id, "b": bb, "r": HAIKU}),
        ("UPDATE route SET global_status='suspended'", {}),
        ("INSERT INTO allowlist_version (version, document, sha256) VALUES ('2099.01.01-1', '{}', '\\x00')", {}),
        ("UPDATE request_log SET flags = '{}'", {}),
        ("SELECT * FROM job", {}),
    ]
    try:
        for sql, params in attacks:
            with eng.begin() as c:
                c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(b.tenant_id)})
                with pytest.raises(DBAPIError, match="permission denied"):
                    c.execute(text(sql), params)
    finally:
        eng.dispose()
    assert code_of(world.chat(world.gateway(), b.key, "haiku")) == "route_unverified"


def test_b1_005_console_cannot_mark_verified_or_read_ciphertext_it07(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    conn = world.azure_conn(t, HOST)
    bid = world.bind(t, conn, GPT4O, "gpt-4o", deployment_name=DEP)
    eng = create_engine(CONSOLE_URL)
    try:
        for sql in ("SELECT ciphertext FROM connection_secret", "SELECT wrapped_data_key FROM connection_secret",
                    "UPDATE binding SET status='verified', last_verified_at=now(), l2_confirmed_at=now()",
                    "INSERT INTO binding (tenant_id, project_id, connection_id, route_id, alias, status, "
                    "last_verified_at, l2_confirmed_at) VALUES (:t, :p, :c, :r, 'forged', 'verified', now(), now())",
                    "SELECT legal_name FROM tenant", "UPDATE route SET global_status='active'"):
            with eng.begin() as c:
                c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)})
                with pytest.raises(DBAPIError, match="permission denied"):
                    c.execute(text(sql), {"t": t.tenant_id, "p": t.project_id, "c": conn, "r": GPT4O})
        with eng.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)})
            assert c.execute(text("SELECT kms_key_arn FROM connection_secret")).scalar_one()
    finally:
        eng.dispose()
    with world.owner() as s:
        assert s.get(Binding, bid).status == "unverified"  # type: ignore[union-attr]


def test_b1_005_worker_reads_tenant_ids_but_not_names(world: World) -> None:
    world.tenant("alpha")
    eng = create_engine(WORKER_URL)
    try:
        with eng.begin() as c:
            assert len(c.execute(text("SELECT id FROM tenant")).all()) == 1
        with eng.begin() as c, pytest.raises(DBAPIError, match="permission denied"):
            c.execute(text("SELECT legal_name FROM tenant"))
        with eng.begin() as c, pytest.raises(DBAPIError, match="permission denied"):
            c.execute(text("SELECT * FROM resolve_api_key('\\x00')"))
    finally:
        eng.dispose()


def test_b1_005_verification_route_must_be_the_bindings_route(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    bid = world.bind(t, world.aws_conn(t), HAIKU, "haiku")
    with pytest.raises(DBAPIError, match="fk_verification_binding_route"), world.app.begin() as s:
        s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)})
        s.execute(text("INSERT INTO verification (tenant_id, binding_id, route_id, checked_at, result, "
                       "provider_answer, allowlist_version, grade) VALUES (:t, :b, :r, now(), 'match', '{}', "
                       "'x', 'EG-3')"), {"t": t.tenant_id, "b": bid, "r": GPT4O})


# ------------------------------------------------------------------------- B1-006 (A9)
class Leaky(FakeInference):
    def send(self, request: UpstreamRequest) -> UpstreamResponse:
        raise RuntimeError("ValidationException: CANARY-PROMPT-91c2 echoed by provider")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_b1_006_adapter_exception_text_reaches_no_log(world: World, capfd: pytest.CaptureFixture[str]) -> None:
    world.activate()
    t = world.tenant("alpha")
    b = world.bind(t, world.aws_conn(t), HAIKU, "haiku")
    assert world.verify(t, b).result == "match"
    leaky = Leaky()
    svc = GatewayServices(world.gw, {"aws": leaky, "azure": leaky}, world.aws_sessions, world.key_service,
                          RateLimiter(100))
    port = free_port()
    quiet_server_loggers()
    server = uvicorn.Server(uvicorn.Config(create_app(svc), host="127.0.0.1", port=port, access_log=False,
                                           log_level="warning", log_config=None))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/v1/chat/completions",
                       json={"model": "haiku", "messages": [{"role": "user", "content": "CANARY-PROMPT-91c2"}]},
                       headers={"Authorization": f"Bearer {t.key}"}, timeout=10)
        s = httpx.post(f"http://127.0.0.1:{port}/v1/chat/completions",
                       json={"model": "haiku", "stream": True, "messages": []},
                       headers={"Authorization": f"Bearer {t.key}"}, timeout=10)
    finally:
        server.should_exit = True
        th.join(timeout=10)
        root.removeHandler(handler)
    out, err = capfd.readouterr()
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error"
    assert "CANARY" not in r.text and "CANARY" not in s.text
    for stream in (buf.getvalue(), out, err, world.logs.getvalue()):
        assert "CANARY" not in stream
    assert '"error_class": "RuntimeError"' in world.logs.getvalue()
    with world.owner() as sess:
        assert sess.execute(select(RequestLog.state)).scalars().first() == "upstream_error"


def test_b1_006_unhandled_exception_becomes_generic_500(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")

    class Boom:
        def allow(self, *a: object) -> bool:
            raise ValueError("CANARY-RATE-LIMITER-TEXT")

    svc = GatewayServices(world.gw, {"aws": world.inference}, world.aws_sessions, world.key_service,
                          Boom())  # type: ignore[arg-type]
    from fastapi.testclient import TestClient

    r = TestClient(create_app(svc)).post("/v1/chat/completions", json={"model": "x"},
                                         headers={"Authorization": f"Bearer {t.key}"})
    assert r.status_code == 500 and "CANARY" not in r.text
    assert "CANARY" not in world.logs.getvalue()


# ------------------------------------------------------------------------- B1-008 (A6)
def test_b1_008_overlong_model_is_rejected_not_served(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    b = world.bind(t, world.aws_conn(t), HAIKU, "a" * 128)
    assert world.verify(t, b).result == "match"
    gw = world.gateway()
    assert code_of(world.chat(gw, t.key, "a" * 128)) == "ok"
    r = world.chat(gw, t.key, "a" * 128 + "-something-else")
    assert r.status_code == 403 and r.json()["error"]["code"] == "route_not_eligible"
    assert len(world.inference.calls) == 1


# ------------------------------------------------------------------------- B1-010
def test_b1_010_idempotency_key_is_scoped_to_the_endpoint(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    c = world.console(Principal(t.user_id, t.tenant_id, "owner"))
    conn = world.aws_conn(t)
    bound = c.post(f"/api/projects/{t.project_id}/routes", headers={"Idempotency-Key": "same"},
                   json={"connection_id": str(conn), "route_id": HAIKU, "alias": "haiku"}).json()
    key = c.post(f"/api/projects/{t.project_id}/keys", headers={"Idempotency-Key": "same"}).json()
    assert key["key"].startswith("mr_") and key["id"] != bound["id"] and "replayed" not in key


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "123", None])
def test_b1_010_malformed_ids_are_4xx(world: World, bad: object) -> None:
    world.activate()
    t = world.tenant("alpha")
    c = world.console(Principal(t.user_id, t.tenant_id, "owner"))
    r = c.post(f"/api/projects/{t.project_id}/routes", headers={"Idempotency-Key": f"m-{bad}"},
               json={"connection_id": bad, "route_id": HAIKU, "alias": "haiku"})
    assert r.status_code == 422
    assert c.get("/api/projects/not-a-uuid/requests").status_code == 422


# ========================================================================= fix round 2
# B1-012 cases (N3, three concurrent checks, older mismatch) moved to tests/test_check_serialisation.py
# in fix round 3: checks of one binding are now serialised (B1-003).

# ------------------------------------------------------------------------- B1-005 part (N4)
def test_b1_005_console_cannot_queue_jobs_for_other_tenants_or_kinds(world: World) -> None:
    world.activate()
    a, b = world.tenant("alpha"), world.tenant("bravo")
    world.bind(b, world.aws_conn(b), HAIKU, "haiku")
    ba = world.bind(a, world.aws_conn(a), HAIKU, "haiku")
    payload = json.dumps({"route_id": HAIKU, "changed_at": "x", "reason": "spoof"})
    attempts: list[tuple[str, dict[str, object]]] = [
        ("INSERT INTO job (kind, dedupe_key, payload) VALUES ('notify_route_suspended', 'n4', CAST(:p AS jsonb))",
         {"p": payload}),
        ("INSERT INTO job (kind, dedupe_key, tenant_id, payload) VALUES ('notify_route_suspended', 'n4b', :t, "
         "CAST(:p AS jsonb))", {"p": payload, "t": a.tenant_id}),
        ("INSERT INTO job (kind, dedupe_key, tenant_id, payload) VALUES ('verify_binding', 'n4c', :o, '{}')",
         {"o": b.tenant_id}),
    ]
    eng = create_engine(CONSOLE_URL)
    try:
        for sql, params in attempts:
            with eng.begin() as c:
                c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a.tenant_id)})
                with pytest.raises(DBAPIError, match="row-level security"):
                    c.execute(text(sql), params)
        with eng.begin() as c:  # a manual verify_binding job for its own binding is allowed
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a.tenant_id)})
            c.execute(text("INSERT INTO job (kind, dedupe_key, tenant_id, payload) "
                           "VALUES ('verify_binding', :d, :t, CAST(:p AS jsonb))"),
                      {"t": a.tenant_id, "d": f"{ba}:manual:own", "p": json.dumps({"binding_id": str(ba)})})
            assert c.execute(text("SELECT count(*) FROM job")).scalar_one() == 1
    finally:
        eng.dispose()
    with world.owner() as s:
        assert s.execute(text("SELECT count(*) FROM alert")).scalar_one() == 0
        assert s.execute(text("SELECT count(*) FROM job WHERE kind = 'notify_route_suspended'")).scalar_one() == 0


# ------------------------------------------------------------------------- B1-007 part
def test_b1_007_hand_built_decision_with_private_seal_is_not_sealed(world: World) -> None:
    from core import eligibility
    from core.eligibility import Decision
    from core.secretvalue import SecretValue
    from gateway.forward import forward

    forged = Decision(uuid.uuid4(), uuid.uuid4(), GPT4O, "azure", "eastus", "evil-global.openai.azure.com",
                      "gpt-4o-global", "x", "active", world.clock(), _seal=eligibility._SEAL)
    assert not forged.is_sealed()
    object.__setattr__(forged, "_seal", b"\x00" * 32)
    assert not forged.is_sealed()
    fake = FakeInference()
    with pytest.raises(TypeError):
        forward({"azure": fake}, forged, "chat", {}, SecretValue("x"))
    assert fake.calls == []

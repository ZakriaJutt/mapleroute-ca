"""IT-08 tenant isolation, console idempotency and show-once keys, operator API, IT-09 sweeper."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, text

from console.app import Principal
from core import requestlog, tenancy
from core.models import (
    ApiKey,
    Binding,
    ConnectionSecret,
    FormToken,
    Job,
    Project,
    ProviderConnection,
    RequestLog,
    Route,
)
from tests.helpers import GPT4O, HAIKU, T, World, fixture_routes
from worker.jobs import sweep_outcomes

TENANT_TABLES = ("membership", "form_token", "project", "provider_connection", "connection_secret", "api_key",
                 "binding", "verification", "logging_observation", "request_log", "alert", "audit_event")


def member(t: T, role: str = "owner") -> Principal:
    return Principal(t.user_id, t.tenant_id, role)


def two_tenants(world: World) -> tuple[T, T]:
    world.activate()
    a, b = world.tenant("alpha"), world.tenant("bravo")
    ba = world.bind(a, world.aws_conn(a), HAIKU, "haiku")
    world.verify(a, ba)
    assert world.chat(world.gateway(), a.key, "haiku").status_code == 200
    return a, b


def test_it08_no_tenant_context_reads_zero_rows(world: World) -> None:
    two_tenants(world)
    with world.owner() as s:
        populated = {t: s.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in TENANT_TABLES}
    assert sum(populated.values()) > 0
    checked = 0
    for factory in (world.gw, world.con, world.app, world.ops):
        with factory() as s:
            assert tenancy.current_tenant(s) is None
            role = s.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
            assert tuple(role) == (False, False)
            for table in TENANT_TABLES:
                if not s.execute(text("SELECT has_table_privilege(current_user, :t, 'SELECT')"),
                                 {"t": table}).scalar_one():
                    continue
                assert s.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
                checked += 1
    assert checked >= 15


def test_it08_job_for_a_reads_zero_rows_of_b(world: World) -> None:
    a, b = two_tenants(world)
    with world.app() as s, s.begin():  # worker role, as a job for B
        tenancy.set_tenant(s, b.tenant_id)
        assert s.execute(select(RequestLog)).scalars().all() == []
        assert s.execute(select(Binding)).scalars().all() == []
        tenancy.set_tenant(s, a.tenant_id)
        assert len(s.execute(select(RequestLog)).scalars().all()) == 1
    with world.con() as s, s.begin():
        tenancy.set_tenant(s, b.tenant_id)
        assert s.get(Project, a.project_id) is None


def test_it08_b_session_and_key_on_a_ids_get_404(world: World) -> None:
    a, b = two_tenants(world)
    console_b = world.console(member(b))
    assert console_b.get(f"/api/projects/{a.project_id}/requests").status_code == 404
    assert console_b.post(f"/api/projects/{a.project_id}/keys", headers={"Idempotency-Key": "k1"}).status_code == 404
    assert console_b.get(f"/api/projects/{b.project_id}/requests").json() == {"data": []}
    assert world.console(member(a)).get(f"/api/projects/{a.project_id}/requests").status_code == 200
    # B's key cannot reach A's alias: B's project has no binding for it.
    r = world.chat(world.gateway(), b.key, "haiku")
    assert r.status_code == 403 and r.json()["error"]["code"] == "route_not_eligible"
    # A cross-tenant write is refused by the policy's WITH CHECK.
    with world.con() as s, s.begin():
        tenancy.set_tenant(s, b.tenant_id)
        try:
            s.add(ProviderConnection(tenant_id=a.tenant_id, project_id=a.project_id, provider="aws",
                                     account_ref="smuggled", source_region="ca-central-1", role_arn="arn:x",
                                     external_id="x"))
            s.flush()
            raise AssertionError("cross-tenant insert succeeded")
        except Exception as exc:  # noqa: BLE001
            assert "row-level security" in str(exc)


def test_console_requires_sign_in_by_default(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    assert world.console(None).get(f"/api/projects/{t.project_id}/requests").status_code == 401
    assert world.console(member(t, "reviewer")).post(
        f"/api/projects/{t.project_id}/keys", headers={"Idempotency-Key": "x"}).status_code == 403


def test_key_shown_once_and_double_submit_returns_first_result(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    c = world.console(member(t))
    first = c.post(f"/api/projects/{t.project_id}/keys", headers={"Idempotency-Key": "form-1"}).json()
    second = c.post(f"/api/projects/{t.project_id}/keys", headers={"Idempotency-Key": "form-1"}).json()
    assert first["key"].startswith("mr_") and second["key"] is None and second["replayed"] is True
    assert first["id"] == second["id"]
    with world.owner() as s:
        assert s.execute(select(ApiKey).where(ApiKey.project_id == t.project_id)).scalars().all().__len__() == 2
        stored = " ".join(str(r) for r in s.execute(select(FormToken.result_ref)).scalars())
    assert first["key"] not in stored
    # The new key works on the gateway; revocation takes effect on the next request.
    gw = world.gateway()
    assert world.chat(gw, first["key"], "x").json()["error"]["code"] == "route_not_eligible"
    assert c.delete(f"/api/projects/{t.project_id}/keys/{first['id']}").status_code == 200
    assert world.chat(gw, first["key"], "x").status_code == 401


def test_connect_bind_verify_through_console(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    c = world.console(member(t))
    host = "synthetic-c.openai.azure.com"
    conn = c.post(f"/api/projects/{t.project_id}/connections", headers={"Idempotency-Key": "c1"}, json={
        "provider": "azure", "account_ref": "/subscriptions/synthetic/c", "source_region": "canadaeast",
        "endpoint_host": host, "resource_group": "rg-c", "secret": "CANARY-CONSOLE-SECRET"})
    assert conn.status_code == 200 and "secret" not in conn.json()
    bad = c.post(f"/api/projects/{t.project_id}/routes", headers={"Idempotency-Key": "r0"}, json={
        "connection_id": conn.json()["id"], "route_id": "azure:canadaeast:GlobalStandard:gpt-4o:2024-11-20",
        "alias": "gpt", "deployment_name": "d"})
    assert bad.status_code == 422
    bound = c.post(f"/api/projects/{t.project_id}/routes", headers={"Idempotency-Key": "r1"}, json={
        "connection_id": conn.json()["id"], "route_id": GPT4O, "alias": "gpt-4o", "deployment_name": "gpt4o-c"})
    assert bound.status_code == 200 and bound.json()["status"] == "unverified"
    again = c.post(f"/api/projects/{t.project_id}/routes", headers={"Idempotency-Key": "r1"}, json={})
    assert again.json()["id"] == bound.json()["id"]
    with world.owner() as s:
        jobs = s.execute(select(Job.dedupe_key).where(Job.kind == "verify_binding")).scalars().all()
        secret = s.execute(select(ConnectionSecret.ciphertext)).scalar_one()
    assert jobs == [f"{bound.json()['id']}:initial"]
    assert b"CANARY-CONSOLE-SECRET" not in bytes(secret)
    world.azure_deployment(host, "gpt4o-c")
    assert world.verify(t, uuid.UUID(bound.json()["id"])).result == "match"
    assert world.chat(world.gateway(), t.key, "gpt-4o").status_code == 200


def test_operator_api_publish_approve_suspend_resume(world: World) -> None:
    op = world.operator()
    # B2: approve, suspend and resume need a second factor and an authentication under 5 minutes old.
    stale = world.console(Principal(op, None, None, is_operator=True, amr=("pwd", "otp"),
                                    auth_time=world.clock() - timedelta(minutes=6)))
    no_mfa = world.console(Principal(op, None, None, is_operator=True, amr=("pwd",), auth_time=world.clock()))
    ops = world.console(Principal(op, None, None, is_operator=True, amr=("pwd", "otp"), auth_time=world.clock()))
    body = {"version": "2026.11.10-1", "routes": fixture_routes()}
    assert ops.post("/api/ops/allowlist/versions", json=body).status_code == 201
    assert ops.post("/api/ops/allowlist/versions", json=body).status_code == 200  # idempotent
    body2 = {"version": "2026.11.10-1", "routes": fixture_routes()[:3]}
    assert ops.post("/api/ops/allowlist/versions", json=body2).status_code == 409  # never edited
    bad = {"version": "2026.11.12-1", "routes": [dict(fixture_routes()[0], destinations=["us-east-1"])]}
    refused = ops.post("/api/ops/allowlist/versions", json=bad)
    assert refused.status_code == 422 and refused.json()["detail"]["refused_route"] == fixture_routes()[0]["id"]
    assert ops.post("/api/ops/allowlist/versions/2026.11.10-1/approve", json={}).status_code == 422
    for refused_client in (stale, no_mfa):
        assert refused_client.post("/api/ops/allowlist/versions/2026.11.10-1/approve",
                                   json={"confirm": "2026.11.10-1"}).status_code == 401
        assert refused_client.post(f"/api/ops/routes/{HAIKU}/suspend").status_code == 401
    ok = ops.post("/api/ops/allowlist/versions/2026.11.10-1/approve", json={"confirm": "2026.11.10-1"})
    assert ok.json()["state"] == "active"
    t = world.tenant("alpha")
    assert world.console(member(t)).post("/api/ops/routes/x/suspend").status_code == 403
    assert ops.post(f"/api/ops/routes/{HAIKU}/suspend").status_code == 200
    with world.owner() as s:
        assert s.get(Route, HAIKU).global_status == "suspended"  # type: ignore[union-attr]
    assert ops.post(f"/api/ops/routes/{HAIKU}/resume").status_code == 409


def test_route_removal_in_use_waits_seven_days(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    world.bind(t, world.aws_conn(t), HAIKU, "haiku")
    op = world.operator()
    ops = world.console(Principal(op, None, None, is_operator=True, amr=("pwd", "otp"), auth_time=world.clock()))
    routes = [r for r in fixture_routes() if r["id"] != HAIKU]
    published = ops.post("/api/ops/allowlist/versions", json={"version": "2026.11.11-1", "routes": routes})
    assert published.status_code == 201
    r = ops.post("/api/ops/allowlist/versions/2026.11.11-1/approve", json={"confirm": "2026.11.11-1"}).json()
    assert r["state"] == "draft" and r["activate_after"] is not None
    from core import policy_store

    with world.app.begin() as s:
        assert policy_store.activate_due(s, world.clock() + timedelta(days=6)) == []
    with world.app.begin() as s:
        assert policy_store.activate_due(s, world.clock() + timedelta(days=7)) == ["2026.11.11-1"]


def test_it09_sweeper_then_late_completion_reconciles(world: World) -> None:
    a, _ = two_tenants(world)
    rid, at = uuid.uuid4(), world.clock()
    with world.gw.begin() as s:
        tenancy.set_tenant(s, a.tenant_id)
        requestlog.insert(s, requestlog.NewRow(rid, a.tenant_id, a.project_id, a.key_id, at, "chat", "haiku",
                                               "forwarding", route_id=HAIKU, allowlist_version="2026.11.10-1",
                                               route_status="active", binding_verified_at=at))
    world.clock.advance(minutes=16)
    with world.app.begin() as s:
        assert sweep_outcomes(s, world.clock()) == 1
    with world.gw.begin() as s:
        tenancy.set_tenant(s, a.tenant_id)
        assert requestlog.transition(s, rid, at, "completed", world.clock(), http_status=200)
        assert not requestlog.transition(s, rid, at, "completed", world.clock())  # second writer: no change
    with world.owner() as s:
        row = s.execute(select(RequestLog).where(RequestLog.id == rid)).scalar_one()
    assert (row.state, row.reconciled_at) == ("completed", world.clock())
    with world.owner.begin() as s:
        try:
            s.execute(text("UPDATE request_log SET state = 'forwarding' WHERE id = :i"), {"i": rid})
            raise AssertionError("illegal transition accepted")
        except Exception as exc:  # noqa: BLE001
            assert "not allowed" in str(exc)


def test_connection_must_match_route_region(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    west = world.aws_conn(t, region="ca-west-1")
    c = world.console(member(t))
    r = c.post(f"/api/projects/{t.project_id}/routes", headers={"Idempotency-Key": "w"},
               json={"connection_id": str(west), "route_id": HAIKU, "alias": "haiku"})
    assert r.status_code == 422
    with world.owner() as s:
        assert s.execute(select(ProviderConnection).where(ProviderConnection.id == west)).scalar_one()
    assert GPT4O.startswith("azure:")

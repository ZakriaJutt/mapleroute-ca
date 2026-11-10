"""Verification and the two mismatch kinds: UT-06, IT-05, IT-10 (rows only), IT-21 (3 variants), IT-22."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from core.fakes import FakeAwsAccount, canadian_profile
from core.models import Alert, Binding, Job, RequestLog, Route, Verification
from core.providers import FoundationModelAnswer, InferenceProfileAnswer, LoggingAnswer, PolicyAnswer, RolePolicyAnswer
from core.verification import CheckOutcome, apply_outcome, resume_route
from core.window import azure_line
from tests.helpers import GPT4O, HAIKU, TITAN, T, World
from worker.jobs import notify_route_suspended

HOST_A = "synthetic-a.openai.azure.com"
HOST_B = "synthetic-b.openai.azure.com"
US_PROFILE = InferenceProfileAnswer(
    "ca.anthropic.claude-haiku-5-5", "SYSTEM_DEFINED",
    ("arn:aws:bedrock:ca-central-1::foundation-model/anthropic.claude-haiku-5-5",
     "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-5-5"),
)


def binding(world: World, binding_id: uuid.UUID) -> Binding:
    with world.owner() as s:
        b = s.get(Binding, binding_id)
        assert b is not None
        return b


def route(world: World, route_id: str) -> Route:
    with world.owner() as s:
        r = s.get(Route, route_id)
        assert r is not None
        return r


def code_of(resp: object) -> str:
    r = resp  # httpx.Response
    return "ok" if r.status_code == 200 else r.json()["error"]["code"]  # type: ignore[attr-defined]


def azure_tenant(world: World, name: str, host: str) -> tuple[T, uuid.UUID]:
    t = world.tenant(name)
    conn = world.azure_conn(t, host)
    world.azure_deployment(host, "gpt4o-prod")
    b = world.bind(t, conn, GPT4O, "gpt-4o", deployment_name="gpt4o-prod")
    return t, b


# ----------------------------------------------------------------------------- IT-05
def test_it05a_bedrock_binding_matched_25_hours_ago_rejects(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    b = world.bind(t, world.aws_conn(t), HAIKU, "haiku")
    assert world.verify(t, b).result == "match"
    gw = world.gateway()
    world.clock.advance(hours=24)
    assert code_of(world.chat(gw, t.key, "haiku")) == "ok"
    world.clock.advance(hours=1)
    assert code_of(world.chat(gw, t.key, "haiku")) == "route_unverified"
    assert len(world.inference.calls) == 1


def test_it05b_customer_side_mismatch_unverifies_that_binding_only(world: World) -> None:
    world.activate()
    a, ba = azure_tenant(world, "alpha", HOST_A)
    b, bb = azure_tenant(world, "bravo", HOST_B)
    assert world.verify(a, ba).result == "match" and world.verify(b, bb).result == "match"
    world.clock.advance(minutes=15)
    world.azure_reader.recreate(HOST_A, "gpt4o-prod", "GlobalStandard", world.clock() - timedelta(minutes=5))
    applied = world.verify(a, ba)
    assert applied.result == "config_mismatch"
    assert binding(world, ba).status == "unverified"
    assert binding(world, bb).status == "verified"
    assert route(world, GPT4O).global_status == "active"
    gw = world.gateway()
    assert code_of(world.chat(gw, a.key, "gpt-4o")) == "route_unverified"
    assert code_of(world.chat(gw, b.key, "gpt-4o")) == "ok"
    with world.owner() as s:
        alerts = [tuple(r) for r in s.execute(select(Alert.tenant_id, Alert.kind)).all()]
    assert alerts == [(a.tenant_id, "config_mismatch")]


def suspended_world(world: World) -> tuple[T, T, uuid.UUID, uuid.UUID]:
    world.activate()
    a, b = world.tenant("alpha"), world.tenant("bravo")
    ba = world.bind(a, world.aws_conn(a), HAIKU, "haiku")
    bb = world.bind(b, world.aws_conn(b), HAIKU, "haiku")
    assert world.verify(a, ba).result == "match" and world.verify(b, bb).result == "match"
    world.clock.advance(hours=6)
    role_a = next(k for k, v in world.aws_reader.accounts.items() if k)  # first account belongs to alpha
    world.aws_reader.accounts[role_a].profiles["ca.anthropic.claude-haiku-5-5"] = US_PROFILE
    applied = world.verify(a, ba)
    assert applied.result == "definition_mismatch" and applied.route_suspended
    return a, b, ba, bb


def test_it05c_provider_definition_mismatch_suspends_route_for_all_tenants(world: World) -> None:
    a, b, ba, bb = suspended_world(world)
    assert route(world, HAIKU).global_status == "suspended"
    assert binding(world, bb).status == "verified"  # the binding is not the cause; the route is
    gw = world.gateway()
    for t in (a, b):
        r = world.chat(gw, t.key, "haiku")
        assert r.status_code == 503 and r.json()["error"]["code"] == "route_suspended"
        assert r.json()["error"]["forwarded"] is False
    assert world.inference.calls == []
    assert [p[0] for p in world.pager.pages] == ["route_suspended"]


def test_it10_suspension_alerts_every_bound_tenant_once(world: World) -> None:
    a, b, _, _ = suspended_world(world)
    with world.owner() as s:
        job = s.execute(select(Job).where(Job.kind == "notify_route_suspended")).scalar_one()
        payload = job.payload
    with world.app.begin() as s:
        assert notify_route_suspended(s, payload) == 2
    with world.app.begin() as s:
        assert notify_route_suspended(s, payload) == 0  # de-duplicated: one alert, not many
    with world.owner() as s:
        kinds = sorted((str(t), k) for t, k in s.execute(select(Alert.tenant_id, Alert.kind)).all())
    assert kinds == sorted([(str(a.tenant_id), "route_suspended"), (str(b.tenant_id), "route_suspended")])


def test_it05d_resume_refused_until_a_newer_match_exists(world: World) -> None:
    a, b, ba, bb = suspended_world(world)
    op = world.operator()
    with pytest.raises(Exception, match="cannot resume"), world.ops.begin() as s:
        resume_route(s, HAIKU, op, world.clock())
    assert route(world, HAIKU).global_status == "suspended"
    world.clock.advance(minutes=30)
    assert world.verify(b, bb).result == "match"  # a newer match from an account that reads correctly
    with world.ops.begin() as s:
        resume_route(s, HAIKU, op, world.clock())
    assert route(world, HAIKU).global_status == "active"


def test_ut06_late_match_after_mismatch_leaves_route_suspended(world: World) -> None:
    world.activate()
    a = world.tenant("alpha")
    ba = world.bind(a, world.aws_conn(a), HAIKU, "haiku")
    world.clock.t = world.clock.t.replace(hour=9, minute=0)
    assert world.verify(a, ba).result == "match"
    world.clock.t = world.clock.t.replace(hour=10, minute=0)
    role = next(iter(world.aws_reader.accounts))
    world.aws_reader.accounts[role].profiles["ca.anthropic.claude-haiku-5-5"] = US_PROFILE
    assert world.verify(a, ba).result == "definition_mismatch"
    late_at = world.clock.t.replace(hour=9, minute=55)
    with world.app.begin() as s:
        s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a.tenant_id)})
        row = s.execute(select(Binding).where(Binding.id == ba).with_for_update()).scalar_one()
        applied = apply_outcome(s, row, CheckOutcome("match"), late_at, "2026.11.10-1", world.pager)
    assert applied.applied is False
    assert route(world, HAIKU).global_status == "suspended"
    assert binding(world, ba).last_checked_at == world.clock.t.replace(hour=10, minute=0)
    with pytest.raises(Exception, match="cannot resume"), world.ops.begin() as s:
        resume_route(s, HAIKU, world.operator(), world.clock())


def test_access_failed_and_error_never_count_as_a_pass(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    conn = world.aws_conn(t)
    b = world.bind(t, conn, HAIKU, "haiku")
    role = next(iter(world.aws_reader.accounts))
    world.aws_reader.accounts[role].deny_access = True
    assert world.verify(t, b).result == "access_failed"
    world.aws_reader.accounts[role].deny_access = False
    world.aws_reader.accounts[role].raise_error = True
    world.clock.advance(minutes=1)
    assert world.verify(t, b).result == "error"
    assert binding(world, b).status == "unverified"
    assert code_of(world.chat(world.gateway(), t.key, "haiku")) == "route_unverified"


# ----------------------------------------------------------------------------- IT-22
def test_it22_missing_l2_us_logging_and_broad_role_never_verified(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    az = world.azure_conn(t, HOST_A)
    dep = world.azure_deployment(HOST_A, "gpt4o-prod")
    dep.policy = PolicyAnswer(False, False, False)
    b1 = world.bind(t, az, GPT4O, "gpt-4o", deployment_name="gpt4o-prod")
    logging_us = FakeAwsAccount(
        profiles={"ca.anthropic.claude-haiku-5-5": canadian_profile("ca.anthropic.claude-haiku-5-5")},
        logging=LoggingAnswer("on", "s3://synthetic-invocation-logs", "us-east-1"))
    b2 = world.bind(t, world.aws_conn(t, account=logging_us), HAIKU, "haiku")
    broad = FakeAwsAccount(
        models={"amazon.titan-embed-text-v2:0": FoundationModelAnswer("amazon.titan-embed-text-v2:0", True, True)},
        role=RolePolicyAnswer(False, False, True))
    b3 = world.bind(t, world.aws_conn(t, account=broad), TITAN, "titan")
    expected = {b1: "l2_missing", b2: "logging_outside_canada", b3: "role_too_broad"}
    for bid, reason in expected.items():
        applied = world.verify(t, bid)
        assert applied.result == "config_mismatch"
        assert binding(world, bid).status == "unverified"
        with world.owner() as s:
            reasons = s.execute(select(Verification.reason).where(Verification.binding_id == bid)).scalar_one()
        assert reason in str(reasons).split(",")


# ----------------------------------------------------------------------------- IT-21
def it21_setup(world: World) -> tuple[T, uuid.UUID]:
    world.activate()
    t, b = azure_tenant(world, "alpha", HOST_A)
    assert world.verify(t, b).result == "match"  # 10:00, last matching check
    return t, b


def served(world: World) -> list[tuple[str, list[str]]]:
    with world.owner() as s:
        return [(r.state, list(r.flags)) for r in s.execute(
            select(RequestLog).order_by(RequestLog.received_at)).scalars()]


def test_it21_variant1_swap_detected_at_next_check_and_window_flagged(world: World) -> None:
    t, b = it21_setup(world)
    gw = world.gateway()
    start = world.clock()
    world.clock.advance(minutes=5)
    world.azure_reader.remove_deny_policy(HOST_A, "gpt4o-prod", world.clock())
    world.azure_reader.recreate(HOST_A, "gpt4o-prod", "GlobalStandard", world.clock())
    for minutes in (1, 4):  # 10:06, 10:10: requests keep flowing; nothing has re-read yet
        world.clock.advance(minutes=minutes)
        assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"
    world.clock.advance(minutes=5)  # 10:15 check
    applied = world.verify(t, b)
    assert applied.result == "config_mismatch" and applied.flagged_requests == 2
    with world.owner() as s:
        reasons = set(str(s.execute(select(Verification.reason).where(
            Verification.result == "config_mismatch")).scalar_one()).split(","))
    assert {"sku_not_eligible", "l2_missing", "deployment_recreated", "activity_change"} <= reasons
    world.clock.advance(minutes=1)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "route_unverified"
    assert served(world) == [("completed", ["config_changed_window"])] * 2 + [("rejected", [])]
    with world.app.begin() as s:
        s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)})
        line = azure_line(s, b, start, world.clock() + timedelta(seconds=1))
    assert (line.matching_checks, line.failed_checks, line.flagged_requests) == (1, 0, 2)
    assert line.longest_served_since_match == timedelta(minutes=10)
    assert "continuously" not in line.text() and "matched at each check" in line.text()


@pytest.mark.parametrize("activity_visible", [True, False])
def test_it21_variant2_swap_and_restore_caught_from_timestamps_or_activity(world: World,
                                                                         activity_visible: bool) -> None:
    t, b = it21_setup(world)
    gw = world.gateway()
    world.clock.advance(minutes=3)
    world.azure_reader.remove_deny_policy(HOST_A, "gpt4o-prod", world.clock())
    world.azure_reader.recreate(HOST_A, "gpt4o-prod", "GlobalStandard", world.clock())
    world.clock.advance(minutes=1)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"  # 10:04, served while Global
    world.clock.advance(minutes=4)
    world.azure_reader.recreate(HOST_A, "gpt4o-prod", "Standard", world.clock())  # 10:08: reversed
    world.azure_reader.restore_deny_policy(HOST_A, "gpt4o-prod", world.clock())
    if not activity_visible:  # O-13: the reader may not see activity-log events; timestamps still catch it
        world.azure_reader.deployments[(HOST_A, "gpt4o-prod")].events.clear()
    world.clock.advance(minutes=1)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"  # 10:09
    world.clock.advance(minutes=6)  # 10:15
    applied = world.verify(t, b)
    assert applied.result == "config_mismatch" and applied.flagged_requests == 2
    with world.owner() as s:
        reasons = set(str(s.execute(select(Verification.reason).where(
            Verification.result == "config_mismatch")).scalar_one()).split(","))
    assert "deployment_recreated" in reasons
    assert ("activity_change" in reasons) is activity_visible
    assert "sku_not_eligible" not in reasons and "l2_missing" not in reasons
    # The next check re-baselines on the restored deployment and matches again.
    world.clock.advance(minutes=15)
    assert world.verify(t, b).result == "match"
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"


def test_it21_variant3_checks_fail_after_swap_requests_flow_until_60_minutes(world: World) -> None:
    t, b = it21_setup(world)
    gw = world.gateway()
    start = world.clock()
    world.clock.advance(minutes=5)
    world.azure_reader.remove_deny_policy(HOST_A, "gpt4o-prod", world.clock())
    world.azure_reader.recreate(HOST_A, "gpt4o-prod", "GlobalStandard", world.clock())
    world.azure_reader.deployments[(HOST_A, "gpt4o-prod")].deny_access = True  # every later check fails
    results: list[str] = []
    alerts_after: list[list[str]] = []
    for _ in range(3):  # 10:15, 10:30, 10:45
        world.clock.t = world.clock.t.replace(minute=0) + timedelta(minutes=15 * (len(results) + 1))
        results.append(world.verify(t, b).result)
        with world.owner() as s:
            alerts_after.append(list(s.execute(select(Alert.kind)).scalars().all()))
    assert results == ["access_failed"] * 3
    assert alerts_after == [[], ["access_failed"], ["access_failed"]]  # after the second failed check, once
    assert [p[0] for p in world.pager.pages] == ["access_failed"]
    assert binding(world, b).status == "verified"  # no status change on a failed check
    world.clock.t = start + timedelta(minutes=59)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"
    world.clock.t = start + timedelta(minutes=60)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"  # validity is inclusive: 60 minutes exactly
    world.clock.t = start + timedelta(minutes=60, seconds=1)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "route_unverified"
    with world.app.begin() as s:
        s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)})
        line = azure_line(s, b, start, world.clock() + timedelta(seconds=1))
    assert (line.matching_checks, line.failed_checks, line.flagged_requests) == (1, 3, 0)
    assert line.longest_served_since_match == timedelta(minutes=60)
    assert "60 minutes (limit 60)" in line.text()

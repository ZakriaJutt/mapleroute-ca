"""B1-003 / B1-012 fix round 3: one check of a binding at a time, and asymmetric ordering.

Rule 1: a check holds its binding's lease (``binding_check_lease``) for its whole run, provider
reads included; a second check is skipped; a lease past ``CHECK_LEASE`` is taken over.
Rule 2: any mismatch un-verifies, whatever its timing; a match re-verifies only if its check still
holds the lease and started after the latest recorded mismatch.

Also B1-005 part: the console cannot create or squat another tenant's scheduled-check key.
Synthetic data only.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from core import jobs, locks
from core.config import CHECK_LEASE
from core.models import Binding, BindingCheckLease, Job, RequestLog, Verification
from core.providers import AzureTarget, DeploymentAnswer
from core.verification import Applied, CheckOutcome, apply_outcome
from tests.helpers import CONSOLE_URL, GPT4O, HAIKU, WORKER_URL, T, World
from worker.jobs import CheckInProgress, run_job, schedule_verifications, verify_binding

HOST = "synthetic-a.openai.azure.com"
DEP = "gpt4o-prod"
PAST_LEASE = CHECK_LEASE + timedelta(seconds=5)


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


def check(world: World, t: T, b: uuid.UUID) -> Applied:
    with world.app.begin() as s:
        return verify_binding(s, world.worker_services(), t.tenant_id, b, world.clock())


def binding_row(world: World, b: uuid.UUID) -> Binding:
    with world.owner() as s:
        row = s.get(Binding, b)
        assert row is not None
        return row


def flags(world: World) -> list[list[str]]:
    with world.owner() as s:
        return [list(r.flags) for r in s.execute(select(RequestLog).order_by(RequestLog.received_at)).scalars()]


def lease_rows(world: World) -> int:
    with world.owner() as s:
        return int(s.execute(select(text("count(*)")).select_from(BindingCheckLease)).scalar_one())


# ------------------------------------------------------------------------- R1 (reviewer, round 3)
def test_r1_mismatch_read_after_the_verifying_match_unverifies(world: World) -> None:
    """Reviewer case R1. Check A starts 10:15:00, its deployment read is slow; check B is attempted at
    10:15:05 while A runs; the deployment becomes Global at 10:15:07; A's read answers 10:15:08.
    B never overlaps A (skipped); A's mismatch un-verifies; the next request is rejected."""
    t, b = azure_setup(world)
    gw = world.gateway()
    world.clock.advance(minutes=15)
    reader = world.azure_reader
    orig = reader.get_deployment
    st: dict[str, Any] = {"depth": 0}

    def slow(target: AzureTarget) -> DeploymentAnswer:
        st["depth"] += 1
        if st["depth"] == 1:
            world.clock.advance(seconds=5)
            st["b"] = check(world, t, b)
            world.clock.advance(seconds=2)
            reader.recreate(HOST, DEP, "GlobalStandard", world.clock())
            world.clock.advance(seconds=1)
        return orig(target)

    reader.get_deployment = slow  # type: ignore[method-assign]
    a = check(world, t, b)
    reader.get_deployment = orig  # type: ignore[method-assign]
    world.clock.advance(seconds=30)
    assert st["b"].result == "skipped" and st["b"].applied is False
    assert a.result == "config_mismatch" and a.applied
    assert binding_row(world, b).status == "unverified"
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "route_unverified"
    assert lease_rows(world) == 0


def test_r1_overlap_after_lease_expiry_mismatch_still_unverifies(world: World) -> None:
    """R1 with a real overlap: A's slow read outlives its lease, B takes the lease over, reads Standard
    and verifies; the deployment turns Global; A's read sees Global. A lost its lease, but a mismatch
    always applies: the binding is un-verified and the request served after B is flagged."""
    t, b = azure_setup(world)
    gw = world.gateway()
    world.clock.advance(minutes=15)
    reader = world.azure_reader
    orig = reader.get_deployment
    st: dict[str, Any] = {"depth": 0}

    def slow(target: AzureTarget) -> DeploymentAnswer:
        st["depth"] += 1
        if st["depth"] == 1:
            world.clock.advance(seconds=PAST_LEASE.total_seconds())
            st["b"] = check(world, t, b)  # takes over the expired lease
            world.clock.advance(seconds=1)
            st["served"] = code_of(world.chat(gw, t.key, "gpt-4o"))
            world.clock.advance(seconds=1)
            reader.recreate(HOST, DEP, "GlobalStandard", world.clock())
            world.clock.advance(seconds=1)
        return orig(target)

    reader.get_deployment = slow  # type: ignore[method-assign]
    a = check(world, t, b)
    reader.get_deployment = orig  # type: ignore[method-assign]
    assert st["b"].result == "match" and st["b"].applied and st["served"] == "ok"
    assert a.result == "config_mismatch" and a.applied
    assert binding_row(world, b).status == "unverified"
    assert flags(world) == [["config_changed_window"]]
    world.clock.advance(seconds=30)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "route_unverified"


def test_n3_match_of_a_check_that_lost_its_lease_never_re_verifies(world: World) -> None:
    """N3 under the new design. A reads Standard, its last read outlives the lease; the deployment
    turns Global; B takes the lease, sees Global, un-verifies. A's match arrives last: not applied."""
    t, b = azure_setup(world)
    gw = world.gateway()
    world.clock.advance(minutes=15)
    reader = world.azure_reader
    orig = reader.get_diagnostic_logging
    st: dict[str, Any] = {"inside": False}

    def slow_logging(target: AzureTarget):  # type: ignore[no-untyped-def]
        if not st["inside"]:
            st["inside"] = True
            world.clock.advance(seconds=PAST_LEASE.total_seconds())
            reader.recreate(HOST, DEP, "GlobalStandard", world.clock())
            st["b"] = check(world, t, b)
            world.clock.advance(seconds=1)
            st["mid"] = code_of(world.chat(gw, t.key, "gpt-4o"))
        return orig(target)

    reader.get_diagnostic_logging = slow_logging  # type: ignore[method-assign]
    a = check(world, t, b)
    reader.get_diagnostic_logging = orig  # type: ignore[method-assign]
    assert st["b"].result == "config_mismatch" and st["b"].applied and st["mid"] == "route_unverified"
    assert a.result == "match" and a.applied is False
    world.clock.advance(minutes=1)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "route_unverified"
    assert binding_row(world, b).status == "unverified"


# ------------------------------------------------------------------------- three concurrent checks
def test_three_concurrent_checks_never_overlap(world: World) -> None:
    """Three worker threads check one binding at once. Exactly one reads the provider; the other two
    are skipped without reading; at no moment are two checks inside provider reads."""
    t, b = azure_setup(world)
    world.clock.advance(minutes=15)
    reader = world.azure_reader
    orig = reader.get_deployment
    guard = threading.Lock()
    inside = {"now": 0, "max": 0, "reads": 0}
    entered, release = threading.Event(), threading.Event()

    def blocking(target: AzureTarget) -> DeploymentAnswer:
        with guard:
            inside["now"] += 1
            inside["reads"] += 1
            inside["max"] = max(inside["max"], inside["now"])
        entered.set()
        release.wait(10)
        with guard:
            inside["now"] -= 1
        return orig(target)

    reader.get_deployment = blocking  # type: ignore[method-assign]
    results: dict[int, Applied] = {}

    def worker(i: int) -> None:
        results[i] = check(world, t, b)

    first = threading.Thread(target=worker, args=(1,))
    first.start()
    assert entered.wait(10)
    others = [threading.Thread(target=worker, args=(i,)) for i in (2, 3)]
    for th in others:
        th.start()
    for th in others:
        th.join(10)
    assert {results[2].result, results[3].result} == {"skipped"}  # skipped while 1 holds the lease
    release.set()
    first.join(10)
    reader.get_deployment = orig  # type: ignore[method-assign]
    assert results[1].result == "match" and results[1].applied
    assert inside == {"now": 0, "max": 1, "reads": 1}
    with world.owner() as s:
        assert s.execute(select(text("count(*)")).select_from(Verification)).scalar_one() == 2  # setup + 1
    assert lease_rows(world) == 0
    assert check(world, t, b).result == "match"  # the lease was released: the next check runs


# ------------------------------------------------------------------------- lease expiry
def test_worker_dies_mid_check_lease_expires_then_checks_resume(world: World) -> None:
    """A worker claims the lease and dies during its reads (never releases). Checks are skipped, and
    the job is retried, until the lease expires; then a check takes the lease over and runs."""
    t, b = azure_setup(world)
    world.clock.advance(minutes=15)
    with world.app() as s:
        dead = locks.claim_check(s, t.tenant_id, b, world.clock())
    assert dead is not None and lease_rows(world) == 1
    world.clock.advance(seconds=CHECK_LEASE.total_seconds() - 5)
    assert check(world, t, b).result == "skipped"
    with world.app.begin() as s:
        jobs.enqueue(s, "verify_binding", f"{b}:manual:retry", tenant_id=t.tenant_id,
                     payload={"binding_id": str(b)}, run_after=world.clock())
    with world.app.begin() as s, pytest.raises(CheckInProgress):
        job = jobs.claim(s, world.clock())
        assert job is not None
        run_job(s, world.worker_services(), job, world.clock())
    world.clock.advance(seconds=10)  # past the dead worker's lease
    taken = check(world, t, b)
    assert taken.result == "match" and taken.applied
    assert lease_rows(world) == 0
    assert binding_row(world, b).last_verified_at == world.clock()
    with world.app.begin() as s:  # the dead holder's late release removes nothing of the new holder's
        s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)})
        assert locks.holds_check(s, dead) is False


# ------------------------------------------------------------------------- rule 2 directly
def _apply(world: World, t: T, b: uuid.UUID, outcome: CheckOutcome, started: datetime, checked: datetime,
           holds: bool) -> Applied:
    with world.app.begin() as s:
        s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)})
        row = s.execute(select(Binding).where(Binding.id == b).with_for_update()).scalar_one()
        return apply_outcome(s, row, outcome, checked, "2026.11.10-1", world.pager, reads_started_at=started,
                             holds_lease=holds, recorded_at=checked)


def test_mismatch_older_than_the_verifying_match_still_unverifies_and_flags(world: World) -> None:
    t, b = azure_setup(world)  # match started 10:00
    gw = world.gateway()
    world.clock.advance(minutes=5)
    assert code_of(world.chat(gw, t.key, "gpt-4o")) == "ok"  # 10:05 served
    started_old = world.clock()
    world.clock.advance(minutes=10)
    assert check(world, t, b).result == "match"  # 10:15 verifies
    late = _apply(world, t, b, CheckOutcome("config_mismatch", ("sku_not_eligible",)), started_old,
                  world.clock() + timedelta(seconds=30), holds=False)
    assert late.applied and late.flagged_requests == 1
    assert binding_row(world, b).status == "unverified"
    assert flags(world) == [["config_changed_window"]]


def test_match_must_start_after_the_latest_recorded_mismatch(world: World) -> None:
    t, b = azure_setup(world)
    world.clock.advance(minutes=15)
    recorded = world.clock()
    assert _apply(world, t, b, CheckOutcome("config_mismatch", ("sku_not_eligible",)), recorded,
                  recorded, holds=True).applied
    assert binding_row(world, b).last_mismatch_at == recorded
    for started in (recorded - timedelta(seconds=1), recorded):  # before or at the fence: refused
        late = _apply(world, t, b, CheckOutcome("match"), started, recorded + timedelta(seconds=5), holds=True)
        assert late.applied is False
    lost = _apply(world, t, b, CheckOutcome("match"), recorded + timedelta(seconds=1),
                  recorded + timedelta(seconds=5), holds=False)
    assert lost.applied is False  # a check that lost its lease never re-verifies
    assert binding_row(world, b).status == "unverified"
    newer = _apply(world, t, b, CheckOutcome("match"), recorded + timedelta(seconds=1),
                   recorded + timedelta(seconds=5), holds=True)
    assert newer.applied and binding_row(world, b).status == "verified"


# ------------------------------------------------------------------------- B1-005 part (R3)
def _as(url: str, sql: str, params: dict[str, Any], tenant: uuid.UUID) -> str:
    eng = create_engine(url)
    try:
        with eng.begin() as c:
            c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
            c.execute(text(sql), params)
        return "allowed"
    except DBAPIError as exc:
        return str(getattr(exc.orig, "sqlstate", None))
    finally:
        eng.dispose()


def test_console_cannot_create_or_squat_another_tenants_scheduled_key(world: World) -> None:
    world.activate()
    a, b = world.tenant("alpha"), world.tenant("bravo")
    ba = world.bind(a, world.aws_conn(a), HAIKU, "haiku")
    bb = world.bind(b, world.aws_conn(b), HAIKU, "haiku")
    assert world.verify(b, bb).result == "match"
    world.clock.advance(minutes=15)
    slot = int(world.clock().timestamp() // (6 * 3600))
    ins = ("INSERT INTO job (kind, dedupe_key, tenant_id, payload) "
           "VALUES ('verify_binding', :d, :t, CAST(:p AS jsonb))")

    def p(binding: uuid.UUID) -> str:
        return json.dumps({"binding_id": str(binding)})

    attempts = {
        "B's scheduled key, A's tenant": _as(CONSOLE_URL, ins, {"d": f"{bb}:{slot}", "t": a.tenant_id, "p": p(bb)},
                                             a.tenant_id),
        "B's scheduled key, B's tenant": _as(CONSOLE_URL, ins, {"d": f"{bb}:{slot}", "t": b.tenant_id, "p": p(bb)},
                                             a.tenant_id),
        "manual key naming B's binding": _as(CONSOLE_URL, ins, {"d": f"{bb}:manual:x", "t": a.tenant_id,
                                                                "p": p(bb)}, a.tenant_id),
        "own scheduled-slot key": _as(CONSOLE_URL, ins, {"d": f"{ba}:{slot}", "t": a.tenant_id, "p": p(ba)},
                                      a.tenant_id),
        "key not naming the payload's binding": _as(CONSOLE_URL, ins, {"d": f"{bb}:manual:x", "t": a.tenant_id,
                                                                       "p": p(ba)}, a.tenant_id),
    }
    assert set(attempts.values()) == {"42501"}, attempts  # row-level security refuses every one
    assert _as(CONSOLE_URL, ins, {"d": f"{ba}:manual:k1", "t": a.tenant_id, "p": p(ba)}, a.tenant_id) == "allowed"
    # The constraint holds for the worker too: a verify_binding key must name the job's own binding.
    assert _as(WORKER_URL, ins, {"d": f"{bb}:{slot}", "t": a.tenant_id, "p": p(ba)}, a.tenant_id) == "23514"
    with world.app.begin() as s:
        schedule_verifications(s, world.clock())
    with world.owner() as s:
        owners = [str(j.tenant_id) for j in s.execute(select(Job).where(Job.dedupe_key == f"{bb}:{slot}")).scalars()]
    assert owners == [str(b.tenant_id)]  # B's scheduled check was enqueued, for B

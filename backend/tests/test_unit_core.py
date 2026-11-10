"""Pure unit tests: forwardable (MH-03, MH-04 validity), Decision sealing, UT-05, UT-07, UT-10."""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from core import logging as mr_logging
from core.allowlist import build_version, load_verified
from core.eligibility import BindingState, Decision, Rejection, evaluate
from core.errors import CONTRACT, Code, error_body
from core.regions import ArnError, regions_of_arns
from core.requestlog import STATES, allowed
from core.secretvalue import SecretValue
from gateway.forward import forward
from tests.helpers import fixture_routes

NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
DOC = load_verified("2026.11.10-1", *build_version("2026.11.10-1", fixture_routes()))
KEYS = {e.id: e.key for e in DOC.entries.values()}


def state(route_id: str, **kw: object) -> BindingState:
    key = KEYS[route_id]
    base: dict[str, object] = dict(
        binding_id=uuid.uuid4(), tenant_id=uuid.uuid4(), project_id=uuid.uuid4(), alias="m", route=key,
        route_global_status="active", status="verified", last_verified_at=NOW - timedelta(minutes=5),
        deployment_name="dep-1" if key.provider == "azure" else None, connection_id=uuid.uuid4(),
        connection_provider=key.provider, connection_region=key.source_region, connection_state="connected",
        endpoint_host="synthetic.openai.azure.com" if key.provider == "azure" else None,
    )
    base.update(kw)
    return BindingState(**base)  # type: ignore[arg-type]


AWS = "aws:ca-central-1:geo_ca:ca.anthropic.claude-haiku-5-5"
AZ = "azure:canadaeast:Standard:gpt-4o:2024-11-20"


def code(result: Decision | Rejection) -> str:
    return "forward" if isinstance(result, Decision) else result.code.value


def test_forwardable_happy_paths_bind_host_and_identifier() -> None:
    d = evaluate(state(AWS), DOC, NOW)
    assert isinstance(d, Decision)
    assert (d.upstream_host, d.upstream_identifier) == ("bedrock-runtime.ca-central-1.amazonaws.com",
                                                        "ca.anthropic.claude-haiku-5-5")
    a = evaluate(state(AZ), DOC, NOW)
    assert isinstance(a, Decision)
    # Azure host and deployment name come from the connection and binding, never from the route.
    assert (a.upstream_host, a.upstream_identifier) == ("synthetic.openai.azure.com", "dep-1")


@pytest.mark.parametrize(("route", "age", "expected"), [
    (AWS, timedelta(hours=24), "forward"),
    (AWS, timedelta(hours=24, seconds=1), "route_unverified"),
    (AZ, timedelta(minutes=60), "forward"),
    (AZ, timedelta(minutes=60, seconds=1), "route_unverified"),
])
def test_validity_bound_24h_bedrock_1h_azure(route: str, age: timedelta, expected: str) -> None:
    assert code(evaluate(state(route, last_verified_at=NOW - age), DOC, NOW)) == expected


@pytest.mark.parametrize(("kw", "expected"), [
    ({"status": "unverified"}, "route_unverified"),
    ({"last_verified_at": None}, "route_unverified"),
    ({"last_verified_at": NOW + timedelta(minutes=5)}, "route_unverified"),
    ({"route_global_status": "suspended"}, "route_suspended"),
    ({"connection_state": "deleted"}, "route_not_eligible"),
    ({"connection_region": "ca-west-1"}, "route_not_eligible"),
    ({"connection_provider": "azure"}, "route_not_eligible"),
])
def test_every_failure_rejects(kw: dict[str, object], expected: str) -> None:
    assert code(evaluate(state(AWS, **kw), DOC, NOW)) == expected


def test_no_version_or_no_binding_rejects() -> None:
    assert code(evaluate(state(AWS), None, NOW)) == "policy_unavailable"
    assert code(evaluate(None, DOC, NOW)) == "route_not_eligible"
    smaller = load_verified("2026.11.11-1", *build_version(
        "2026.11.11-1", [r for r in fixture_routes() if r["id"] != AWS]))
    assert code(evaluate(state(AWS), smaller, NOW)) == "route_not_eligible"


def test_decision_cannot_be_built_outside_the_evaluator() -> None:
    with pytest.raises(TypeError):
        Decision(uuid.uuid4(), uuid.uuid4(), AWS, "aws", "ca-central-1", "h", "i", "v", "active", NOW)
    with pytest.raises(TypeError):
        forward({}, object(), "chat", {}, SecretValue("x"))  # type: ignore[arg-type]


def test_error_contract_forwarded_flag() -> None:
    for c, contract in CONTRACT.items():
        body = error_body(c, request_id="r", allowlist_version="v")["error"]
        assert body["forwarded"] is contract.forwarded
        assert body["forwarded"] is (c in (Code.UPSTREAM_ERROR, Code.UPSTREAM_TIMEOUT))
        assert set(body) >= {"type", "code", "message", "param", "request_id", "allowlist_version", "forwarded"}


def test_ut05_only_listed_transitions() -> None:
    ok = {("forwarding", s) for s in ("completed", "upstream_error", "client_aborted", "unknown_outcome")} | {
        ("unknown_outcome", "completed"), ("unknown_outcome", "upstream_error")}
    for old in STATES:
        for new in STATES:
            assert allowed(old, new) is ((old, new) in ok), (old, new)


def test_ut07_body_and_authorization_never_logged() -> None:
    stream = io.StringIO()
    mr_logging.configure(stream)
    mr_logging.log_event("request_completed", request_id="r1", body={"messages": "CANARY-UT07-BODY"},
                         authorization="Bearer CANARY-UT07-KEY", headers={"api-key": "CANARY-UT07-H"},
                         provider_message="CANARY-UT07-PROV", code="ok")
    out = stream.getvalue()
    assert "CANARY" not in out
    line = json.loads(out)
    assert line["event"] == "request_completed" and line["request_id"] == "r1"
    assert repr(SecretValue("CANARY-SECRET")) == "SecretValue(***)"


def test_ut07_correlation_id_on_every_line() -> None:
    stream = io.StringIO()
    mr_logging.configure(stream)
    with mr_logging.correlation("req-123"):
        mr_logging.log_event("a")
    assert json.loads(stream.getvalue())["correlation_id"] == "req-123"


def test_ut10_three_model_arns_give_three_regions() -> None:
    arns = [
        "arn:aws:bedrock:ca-central-1::foundation-model/anthropic.claude-sonnet-5-5",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-5-5",
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-5-5",
    ]
    assert regions_of_arns(arns) == {"ca-central-1", "us-east-1", "us-west-2"}
    with pytest.raises(ArnError):
        regions_of_arns(["arn:aws:s3:::bucket"])

"""Gateway fail-closed path: UT-04, IT-01, IT-02 (simulated disconnect), IT-03, IT-04, error mapping."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import sessionmaker

from core.models import ApiKey, ProviderConnection, RequestLog, Route
from tests.helpers import GPT4O, HAIKU, TITAN, T, World

HOST = "synthetic-a.openai.azure.com"


def verified_world(world: World) -> tuple[T, dict[str, uuid.UUID]]:
    world.activate()
    t = world.tenant("alpha")
    aws = world.aws_conn(t)
    az = world.azure_conn(t, HOST)
    world.azure_deployment(HOST, "gpt4o-prod")
    ids = {
        "haiku": world.bind(t, aws, HAIKU, "haiku"),
        "titan": world.bind(t, aws, TITAN, "titan-embed"),
        "gpt4o": world.bind(t, az, GPT4O, "gpt-4o", deployment_name="gpt4o-prod"),
    }
    for b in ids.values():
        assert world.verify(t, b).result == "match"
    return t, ids


def rows(world: World) -> list[RequestLog]:
    with world.owner() as s:
        return list(s.execute(select(RequestLog).order_by(RequestLog.received_at)).scalars())


def test_it01_eligible_request_forwarded_once_and_logged(world: World) -> None:
    t, _ = verified_world(world)
    gw = world.gateway()
    r = world.chat(gw, t.key, "haiku")
    assert r.status_code == 200, r.text
    assert r.headers["X-MapleRoute-Route"] == HAIKU
    assert r.headers["X-MapleRoute-Allowlist-Version"] == "2026.11.10-1"
    assert [c.identifier for c in world.inference.calls] == ["ca.anthropic.claude-haiku-5-5"]
    [row] = rows(world)
    assert (row.state, row.route_id, row.allowlist_version, row.route_status) == (
        "completed", HAIKU, "2026.11.10-1", "active")
    assert row.binding_verified_at is not None and row.input_tokens == 3
    assert str(row.id) == r.headers["X-MapleRoute-Request-Id"]

    az = world.chat(gw, t.key, "gpt-4o")
    assert az.status_code == 200
    assert (world.inference.calls[-1].host, world.inference.calls[-1].identifier) == (HOST, "gpt4o-prod")
    emb = gw.post("/v1/embeddings", json={"model": "titan-embed", "input": "x"},
                  headers={"Authorization": f"Bearer {t.key}"})
    assert emb.status_code == 200 and world.inference.calls[-1].endpoint == "embeddings"


def test_it01_models_lists_only_bound_forwardable_aliases(world: World) -> None:
    t, ids = verified_world(world)
    with world.owner.begin() as s:
        s.execute(update(Route).where(Route.id == TITAN).values(global_status="suspended"))
    r = world.gateway().get("/v1/models", headers={"Authorization": f"Bearer {t.key}"})
    assert [m["id"] for m in r.json()["data"]] == ["gpt-4o", "haiku"]


def test_it02_streaming_passes_chunks_and_records_client_abort(world: World) -> None:
    t, _ = verified_world(world)
    world.inference.chunks = [b"data: 1\n\n", b"data: 2\n\n", b"data: 3\n\n"]
    gw = world.gateway()
    with gw.stream("POST", "/v1/chat/completions", json={"model": "haiku", "stream": True, "messages": []},
                   headers={"Authorization": f"Bearer {t.key}"}) as r:
        assert r.status_code == 200
        assert b"".join(r.iter_bytes()) == b"data: 1\n\ndata: 2\n\ndata: 3\n\n"
    assert rows(world)[-1].state == "completed"
    # Simulated disconnect: the response iterator is closed after the first chunk.
    app = world_app(gw)
    world.inference.chunks = [b"a", b"b", b"c"]
    import asyncio

    from starlette.requests import Request

    async def run() -> Any:
        body = b'{"model":"haiku","stream":true,"messages":[]}'
        scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions", "headers": [
            (b"authorization", f"Bearer {t.key}".encode()), (b"content-type", b"application/json")],
            "query_string": b""}

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        route = next(rt for rt in app.routes if getattr(rt, "path", "") == "/v1/chat/completions")
        response = await route.endpoint(Request(scope, receive))
        iterator = response.body_iterator
        first = await iterator.__anext__()
        await iterator.aclose()
        return first

    assert asyncio.run(run()) == b"a"
    assert rows(world)[-1].state == "client_aborted"


def world_app(client: Any) -> Any:
    return client.app


def ineligible_cases(world: World, t: T, ids: dict[str, uuid.UUID]) -> list[tuple[str, dict[str, Any], str]]:
    """Fifty ineligible inputs (IT-03): (description, request body, expected code)."""
    aws2 = world.aws_conn(t)
    # Routes that exist as rows but are not on the active version: `us.` and `global.` profiles.
    with world.owner.begin() as s:
        for ident in ("us.anthropic.claude-sonnet-5-5", "global.anthropic.claude-sonnet-5-5",
                      "us.anthropic.claude-opus-5-5"):
            s.add(Route(id=f"aws:ca-central-1:geo_ca:{ident}", provider="aws", source_region="ca-central-1",
                        identifier=ident, deployment_class="geo_ca"))
    for ident in ("us.anthropic.claude-sonnet-5-5", "global.anthropic.claude-sonnet-5-5",
                  "us.anthropic.claude-opus-5-5"):
        world.bind(t, aws2, f"aws:ca-central-1:geo_ca:{ident}", f"bound-{ident}")
    # A Global Standard deployment registered under a Canadian-sounding name: never verified.
    az = world.azure_conn(t, "synthetic-b.openai.azure.com")
    world.azure_deployment("synthetic-b.openai.azure.com", "gpt-4o-canada", sku="GlobalStandard")
    g = world.bind(t, az, GPT4O, "gpt-4o-canada", deployment_name="gpt-4o-canada")
    assert world.verify(t, g).result == "config_mismatch"
    # A suspended route, an unverified binding, a stale binding, a deleted connection.
    world.bind(t, aws2, "aws:ca-central-1:in_region:cohere.embed-english-v3", "never-verified")
    aws3 = world.aws_conn(t)
    stale = world.bind(t, aws3, "aws:ca-central-1:in_region:meta.llama3-8b-instruct-v1:0", "stale")
    with world.owner.begin() as s:
        s.execute(text("UPDATE binding SET status='verified', l2_confirmed_at=now(), "
                       "last_verified_at = :t WHERE id = :b"), {"t": world.clock() - timedelta(hours=25), "b": stale})
        s.execute(update(Route).where(Route.id == TITAN).values(global_status="suspended"))
    aws4 = world.aws_conn(t)
    gone = world.bind(t, aws4, "aws:ca-central-1:in_region:meta.llama3-70b-instruct-v1:0", "deleted-conn")
    with world.owner.begin() as s:
        s.execute(text("UPDATE binding SET status='verified', l2_confirmed_at=now(), last_verified_at=:t "
                       "WHERE id=:b"), {"t": world.clock(), "b": gone})
        s.execute(update(ProviderConnection).where(ProviderConnection.id == aws4).values(state="deleted"))

    cases: list[tuple[str, dict[str, Any], str]] = []
    for i in range(13):
        cases.append((f"unbound alias {i}", {"model": f"claude-sonnet-5-5-v{i}"}, "route_not_eligible"))
    for ident in ("us.anthropic.claude-sonnet-5-5", "global.anthropic.claude-sonnet-5-5",
                  "us.anthropic.claude-opus-5-5"):
        for j in range(3):
            cases.append((f"{ident} {j}", {"model": f"bound-{ident}"}, "route_not_eligible"))
    for j in range(5):
        cases.append((f"global deployment {j}", {"model": "gpt-4o-canada"}, "route_unverified"))
    for j in range(5):
        cases.append((f"suspended {j}", {"model": "titan-embed"}, "route_suspended"))
    for j in range(3):
        cases.append((f"never verified {j}", {"model": "never-verified"}, "route_unverified"))
    for j in range(3):
        cases.append((f"stale {j}", {"model": "stale"}, "route_unverified"))
    for j in range(2):
        cases.append((f"deleted connection {j}", {"model": "deleted-conn"}, "route_not_eligible"))
    for param in ("files", "file_ids", "attachments", "batch", "background", "previous_response_id"):
        cases.append((f"param {param}", {"model": "haiku", param: ["x"]}, "unsupported_parameter"))
    cases.append(("store true", {"model": "haiku", "store": True}, "unsupported_parameter"))
    cases.append(("store true gpt", {"model": "gpt-4o", "store": True}, "unsupported_parameter"))
    cases.append(("empty model", {"model": ""}, "route_not_eligible"))
    cases.append(("model not a string", {"model": ["haiku"]}, "route_not_eligible"))
    return cases


def test_it03_fifty_ineligible_inputs_zero_outbound_calls(world: World) -> None:
    t, ids = verified_world(world)
    cases = ineligible_cases(world, t, ids)
    assert len(cases) == 50
    gw = world.gateway()
    world.inference.calls.clear()
    for desc, body, expected in cases:
        body.setdefault("messages", [{"role": "user", "content": "synthetic"}])
        r = gw.post("/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {t.key}"})
        err = r.json()["error"]
        assert err["code"] == expected, (desc, err)
        assert err["forwarded"] is False, desc
        assert r.status_code == {"route_not_eligible": 403, "route_unverified": 403, "route_suspended": 503,
                                 "unsupported_parameter": 400}[expected]
    # Malformed bodies and bad keys are also refused without a call.
    assert gw.post("/v1/chat/completions", content=b"not json", headers={
        "Authorization": f"Bearer {t.key}"}).json()["error"]["code"] == "unsupported_parameter"
    assert world.inference.calls == []
    logged = [r for r in rows(world) if r.state == "rejected"]
    assert len(logged) == 51
    assert all(r.code for r in logged)


def test_ut04_valid_revoked_malformed_keys(world: World) -> None:
    t, _ = verified_world(world)
    gw = world.gateway()
    assert world.chat(gw, t.key, "haiku").status_code == 200
    for bad in ("", "Bearer", "Bearer mr_short", "Basic abc", f"Bearer {t.key}x"):
        r = gw.post("/v1/chat/completions", json={"model": "haiku"}, headers={"Authorization": bad} if bad else {})
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"
    unknown = "mr_" + "A" * 43
    assert world.chat(gw, unknown, "haiku").status_code == 401
    with world.owner.begin() as s:
        s.execute(update(ApiKey).where(ApiKey.id == t.key_id).values(state="revoked"))
    r = world.chat(gw, t.key, "haiku")
    assert r.status_code == 401 and r.json()["error"]["forwarded"] is False
    assert len(world.inference.calls) == 1


def test_it04_database_down_rejects_audit_unavailable(world: World) -> None:
    t, _ = verified_world(world)
    down = sessionmaker(bind=create_engine("postgresql+psycopg://mapleroute_app@localhost:1/mapleroute_test",
                                           connect_args={"connect_timeout": 1}))
    world.inference.calls.clear()
    r = world.chat(world.gateway(down), t.key, "haiku")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "audit_unavailable" and r.json()["error"]["forwarded"] is False
    assert world.inference.calls == []


def test_it04_log_insert_failure_rejects_audit_unavailable(world: World) -> None:
    t, _ = verified_world(world)
    world.inference.calls.clear()
    with world.owner.begin() as s:
        s.execute(text("REVOKE INSERT ON request_log FROM mapleroute_gateway"))
    try:
        r = world.chat(world.gateway(), t.key, "haiku")
    finally:
        with world.owner.begin() as s:
            s.execute(text("GRANT INSERT ON request_log TO mapleroute_gateway"))
    assert r.status_code == 503 and r.json()["error"]["code"] == "audit_unavailable"
    assert world.inference.calls == []
    assert rows(world) == []


def test_no_active_allowlist_is_policy_unavailable(world: World) -> None:
    t = world.tenant("alpha")
    r = world.chat(world.gateway(), t.key, "haiku")
    assert r.status_code == 503 and r.json()["error"]["code"] == "policy_unavailable"


@pytest.mark.parametrize(("mode", "status", "code"), [("error", 502, "upstream_error"),
                                                       ("timeout", 504, "upstream_timeout")])
def test_upstream_failure_no_retry_and_no_provider_text(world: World, mode: str, status: int, code: str) -> None:
    t, _ = verified_world(world)
    world.inference.mode = mode
    world.inference.error_status, world.inference.error_code = 429, "ThrottlingException"
    r = world.chat(world.gateway(), t.key, "haiku")
    assert r.status_code == status
    err = r.json()["error"]
    assert err["code"] == code and err["forwarded"] is True
    if mode == "error":
        assert (err["provider_status"], err["provider_code"]) == (429, "ThrottlingException")
    assert len(world.inference.calls) == 1  # exactly one call: no retry, no other route
    assert rows(world)[-1].state == "upstream_error"


def test_rate_limit_rejects_without_forwarding(world: World) -> None:
    t, _ = verified_world(world)
    world.rate_limit = 2
    gw = world.gateway()
    codes = [world.chat(gw, t.key, "haiku").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert len(world.inference.calls) == 2


def test_healthz_has_no_tenant_data(world: World) -> None:
    r = world.gateway().get("/healthz")
    assert r.status_code == 200 and set(r.json()) == {"status", "process", "constants_hash"}

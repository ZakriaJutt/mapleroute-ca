"""UT-01, UT-02, UT-03 and the first allow-list fixture (T-3.1.1, MH-02)."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import text

from core import policy_store
from core.allowlist import (
    AllowlistDoc,
    PolicyUnavailable,
    PublishRefused,
    RouteEntry,
    RouteKey,
    build_version,
    canonical_bytes,
    entry_to_dict,
    listed,
    load_verified,
    rule_failure,
)
from tests.helpers import FIXTURE, World, fixture_routes

CA = frozenset({"ca-central-1", "ca-west-1"})


def entry(provider: str, cls: str, ident: str, dest: set[str], region: str = "ca-central-1",
          version: str | None = None) -> RouteEntry:
    return RouteEntry(RouteKey(provider, region, cls, ident, version), frozenset(dest))


UT01 = [
    ("ca_profile", entry("aws", "geo_ca", "ca.anthropic.claude-haiku-5-5", set(CA)), True),
    ("us_profile", entry("aws", "geo_ca", "us.anthropic.claude-sonnet-5-5",
                         {"ca-central-1", "us-east-1", "us-east-2", "us-west-2"}), False),
    ("global_profile", entry("aws", "geo_ca", "global.anthropic.claude-sonnet-5-5", {"ca-central-1", "eu-west-1"}),
     False),
    ("empty_destinations", entry("aws", "geo_ca", "ca.amazon.nova-lite-v1:0", set()), False),
    ("azure_global_standard", entry("azure", "GlobalStandard", "gpt-4o", {"canadaeast"}, "canadaeast",
                                    "2024-11-20"), False),
    ("unknown_provider", entry("gcp", "regional", "gemini-x", {"northamerica-northeast1"},
                               "northamerica-northeast1"), False),
]


def doc_of(*entries: RouteEntry) -> AllowlistDoc:
    return AllowlistDoc("2026.11.10-1", {e.id: e for e in entries}, b"")


@pytest.mark.parametrize(("name", "route", "eligible"), UT01, ids=[u[0] for u in UT01])
def test_ut01_only_the_ca_profile_is_eligible(name: str, route: RouteEntry, eligible: bool) -> None:
    # Each route is evaluated against a version that contains it: listing alone never makes it eligible.
    assert listed(route.key, doc_of(route)) is eligible
    assert (rule_failure(route) is None) is eligible


def test_ut01_listed_is_deterministic_and_denies_absent_routes() -> None:
    ca = UT01[0][1]
    version = doc_of(ca)
    assert all(listed(ca.key, version) for _ in range(100))
    absent = RouteKey("aws", "ca-central-1", "geo_ca", "ca.amazon.nova-lite-v1:0")
    assert listed(absent, version) is False


def test_ut01_prefix_never_substitutes_for_destinations() -> None:
    # A `us.` identifier claiming Canadian destinations is refused by the consistency rule.
    assert rule_failure(entry("aws", "geo_ca", "us.anthropic.claude-sonnet-5-5", set(CA))) is not None
    # An in-region identifier must not carry a profile prefix and must stay in its source Region.
    assert rule_failure(entry("aws", "in_region", "ca.amazon.nova-lite-v1:0", {"ca-central-1"})) is not None
    assert rule_failure(entry("aws", "in_region", "amazon.titan-embed-text-v2:0", set(CA))) is not None


def test_ut02_draft_with_one_us_destination_is_refused_naming_the_route() -> None:
    routes = fixture_routes()
    bad = dict(routes[0], destinations=["ca-central-1", "us-east-1"])
    with pytest.raises(PublishRefused) as exc:
        build_version("2026.11.12-1", [*routes[1:], bad])
    assert exc.value.route_id == bad["id"]
    assert exc.value.reason == "destination_outside_canada"


def test_ut03_altered_byte_gives_policy_unavailable() -> None:
    doc, digest = build_version("2026.11.10-1", fixture_routes())
    assert load_verified("2026.11.10-1", doc, digest).version == "2026.11.10-1"
    raw = canonical_bytes(doc).replace(b"ca-west-1", b"ca-west-2", 1)
    with pytest.raises(PolicyUnavailable):
        load_verified("2026.11.10-1", json.loads(raw), digest)
    altered_hash = bytes([digest[0] ^ 1]) + digest[1:]
    with pytest.raises(PolicyUnavailable):
        load_verified("2026.11.10-1", doc, altered_hash)


def test_first_version_fixture_has_32_routes_and_stable_hash() -> None:
    raw = json.loads(FIXTURE.read_text())
    doc, digest = build_version(raw["version"], raw["routes"])
    assert len(doc["routes"]) == 32
    assert digest.hex() == raw["sha256"] == hashlib.sha256(canonical_bytes(doc)).hexdigest()
    by_class: dict[str, int] = {}
    for r in doc["routes"]:
        by_class[r["deployment_class"]] = by_class.get(r["deployment_class"], 0) + 1
    assert by_class == {"in_region": 12, "geo_ca": 2, "Standard": 5, "ProvisionedManaged": 13}
    assert not any(r["identifier"].startswith(("us.", "global.")) for r in doc["routes"])


def test_ut03_db_altered_document_rejects_requests(world: World) -> None:
    """The active version's stored bytes are altered behind the trigger: requests get policy_unavailable."""
    world.activate()
    t = world.tenant("alpha")
    with world.owner.begin() as s:
        s.execute(text("ALTER TABLE allowlist_version DISABLE TRIGGER allowlist_version_immutable"))
        s.execute(text("UPDATE allowlist_version SET document = jsonb_set(document, '{routes,0,destinations}', "
                       "'[\"us-east-1\"]') WHERE state = 'active'"))
        s.execute(text("ALTER TABLE allowlist_version ENABLE TRIGGER allowlist_version_immutable"))
    r = world.chat(world.gateway(), t.key, "anything")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "policy_unavailable"
    assert r.json()["error"]["forwarded"] is False
    assert world.inference.calls == []


def test_versions_are_immutable_and_republish_is_idempotent(world: World) -> None:
    world.activate()
    op = world.operator()
    with world.app.begin() as s:
        again = policy_store.publish_draft(s, "2026.11.10-1", fixture_routes(), op)
    assert again.created is False
    changed = [dict(r) for r in fixture_routes()[:-1]]
    with pytest.raises(policy_store.VersionConflict), world.app.begin() as s:
        policy_store.publish_draft(s, "2026.11.10-1", changed, op)
    with pytest.raises(Exception, match="immutable"), world.app.begin() as s:
        s.execute(text("UPDATE allowlist_version SET document = '{}'::jsonb"))
    with pytest.raises(Exception, match="never deleted"), world.owner.begin() as s:
        s.execute(text("DELETE FROM allowlist_version"))


def test_at_most_one_active_version(world: World) -> None:
    world.activate()
    routes = [r for r in fixture_routes() if r["provider"] == "aws"]
    world.activate(routes, version="2026.11.11-1")
    with world.app.begin() as s:
        states = dict(s.execute(text("SELECT version, state FROM allowlist_version")).all())
        active = policy_store.load_active(s)
    assert states == {"2026.11.10-1": "superseded", "2026.11.11-1": "active"}
    assert active is not None and len(active.entries) == 14


def test_entry_round_trip() -> None:
    e = UT01[0][1]
    assert entry_to_dict(e)["id"] == e.id == "aws:ca-central-1:geo_ca:ca.anthropic.claude-haiku-5-5"

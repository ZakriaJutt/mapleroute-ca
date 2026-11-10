"""The allow-list: routes, the eligibility rule ``listed``, canonical serialisation and hash (T-3.1.1).

Pure. ``listed`` gives the same answer for the same route and version every time (AD-01).
This is the only implementation of the rule; the publish check and the request path both call it.
A route is global: it names no customer host or deployment (AD-14).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from core.config import CANADA, CLASSES

VERSION_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2}-\d+$")
# Geographic or global prefixes of Bedrock inference profiles. An in-region identifier carries none.
_BEDROCK_PROFILE_PREFIXES = ("us.", "us-gov.", "eu.", "apac.", "jp.", "au.", "in.", "ca.", "global.")


class AllowlistError(ValueError):
    pass


class PublishRefused(AllowlistError):
    def __init__(self, route_id: str, reason: str) -> None:
        super().__init__(f"route {route_id} refused: {reason}")
        self.route_id = route_id
        self.reason = reason


class PolicyUnavailable(AllowlistError):
    """Allow-list missing, unreadable or hash mismatch. The request path rejects."""


@dataclass(frozen=True)
class RouteKey:
    """What identifies a route. Destinations belong to a version's entry, not to the key."""

    provider: str
    source_region: str
    deployment_class: str
    identifier: str
    model_version: str | None = None

    @property
    def id(self) -> str:
        parts = [self.provider, self.source_region, self.deployment_class, self.identifier]
        if self.model_version is not None:
            parts.append(self.model_version)
        return ":".join(parts)


@dataclass(frozen=True)
class RouteEntry:
    key: RouteKey
    destinations: frozenset[str]

    @property
    def id(self) -> str:
        return self.key.id


@dataclass(frozen=True)
class AllowlistDoc:
    version: str
    entries: Mapping[str, RouteEntry]
    sha256: bytes


def rule_failure(entry: RouteEntry) -> str | None:
    """Why an entry fails the eligibility rule, or None when it holds (TRD.md ``listed``)."""
    key = entry.key
    canada = CANADA.get(key.provider)
    classes = CLASSES.get(key.provider)
    if canada is None or classes is None:
        return "unknown_provider"
    if not entry.destinations:
        return "empty_destinations"
    if not entry.destinations <= canada:
        return "destination_outside_canada"
    if key.deployment_class not in classes:
        return "class_not_eligible"
    if key.source_region not in canada:
        return "source_region_outside_canada"
    if not key.identifier:
        return "empty_identifier"
    # Consistency checks. They can only refuse; a prefix never makes a route eligible.
    if key.provider == "aws":
        if key.model_version is not None:
            return "aws_has_no_model_version"
        if key.deployment_class == "in_region":
            if key.identifier.startswith(_BEDROCK_PROFILE_PREFIXES):
                return "in_region_identifier_has_profile_prefix"
            if entry.destinations != frozenset({key.source_region}):
                return "in_region_destinations_not_source"
        if key.deployment_class == "geo_ca" and not key.identifier.startswith("ca."):
            return "geo_ca_identifier_not_ca_profile"
    if key.provider == "azure" and not key.model_version:
        return "azure_needs_model_version"
    return None


def listed(route: RouteKey, version: AllowlistDoc) -> bool:
    """``route in version.routes`` and the version's entry for it satisfies the rule."""
    entry = version.entries.get(route.id)
    return entry is not None and entry.key == route and rule_failure(entry) is None


def entry_from_dict(raw: Mapping[str, Any]) -> RouteEntry:
    try:
        key = RouteKey(
            provider=str(raw["provider"]),
            source_region=str(raw["source_region"]),
            deployment_class=str(raw["deployment_class"]),
            identifier=str(raw["identifier"]),
            model_version=None if raw.get("model_version") is None else str(raw["model_version"]),
        )
        destinations = frozenset(str(d) for d in raw["destinations"])
    except (KeyError, TypeError) as exc:
        raise AllowlistError(f"malformed route entry: {exc}") from exc
    entry = RouteEntry(key, destinations)
    if "id" in raw and raw["id"] != entry.id:
        raise AllowlistError(f"route id {raw['id']!r} does not match its fields ({entry.id})")
    return entry


def entry_to_dict(entry: RouteEntry) -> dict[str, Any]:
    k = entry.key
    return {
        "id": entry.id,
        "provider": k.provider,
        "source_region": k.source_region,
        "deployment_class": k.deployment_class,
        "identifier": k.identifier,
        "model_version": k.model_version,
        "destinations": sorted(entry.destinations),
    }


def document(version: str, entries: Iterable[RouteEntry]) -> dict[str, Any]:
    return {"version": version, "routes": [entry_to_dict(e) for e in sorted(entries, key=lambda e: e.id)]}


def canonical_bytes(doc: Mapping[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def build_version(version: str, raw_routes: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], bytes]:
    """Validate a draft and return (canonical document, sha256). Refuses any failing route (UT-02)."""
    if not VERSION_PATTERN.match(version):
        raise AllowlistError(f"version {version!r} must look like 2026.11.10-1")
    entries: dict[str, RouteEntry] = {}
    for raw in raw_routes:
        entry = entry_from_dict(raw)
        reason = rule_failure(entry)
        if reason is not None:
            raise PublishRefused(entry.id, reason)
        if entry.id in entries:
            raise PublishRefused(entry.id, "duplicate_route")
        entries[entry.id] = entry
    if not entries:
        raise AllowlistError("a version must list at least one route")
    doc = document(version, entries.values())
    return doc, hashlib.sha256(canonical_bytes(doc)).digest()


def load_verified(version: str, stored_document: Any, stored_sha256: bytes) -> AllowlistDoc:
    """Re-canonicalise a stored document and check its hash (UT-03). Any failure is PolicyUnavailable."""
    try:
        if not isinstance(stored_document, Mapping) or stored_document.get("version") != version:
            raise PolicyUnavailable("document version field does not match its row")
        entries = [entry_from_dict(r) for r in stored_document["routes"]]
        doc = document(version, entries)
        if doc != dict(stored_document):
            raise PolicyUnavailable("document is not in canonical form")
        digest = hashlib.sha256(canonical_bytes(doc)).digest()
    except PolicyUnavailable:
        raise
    except (AllowlistError, KeyError, TypeError) as exc:
        raise PolicyUnavailable(f"allow-list {version} unreadable") from exc
    if digest != bytes(stored_sha256):
        raise PolicyUnavailable(f"allow-list {version} hash mismatch")
    return AllowlistDoc(version=version, entries={e.id: e for e in entries}, sha256=digest)

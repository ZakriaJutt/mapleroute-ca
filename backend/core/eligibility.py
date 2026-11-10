"""``forwardable`` and the ``Decision`` type (T-3.1.1, AD-01, highest-consequence failure #1).

A ``Decision`` can be built only by ``evaluate``; the single forward function accepts nothing
else. Every input that decided the request is on the Decision (and is copied to the log row), so
the decision can be replayed (MH-02). Anything not listed is denied; there is no fallback.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from core.allowlist import AllowlistDoc, RouteKey, listed
from core.config import VALIDITY
from core.errors import Code

# Clock skew tolerated for a verification stamped slightly in the future; beyond it, reject.
MAX_FUTURE_SKEW = timedelta(seconds=60)

_SEAL = object()


@dataclass(frozen=True)
class BindingState:
    """What the request path reads for one alias: binding, its route, and its connection."""

    binding_id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    alias: str
    route: RouteKey
    route_global_status: str
    status: str
    last_verified_at: datetime | None
    deployment_name: str | None
    connection_id: uuid.UUID
    connection_provider: str
    connection_region: str
    connection_state: str
    endpoint_host: str | None


@dataclass(frozen=True)
class Decision:
    binding_id: uuid.UUID
    connection_id: uuid.UUID
    route_id: str
    provider: str
    source_region: str
    upstream_host: str
    upstream_identifier: str
    allowlist_version: str
    route_status: str
    binding_verified_at: datetime
    _seal: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise TypeError("a Decision is built only by core.eligibility.evaluate")

    def is_sealed(self) -> bool:
        return self._seal is _SEAL


@dataclass(frozen=True)
class Rejection:
    code: Code
    route_id: str | None = None
    allowlist_version: str | None = None
    route_status: str | None = None
    binding_verified_at: datetime | None = None


def bedrock_runtime_host(region: str) -> str:
    return f"bedrock-runtime.{region}.amazonaws.com"


def evaluate(binding: BindingState | None, version: AllowlistDoc | None, now: datetime) -> Decision | Rejection:
    if version is None:
        return Rejection(Code.POLICY_UNAVAILABLE)
    if binding is None:
        return Rejection(Code.ROUTE_NOT_ELIGIBLE, allowlist_version=version.version)
    route = binding.route

    def reject(code: Code) -> Rejection:
        return Rejection(code, route.id, version.version, binding.route_global_status, binding.last_verified_at)

    # The connection must be live and must be the provider and Region the route names.
    if (
        binding.connection_state == "deleted"
        or binding.connection_provider != route.provider
        or binding.connection_region != route.source_region
    ):
        return reject(Code.ROUTE_NOT_ELIGIBLE)
    if not listed(route, version):
        return reject(Code.ROUTE_NOT_ELIGIBLE)
    if binding.route_global_status != "active":
        return reject(Code.ROUTE_SUSPENDED)
    verified_at = binding.last_verified_at
    if binding.status != "verified" or verified_at is None:
        return reject(Code.ROUTE_UNVERIFIED)
    validity = VALIDITY[route.provider]
    if now - verified_at > validity or verified_at - now > MAX_FUTURE_SKEW:
        return reject(Code.ROUTE_UNVERIFIED)
    if route.provider == "aws":
        host, identifier = bedrock_runtime_host(route.source_region), route.identifier
    else:
        if not binding.endpoint_host or not binding.deployment_name:
            return reject(Code.ROUTE_NOT_ELIGIBLE)
        host, identifier = binding.endpoint_host, binding.deployment_name
    return Decision(
        binding_id=binding.binding_id,
        connection_id=binding.connection_id,
        route_id=route.id,
        provider=route.provider,
        source_region=route.source_region,
        upstream_host=host,
        upstream_identifier=identifier,
        allowlist_version=version.version,
        route_status=binding.route_global_status,
        binding_verified_at=verified_at,
        _seal=_SEAL,
    )

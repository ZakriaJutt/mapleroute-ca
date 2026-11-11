"""``forwardable`` and the ``Decision`` type (T-3.1.1, AD-01, highest-consequence failure #1).

A ``Decision`` can be built only by ``evaluate``; the single forward function accepts nothing
else. Every input that decided the request is on the Decision (and is copied to the log row), so
the decision can be replayed (MH-02). Anything not listed is denied; there is no fallback.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from core.allowlist import AllowlistDoc, RouteKey, listed
from core.config import VALIDITY
from core.errors import Code

# Clock skew tolerated for a verification stamped slightly in the future; beyond it, reject.
MAX_FUTURE_SKEW = timedelta(seconds=60)

# Kept only so older probes that pass it still import; it grants nothing since fix round 2 (B1-007).
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


_MAC_KEY = secrets.token_bytes(32)  # per process; a Decision never crosses a process boundary


def _mac(d: Decision) -> bytes:
    fields = (d.binding_id, d.connection_id, d.route_id, d.provider, d.source_region, d.upstream_host,
              d.upstream_identifier, d.allowlist_version, d.route_status, d.binding_verified_at.isoformat())
    return hmac.new(_MAC_KEY, repr(fields).encode(), hashlib.sha256).digest()


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

    def is_sealed(self) -> bool:
        """True only for the very object ``evaluate`` issued, with its fields unchanged (B1-007).

        Constructing a Decision, passing any ``_seal`` value, copying it or changing a field gives an
        object that is not in the issue registry or whose MAC differs. Residual risk, recorded: code
        in the same process that deliberately writes to this module's private registry can still
        forge one; Python has no stronger in-process boundary.
        """
        ref = _ISSUED.get(id(self))
        return (ref is not None and ref() is self and isinstance(self._seal, bytes)
                and hmac.compare_digest(self._seal, _mac(self)))


# id(decision) -> weak reference; identity, not equality, so an equal hand-built copy is not issued.
_ISSUED: dict[int, weakref.ref[Decision]] = {}
_ISSUED_LOCK = threading.Lock()


def _issue(d: Decision) -> Decision:
    object.__setattr__(d, "_seal", _mac(d))
    key = id(d)

    def _drop(_: object, key: int = key) -> None:
        with _ISSUED_LOCK:
            _ISSUED.pop(key, None)

    with _ISSUED_LOCK:
        _ISSUED[key] = weakref.ref(d, _drop)
    return d


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
    return _issue(Decision(
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
    ))

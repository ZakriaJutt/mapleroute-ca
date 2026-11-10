"""The data-plane error contract (TRD.md "Error contract", T-1.1.2, T-3.1.6).

``forwarded`` is false whenever no byte was sent to a provider. Messages never contain provider
error text, request content or credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Code(StrEnum):
    INVALID_API_KEY = "invalid_api_key"
    UNSUPPORTED_PARAMETER = "unsupported_parameter"
    ROUTE_NOT_ELIGIBLE = "route_not_eligible"
    ROUTE_UNVERIFIED = "route_unverified"
    ROUTE_SUSPENDED = "route_suspended"
    POLICY_UNAVAILABLE = "policy_unavailable"
    AUDIT_UNAVAILABLE = "audit_unavailable"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    UPSTREAM_TIMEOUT = "upstream_timeout"


@dataclass(frozen=True)
class Contract:
    http_status: int
    type: str
    forwarded: bool


CONTRACT: dict[Code, Contract] = {
    Code.INVALID_API_KEY: Contract(401, "authentication_error", False),
    Code.UNSUPPORTED_PARAMETER: Contract(400, "invalid_request_error", False),
    Code.ROUTE_NOT_ELIGIBLE: Contract(403, "permission_error", False),
    Code.ROUTE_UNVERIFIED: Contract(403, "permission_error", False),
    Code.ROUTE_SUSPENDED: Contract(503, "service_unavailable", False),
    Code.POLICY_UNAVAILABLE: Contract(503, "service_unavailable", False),
    Code.AUDIT_UNAVAILABLE: Contract(503, "service_unavailable", False),
    Code.RATE_LIMITED: Contract(429, "rate_limit_error", False),
    Code.UPSTREAM_ERROR: Contract(502, "upstream_error", True),
    Code.UPSTREAM_TIMEOUT: Contract(504, "upstream_error", True),
}

_NOT_SENT = "The request was not sent to any provider."


def message(code: Code, alias: str | None = None) -> str:
    model = f"model '{alias}'" if alias else "the requested model"
    texts = {
        Code.INVALID_API_KEY: f"The API key is unknown, revoked or malformed. {_NOT_SENT}",
        Code.UNSUPPORTED_PARAMETER: f"A stateful or storage feature was requested. {_NOT_SENT}",
        Code.ROUTE_NOT_ELIGIBLE: f"No Canada-listed route is bound to {model} for this project. {_NOT_SENT}",
        Code.ROUTE_UNVERIFIED: (
            f"The route bound to {model} has no matching verification within its validity period. {_NOT_SENT}"
        ),
        Code.ROUTE_SUSPENDED: f"The route bound to {model} is suspended. {_NOT_SENT}",
        Code.POLICY_UNAVAILABLE: f"The allow-list could not be read. {_NOT_SENT}",
        Code.AUDIT_UNAVAILABLE: f"The request could not be recorded. {_NOT_SENT}",
        Code.RATE_LIMITED: f"Too many requests for this key. {_NOT_SENT}",
        Code.UPSTREAM_ERROR: "The provider returned an error. The provider's message text is not passed on.",
        Code.UPSTREAM_TIMEOUT: "The provider sent no first byte within 60 seconds. No other route was tried.",
    }
    return texts[code]


def error_body(
    code: Code,
    *,
    request_id: str | None,
    allowlist_version: str | None,
    alias: str | None = None,
    param: str | None = None,
    provider_status: int | None = None,
    provider_code: str | None = None,
) -> dict[str, Any]:
    c = CONTRACT[code]
    err: dict[str, Any] = {
        "type": c.type,
        "code": code.value,
        "message": message(code, alias),
        "param": param,
        "request_id": request_id,
        "allowlist_version": allowlist_version,
        "forwarded": c.forwarded,
    }
    if provider_status is not None:
        err["provider_status"] = provider_status
    if provider_code is not None:
        err["provider_code"] = provider_code
    return {"error": err}

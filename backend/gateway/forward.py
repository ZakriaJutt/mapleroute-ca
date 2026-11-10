"""The single forward function (highest-consequence failure #1). It accepts only a sealed Decision.

There is no fallback route and no retry: one Decision, one upstream call on that Decision's host
and identifier, or nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from core.eligibility import Decision
from core.providers import InferenceClient, UpstreamRequest, UpstreamResponse
from core.secretvalue import SecretValue


def _check(decision: object) -> Decision:
    if not isinstance(decision, Decision) or not decision.is_sealed():
        raise TypeError("forward() requires a Decision built by core.eligibility.evaluate")
    return decision


def forward(clients: dict[str, InferenceClient], decision: Decision, endpoint: str, body: dict[str, Any],
            credential: SecretValue) -> UpstreamResponse:
    d = _check(decision)
    return clients[d.provider].send(UpstreamRequest(d, endpoint, body, credential))


def forward_stream(clients: dict[str, InferenceClient], decision: Decision, body: dict[str, Any],
                   credential: SecretValue) -> Iterator[bytes]:
    d = _check(decision)
    return clients[d.provider].stream(UpstreamRequest(d, "chat", body, credential))

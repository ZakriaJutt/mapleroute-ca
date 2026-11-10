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


# Fields an adapter may receive (B1-009). Anything else, including routing fields such as
# `deployment`, `region` or `api_base`, is dropped. `model` is always the Decision's identifier.
ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "chat": frozenset({
        "messages", "temperature", "top_p", "max_tokens", "max_completion_tokens", "stop", "stream", "n",
        "presence_penalty", "frequency_penalty", "seed", "response_format", "tools", "tool_choice",
        "logit_bias", "logprobs", "top_logprobs", "user",
    }),
    "embeddings": frozenset({"input", "dimensions", "encoding_format", "user"}),
}


def validated_body(endpoint: str, body: dict[str, Any], decision: Decision) -> dict[str, Any]:
    allowed = ALLOWED_FIELDS[endpoint]
    clean = {k: v for k, v in body.items() if k in allowed}
    clean["model"] = decision.upstream_identifier
    return clean


def forward(clients: dict[str, InferenceClient], decision: Decision, endpoint: str, body: dict[str, Any],
            credential: SecretValue) -> UpstreamResponse:
    d = _check(decision)
    return clients[d.provider].send(UpstreamRequest(d, endpoint, validated_body(endpoint, body, d), credential))


def forward_stream(clients: dict[str, InferenceClient], decision: Decision, body: dict[str, Any],
                   credential: SecretValue) -> Iterator[bytes]:
    d = _check(decision)
    return clients[d.provider].stream(UpstreamRequest(d, "chat", validated_body("chat", body, d), credential))

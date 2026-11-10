"""Deterministic in-memory fakes for every provider interface (B1: no real cloud calls).

Used by the tests and by the local start command. The inference fake counts outbound calls so a
test can assert "zero outbound calls" (IT-03, IT-04). It records routing metadata only, never
the request body.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from core.providers import (
    AccessDenied,
    ActivityEvent,
    AwsTarget,
    AzureTarget,
    DeploymentAnswer,
    FoundationModelAnswer,
    InferenceProfileAnswer,
    LoggingAnswer,
    PolicyAnswer,
    RolePolicyAnswer,
    UpstreamError,
    UpstreamRequest,
    UpstreamResponse,
    UpstreamTimeout,
)
from core.secretvalue import SecretValue


@dataclass(frozen=True)
class OutboundCall:
    provider: str
    host: str
    identifier: str
    endpoint: str
    stream: bool


class FakeInference:
    def __init__(self) -> None:
        self.calls: list[OutboundCall] = []
        self.mode = "ok"  # "ok" | "error" | "timeout"
        self.error_status = 500
        self.error_code: str | None = "internal_error"
        self.reply_text = "synthetic reply"
        self.chunks: list[bytes] = [b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n', b"data: [DONE]\n\n"]
        self._ids = itertools.count(1)

    def _record(self, request: UpstreamRequest, stream: bool) -> None:
        d = request.decision
        if not d.is_sealed():
            raise AssertionError("unsealed decision reached the provider stub")
        self.calls.append(OutboundCall(d.provider, d.upstream_host, d.upstream_identifier, request.endpoint, stream))

    def send(self, request: UpstreamRequest) -> UpstreamResponse:
        self._record(request, stream=False)
        if self.mode == "timeout":
            raise UpstreamTimeout()
        if self.mode == "error":
            raise UpstreamError(self.error_status, self.error_code)
        body: dict[str, Any]
        if request.endpoint == "embeddings":
            body = {"object": "list", "data": [{"object": "embedding", "index": 0, "embedding": [0.0, 0.1]}]}
        else:
            body = {
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": self.reply_text}}],
            }
        body["usage"] = {"prompt_tokens": 3, "completion_tokens": 2}
        return UpstreamResponse(200, body, 3, 2, f"prov-{next(self._ids)}")

    def stream(self, request: UpstreamRequest) -> Iterator[bytes]:
        self._record(request, stream=True)
        if self.mode == "timeout":
            raise UpstreamTimeout()
        if self.mode == "error":
            raise UpstreamError(self.error_status, self.error_code)
        yield from self.chunks


class FakeAwsSessions:
    def __init__(self) -> None:
        self.assumed: list[tuple[str, str]] = []

    def assume_role(self, role_arn: str, external_id: str, region: str) -> SecretValue:
        self.assumed.append((role_arn, region))
        return SecretValue("fake-session-" + uuid.uuid4().hex)


@dataclass
class FakeAwsAccount:
    profiles: dict[str, InferenceProfileAnswer] = field(default_factory=dict)
    models: dict[str, FoundationModelAnswer] = field(default_factory=dict)
    role: RolePolicyAnswer = field(default_factory=lambda: RolePolicyAnswer(True, True, False))
    logging: LoggingAnswer = field(default_factory=lambda: LoggingAnswer("off"))
    deny_access: bool = False
    raise_error: bool = False


class FakeAwsReader:
    """Accounts keyed by role ARN."""

    def __init__(self) -> None:
        self.accounts: dict[str, FakeAwsAccount] = {}

    def account(self, target: AwsTarget) -> FakeAwsAccount:
        acct = self.accounts.get(target.role_arn)
        if acct is None or acct.deny_access:
            raise AccessDenied()
        if acct.raise_error:
            raise RuntimeError("fake reader failure")
        return acct

    def get_inference_profile(self, target: AwsTarget, profile_id: str) -> InferenceProfileAnswer:
        acct = self.account(target)
        if profile_id not in acct.profiles:
            raise AccessDenied()
        return acct.profiles[profile_id]

    def get_foundation_model(self, target: AwsTarget, model_id: str) -> FoundationModelAnswer:
        return self.account(target).models.get(model_id, FoundationModelAnswer(model_id, False, False))

    def read_role_policy(self, target: AwsTarget) -> RolePolicyAnswer:
        return self.account(target).role

    def get_invocation_logging(self, target: AwsTarget) -> LoggingAnswer:
        return self.account(target).logging


def canadian_profile(
    profile_id: str, regions: tuple[str, ...] = ("ca-central-1", "ca-west-1")
) -> InferenceProfileAnswer:
    model = profile_id.removeprefix("ca.")
    arns = tuple(f"arn:aws:bedrock:{r}::foundation-model/{model}" for r in regions)
    return InferenceProfileAnswer(profile_id, "SYSTEM_DEFINED", arns)


@dataclass
class FakeAzureDeployment:
    deployment: DeploymentAnswer
    policy: PolicyAnswer = field(default_factory=lambda: PolicyAnswer(True, True, False, ("pa-deny-sku",)))
    events: list[ActivityEvent] = field(default_factory=list)
    logging: LoggingAnswer = field(default_factory=lambda: LoggingAnswer("off"))
    deny_access: bool = False


class FakeAzureReader:
    """Deployments keyed by (endpoint host, deployment name)."""

    def __init__(self) -> None:
        self.deployments: dict[tuple[str, str], FakeAzureDeployment] = {}
        self.read_count = 0

    def _get(self, target: AzureTarget) -> FakeAzureDeployment:
        self.read_count += 1
        dep = self.deployments.get((target.endpoint_host, target.deployment_name))
        if dep is None or dep.deny_access:
            raise AccessDenied()
        return dep

    def get_deployment(self, target: AzureTarget) -> DeploymentAnswer:
        return self._get(target).deployment

    def get_policy_state(self, target: AzureTarget) -> PolicyAnswer:
        return self._get(target).policy

    def activity_since(self, target: AzureTarget, since: datetime) -> list[ActivityEvent]:
        return [e for e in self._get(target).events if e.at > since]

    def get_diagnostic_logging(self, target: AzureTarget) -> LoggingAnswer:
        return self._get(target).logging

    # --- fixture helpers for IT-21 -------------------------------------------------------
    def remove_deny_policy(self, host: str, name: str, at: datetime) -> None:
        dep = self.deployments[(host, name)]
        dep.policy = PolicyAnswer(False, False, False, ())
        dep.events.append(ActivityEvent("policy_assignment_change", at))

    def restore_deny_policy(self, host: str, name: str, at: datetime) -> None:
        dep = self.deployments[(host, name)]
        dep.policy = PolicyAnswer(True, True, False, ("pa-deny-sku",))
        dep.events.append(ActivityEvent("policy_assignment_change", at))

    def recreate(self, host: str, name: str, sku_name: str, at: datetime) -> None:
        dep = self.deployments[(host, name)]
        dep.deployment = replace(dep.deployment, sku_name=sku_name, created_at=at, modified_at=at)
        dep.events.append(ActivityEvent("deployment_delete", at))
        dep.events.append(ActivityEvent("deployment_write", at))


EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

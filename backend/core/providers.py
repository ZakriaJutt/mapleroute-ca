"""Interfaces to AWS and Azure. B1 implements only the fakes in ``core.fakes``; no real calls.

Data plane: ``InferenceClient`` (one per provider), called only by the gateway's single forward
function with a ``Decision``. Control plane: read-only ``AwsControlReader`` and
``AzureControlReader`` used by the verifier. Error types carry a status and a provider code,
never provider message text.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from core.eligibility import Decision
from core.secretvalue import SecretValue


# ------------------------------------------------------------------ data plane
@dataclass(frozen=True)
class UpstreamRequest:
    decision: Decision
    endpoint: str  # "chat" | "embeddings"
    body: dict[str, Any] = field(repr=False)  # content: memory only, never logged
    credential: SecretValue = field(repr=False)


@dataclass(frozen=True)
class UpstreamResponse:
    status: int
    body: dict[str, Any] = field(repr=False)
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_request_id: str | None = None


class UpstreamError(Exception):
    """The provider answered with an error. Only status and code survive; text is dropped."""

    def __init__(self, status: int, provider_code: str | None = None) -> None:
        super().__init__(f"upstream status {status}")
        self.status = status
        self.provider_code = provider_code


class UpstreamTimeout(Exception):
    """No first byte within the first-byte timeout."""


class InferenceClient(Protocol):
    def send(self, request: UpstreamRequest) -> UpstreamResponse: ...

    def stream(self, request: UpstreamRequest) -> Iterator[bytes]: ...


class AwsSessionProvider(Protocol):
    def assume_role(self, role_arn: str, external_id: str, region: str) -> SecretValue:
        """Regional STS; session credentials live in memory for at most 15 minutes."""
        ...


# ------------------------------------------------------------------ control plane (verification)
class AccessDenied(Exception):
    """The reader has no access. Never counts as a pass (TRD.md route verification)."""


@dataclass(frozen=True)
class InferenceProfileAnswer:
    profile_id: str
    profile_type: str  # "SYSTEM_DEFINED" | "APPLICATION"
    model_arns: tuple[str, ...]


@dataclass(frozen=True)
class FoundationModelAnswer:
    model_id: str
    exists: bool
    enabled: bool


@dataclass(frozen=True)
class RolePolicyAnswer:
    """Result of reading the assumed role's policies and simulating two out-of-Canada calls."""

    us_profile_denied: bool
    us_east_model_denied: bool
    broader_than_template: bool


@dataclass(frozen=True)
class LoggingAnswer:
    state: str  # "off" | "on" | "not_readable"
    destination: str | None = None
    destination_region: str | None = None


@dataclass(frozen=True)
class DeploymentAnswer:
    location: str
    sku_name: str
    model_name: str
    model_version: str
    created_at: datetime
    modified_at: datetime


@dataclass(frozen=True)
class PolicyAnswer:
    deny_assignment_present: bool
    enforced: bool
    exempted: bool
    assignment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActivityEvent:
    kind: str  # e.g. "deployment_write", "deployment_delete", "policy_assignment_change", "policy_exemption_change"
    at: datetime


@dataclass(frozen=True)
class AwsTarget:
    connection_id: uuid.UUID
    role_arn: str
    external_id: str
    region: str


@dataclass(frozen=True)
class AzureTarget:
    connection_id: uuid.UUID
    account_ref: str
    endpoint_host: str
    resource_group: str
    deployment_name: str
    credential: SecretValue = field(repr=False)


class AwsControlReader(Protocol):
    def get_inference_profile(self, target: AwsTarget, profile_id: str) -> InferenceProfileAnswer: ...

    def get_foundation_model(self, target: AwsTarget, model_id: str) -> FoundationModelAnswer: ...

    def read_role_policy(self, target: AwsTarget) -> RolePolicyAnswer: ...

    def get_invocation_logging(self, target: AwsTarget) -> LoggingAnswer: ...


class AzureControlReader(Protocol):
    def get_deployment(self, target: AzureTarget) -> DeploymentAnswer: ...

    def get_policy_state(self, target: AzureTarget) -> PolicyAnswer: ...

    def activity_since(self, target: AzureTarget, since: datetime) -> list[ActivityEvent]: ...

    def get_diagnostic_logging(self, target: AzureTarget) -> LoggingAnswer: ...

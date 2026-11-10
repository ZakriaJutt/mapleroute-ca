"""SQLAlchemy models. Must match migrations/sql/0001_core.sql; tools/orm_parity checks it (R-08).

No table or column holds prompt or response content (AD-05).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(TS, nullable=False, server_default=func.now())


def _tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = _id()
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pilot'"))
    log_retention_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("13"))
    require_mfa_claim: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("state IN ('active', 'deletion_pending', 'deleted')", name="ck_tenant_state"),
        CheckConstraint("plan IN ('pilot', 'starter', 'pro', 'business')", name="ck_tenant_plan"),
        CheckConstraint("log_retention_months BETWEEN 1 AND 24", name="ck_tenant_retention"),
    )


class UserAccount(Base):
    __tablename__ = "user_account"
    id: Mapped[uuid.UUID] = _id()
    idp: Mapped[str] = mapped_column(Text, nullable=False)
    idp_subject: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_operator: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created()
    __table_args__ = (UniqueConstraint("idp", "idp_subject", name="uq_user_account_idp_subject"),)


class Membership(Base):
    __tablename__ = "membership"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user_account.id"))
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'engineer', 'reviewer')", name="ck_membership_role"),
        UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),
    )


class FormToken(Base):
    __tablename__ = "form_token"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    token: Mapped[str] = mapped_column(Text, nullable=False)
    result_ref: Mapped[str | None] = mapped_column(Text)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (UniqueConstraint("tenant_id", "token", name="uq_form_token_tenant_token"),)


class Project(Base):
    __tablename__ = "project"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_project_tenant_name"),
        UniqueConstraint("tenant_id", "id", name="uq_project_tenant_id"),
    )


class ProviderConnection(Base):
    __tablename__ = "provider_connection"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    account_ref: Mapped[str] = mapped_column(Text, nullable=False)
    source_region: Mapped[str] = mapped_column(Text, nullable=False)
    role_arn: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    endpoint_host: Mapped[str | None] = mapped_column(Text)
    resource_group: Mapped[str | None] = mapped_column(Text)
    cloudtrail_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    last_read_ok_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.id"], name="fk_connection_project"
        ),
        CheckConstraint("provider IN ('aws', 'azure')", name="ck_connection_provider"),
        CheckConstraint(
            "source_region IN ('ca-central-1', 'ca-west-1', 'canadacentral', 'canadaeast')",
            name="ck_connection_region",
        ),
        CheckConstraint(
            "(provider = 'aws' AND source_region IN ('ca-central-1', 'ca-west-1')) OR "
            "(provider = 'azure' AND source_region IN ('canadacentral', 'canadaeast'))",
            name="ck_connection_provider_region",
        ),
        CheckConstraint(
            "provider <> 'aws' OR (role_arn IS NOT NULL AND external_id IS NOT NULL)",
            name="ck_connection_aws_fields",
        ),
        CheckConstraint(
            "provider <> 'azure' OR (endpoint_host IS NOT NULL AND resource_group IS NOT NULL)",
            name="ck_connection_azure_fields",
        ),
        CheckConstraint(
            "state IN ('pending', 'connected', 'access_failed', 'deleted')", name="ck_connection_state"
        ),
        UniqueConstraint("project_id", "provider", "account_ref", name="uq_connection_account"),
        UniqueConstraint("tenant_id", "id", name="uq_connection_tenant_id"),
    )


class ConnectionSecret(Base):
    __tablename__ = "connection_secret"
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_data_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kms_key_arn: Mapped[str] = mapped_column(Text, nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["provider_connection.tenant_id", "provider_connection.id"],
            name="fk_secret_connection",
        ),
    )


class ApiKey(Base):
    __tablename__ = "api_key"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    last_four: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    last_used_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.id"], name="fk_api_key_project"
        ),
        CheckConstraint("state IN ('active', 'revoked')", name="ck_api_key_state"),
        UniqueConstraint("key_hash", name="uq_api_key_hash"),
    )


class AllowlistVersion(Base):
    __tablename__ = "allowlist_version"
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user_account.id"))
    approved_at: Mapped[datetime | None] = mapped_column(TS)
    activate_after: Mapped[datetime | None] = mapped_column(TS)
    activated_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("state IN ('draft', 'active', 'superseded')", name="ck_allowlist_state"),
        CheckConstraint(
            "state = 'draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_allowlist_approval",
        ),
        Index(
            "ux_allowlist_one_active", "state", unique=True, postgresql_where=text("state = 'active'")
        ),
    )


class Route(Base):
    __tablename__ = "route"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    source_region: Mapped[str] = mapped_column(Text, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    deployment_class: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(Text)
    global_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    status_reason: Mapped[str | None] = mapped_column(Text)
    status_changed_at: Mapped[datetime | None] = mapped_column(TS)
    status_checked_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint(
            "(provider = 'aws' AND deployment_class IN ('in_region', 'geo_ca') AND model_version IS NULL) OR "
            "(provider = 'azure' AND deployment_class IN ('Standard', 'ProvisionedManaged') "
            "AND model_version IS NOT NULL)",
            name="ck_route_class",
        ),
        CheckConstraint("global_status IN ('active', 'suspended')", name="ck_route_status"),
    )


class AllowlistRoute(Base):
    __tablename__ = "allowlist_route"
    version: Mapped[str] = mapped_column(Text, ForeignKey("allowlist_version.version"), nullable=False)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("route.id"), nullable=False)
    destinations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        PrimaryKeyConstraint("version", "route_id"),
        CheckConstraint(
            "cardinality(destinations) > 0 AND destinations <@ "
            "ARRAY['ca-central-1', 'ca-west-1', 'canadacentral', 'canadaeast']::text[]",
            name="ck_allowlist_route_destinations",
        ),
    )


class Binding(Base):
    __tablename__ = "binding"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("route.id"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unverified'"))
    deployment_name: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(TS)
    last_checked_at: Mapped[datetime | None] = mapped_column(TS)
    l2_confirmed_at: Mapped[datetime | None] = mapped_column(TS)
    provider_modified_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.id"], name="fk_binding_project"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["provider_connection.tenant_id", "provider_connection.id"],
            name="fk_binding_connection",
        ),
        CheckConstraint("status IN ('unverified', 'verified')", name="ck_binding_status"),
        CheckConstraint(
            "status <> 'verified' OR (l2_confirmed_at IS NOT NULL AND last_verified_at IS NOT NULL)",
            name="ck_binding_verified_needs_l2",
        ),
        CheckConstraint(
            "route_id NOT LIKE 'azure:%' OR deployment_name IS NOT NULL", name="ck_binding_azure_deployment"
        ),
        UniqueConstraint("project_id", "alias", name="uq_binding_project_alias"),
        UniqueConstraint("tenant_id", "id", name="uq_binding_tenant_id"),
        Index("ix_binding_route", "route_id"),
    )


class Verification(Base):
    __tablename__ = "verification"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    binding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("route.id"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    provider_answer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    allowlist_version: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "binding_id"], ["binding.tenant_id", "binding.id"], name="fk_verification_binding"
        ),
        CheckConstraint(
            "result IN ('match', 'config_mismatch', 'definition_mismatch', 'access_failed', 'error')",
            name="ck_verification_result",
        ),
        CheckConstraint("grade IN ('EG-3', 'EG-4')", name="ck_verification_grade"),
        Index("ix_verification_binding_checked", "tenant_id", "binding_id", text("checked_at DESC")),
        Index(
            "ix_verification_route_match", "route_id", "checked_at", postgresql_where=text("result = 'match'")
        ),
    )


class LoggingObservation(Base):
    __tablename__ = "logging_observation"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str | None] = mapped_column(Text)
    destination_region: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["provider_connection.tenant_id", "provider_connection.id"],
            name="fk_logging_obs_connection",
        ),
        CheckConstraint("state IN ('off', 'on', 'not_readable')", name="ck_logging_obs_state"),
    )


class RequestLog(Base):
    __tablename__ = "request_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    api_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    route_id: Mapped[str | None] = mapped_column(Text)
    allowlist_version: Mapped[str | None] = mapped_column(Text)
    route_status: Mapped[str | None] = mapped_column(Text)
    binding_verified_at: Mapped[datetime | None] = mapped_column(TS)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    state: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    upstream_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    request_bytes: Mapped[int | None] = mapped_column(Integer)
    response_bytes: Mapped[int | None] = mapped_column(Integer)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(TS)
    reconciled_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        PrimaryKeyConstraint("id", "received_at"),
        CheckConstraint("endpoint IN ('chat', 'embeddings')", name="ck_request_log_endpoint"),
        CheckConstraint("char_length(alias) <= 128", name="ck_request_log_alias_len"),
        CheckConstraint(
            "state IN ('rejected', 'forwarding', 'completed', 'upstream_error', 'client_aborted', "
            "'unknown_outcome')",
            name="ck_request_log_state",
        ),
        CheckConstraint(
            "state = 'rejected' OR (route_id IS NOT NULL AND allowlist_version IS NOT NULL)",
            name="ck_request_log_decided",
        ),
        Index("ix_request_log_list", "tenant_id", "project_id", text("received_at DESC")),
        Index(
            "ix_request_log_forwarding",
            "tenant_id",
            "state",
            "received_at",
            postgresql_where=text("state = 'forwarding'"),
        ),
        Index("ix_request_log_provider_request", "tenant_id", "provider_request_id"),
        {"postgresql_partition_by": "RANGE (received_at)"},
    )


class Alert(Base):
    __tablename__ = "alert"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    sent_at: Mapped[datetime | None] = mapped_column(TS)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint(
            "kind IN ('route_suspended', 'config_mismatch', 'allowlist_change_notice', 'rejections_summary', "
            "'access_failed', 'region_incident', 'register_gap')",
            name="ck_alert_kind",
        ),
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_alert_dedupe"),
        Index(
            "ix_alert_open",
            "tenant_id",
            text("created_at DESC"),
            postgresql_where=text("acknowledged_at IS NULL"),
        ),
    )


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("actor_kind IN ('user', 'operator', 'system')", name="ck_audit_actor_kind"),
    )


class Job(Base):
    __tablename__ = "job"
    id: Mapped[uuid.UUID] = _id()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    run_after: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_at: Mapped[datetime | None] = mapped_column(TS)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("state IN ('queued', 'running', 'done', 'failed')", name="ck_job_state"),
        UniqueConstraint("kind", "dedupe_key", name="uq_job_kind_dedupe"),
        Index("ix_job_queued", "run_after", postgresql_where=text("state = 'queued'")),
    )

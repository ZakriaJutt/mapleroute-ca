"""Console JSON API for the core path (B1 subset of TRD.md "API contracts").

Sign-in (OIDC, T-4.1.1) is blocked in B1: the default authenticator admits nobody. Tests inject an
authenticator. Tenant mutations carry an ``Idempotency-Key`` header stored in ``form_token``;
a second submit returns the first result. Foreign identifiers return 404 (MH-09).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core import audit, clock, jobs, keys, policy_store, tenancy, verification
from core.allowlist import AllowlistError, PublishRefused, RouteKey, listed
from core.config import constants_hash
from core.crypto import KeyService, encrypt_secret
from core.models import (
    ApiKey,
    Binding,
    ConnectionSecret,
    FormToken,
    Project,
    ProviderConnection,
    RequestLog,
    Route,
)
from core.secretvalue import SecretValue

# Format check only. A host name is never evidence of location.
AZURE_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]{1,62}\.(openai\.azure\.com|services\.ai\.azure\.com|cognitiveservices\.azure\.com)$"
)
WRITE_ROLES = frozenset({"owner", "engineer"})


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str | None
    is_operator: bool = False


class Authenticator(Protocol):
    def __call__(self, request: Request) -> Principal | None: ...


def no_sign_in(request: Request) -> Principal | None:
    """B1 default: single sign-on is not built, so nobody is admitted."""
    return None


@dataclass
class ConsoleServices:
    factory: sessionmaker[Session]
    key_service: KeyService
    authenticator: Authenticator = no_sign_in


def create_app(services: ConsoleServices) -> FastAPI:
    app = FastAPI(title="MapleRoute console", docs_url=None, redoc_url=None, openapi_url=None)

    def principal(request: Request) -> Principal:
        p = services.authenticator(request)
        if p is None:
            raise HTTPException(401, "sign-in required")
        return p

    def tenant_member(request: Request, write: bool) -> Principal:
        p = principal(request)
        if p.tenant_id is None or p.role is None:
            raise HTTPException(404, "not found")
        if write and p.role not in WRITE_ROLES:
            raise HTTPException(403, "role not permitted")
        return p

    def operator(request: Request) -> Principal:
        p = principal(request)
        if not p.is_operator:
            raise HTTPException(403, "operator only")
        return p

    def project_or_404(s: Session, pid: uuid.UUID) -> Project:
        project = s.get(Project, pid)  # row-level security hides other tenants' rows
        if project is None:
            raise HTTPException(404, "not found")
        return project

    def idempotent(request: Request, p: Principal, compute: Callable[[Session], dict[str, Any]],
                   stored: Callable[[dict[str, Any]], dict[str, Any]] = lambda r: r) -> dict[str, Any]:
        token = request.headers.get("idempotency-key")
        if not token or len(token) > 128:
            raise HTTPException(400, "Idempotency-Key header required")
        assert p.tenant_id is not None
        for _ in range(2):
            try:
                with services.factory.begin() as s:
                    tenancy.set_tenant(s, p.tenant_id)
                    prior = s.execute(
                        select(FormToken.result_ref).where(FormToken.token == token)
                    ).scalar_one_or_none()
                    if prior is not None:
                        return dict(json.loads(prior), replayed=True)
                    result = compute(s)
                    s.add(FormToken(tenant_id=p.tenant_id, token=token, result_ref=json.dumps(stored(result)),
                                    used_at=clock.now()))
                    s.flush()
                    return result
            except IntegrityError:
                continue  # a concurrent duplicate committed first; read its result
        raise HTTPException(409, "duplicate submission in progress")

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        try:
            with services.factory() as s:
                s.execute(text("SELECT 1"))
            return JSONResponse({"status": "ok", "process": "console", "constants_hash": constants_hash()})
        except SQLAlchemyError:
            return JSONResponse({"status": "unavailable", "process": "console"}, status_code=503)

    # ------------------------------------------------------------------ tenant API
    @app.post("/api/projects/{pid}/connections")
    def create_connection(pid: uuid.UUID, body: dict[str, Any], request: Request) -> dict[str, Any]:
        p = tenant_member(request, write=True)
        provider = body.get("provider")
        if provider not in ("aws", "azure"):
            raise HTTPException(422, "provider must be aws or azure")
        if provider == "azure" and not AZURE_HOST.match(str(body.get("endpoint_host", ""))):
            raise HTTPException(422, "endpoint_host is not an Azure resource host")
        secret = body.get("secret")

        def compute(s: Session) -> dict[str, Any]:
            project_or_404(s, pid)
            conn = ProviderConnection(
                tenant_id=p.tenant_id, project_id=pid, provider=provider, account_ref=str(body.get("account_ref")),
                source_region=str(body.get("source_region")), role_arn=body.get("role_arn"),
                external_id=body.get("external_id"), endpoint_host=body.get("endpoint_host"),
                resource_group=body.get("resource_group"), state="pending",
            )
            s.add(conn)
            try:
                s.flush()
            except IntegrityError as exc:
                raise HTTPException(422, "connection fields are not valid for this provider") from exc
            if provider == "azure":
                if not isinstance(secret, str) or not secret:
                    raise HTTPException(422, "secret required for azure")
                assert p.tenant_id is not None
                env = encrypt_secret(services.key_service, p.tenant_id, conn.id, SecretValue(secret))
                s.add(ConnectionSecret(connection_id=conn.id, tenant_id=p.tenant_id, ciphertext=env.ciphertext,
                                       wrapped_data_key=env.wrapped_data_key, kms_key_arn=env.kms_key_arn))
            audit.record(s, p.tenant_id, "user", p.user_id, "connection_create", str(conn.id), {"provider": provider})
            return {"id": str(conn.id), "provider": provider, "state": conn.state}

        return idempotent(request, p, compute)

    @app.post("/api/projects/{pid}/routes")
    def bind_route(pid: uuid.UUID, body: dict[str, Any], request: Request) -> dict[str, Any]:
        p = tenant_member(request, write=True)

        def compute(s: Session) -> dict[str, Any]:
            project_or_404(s, pid)
            conn = s.get(ProviderConnection, uuid.UUID(str(body.get("connection_id"))))
            route = s.get(Route, str(body.get("route_id")))
            if conn is None or conn.project_id != pid or conn.state == "deleted":
                raise HTTPException(404, "not found")
            version = policy_store.load_active(s)
            key = RouteKey(route.provider, route.source_region, route.deployment_class, route.identifier,
                           route.model_version) if route else None
            if key is None or version is None or not listed(key, version):
                raise HTTPException(422, "route is not on the active allow-list")
            if conn.provider != key.provider or conn.source_region != key.source_region:
                raise HTTPException(422, "connection provider or Region differs from the route")
            alias = str(body.get("alias", ""))
            if not alias or len(alias) > 128:
                raise HTTPException(422, "alias required, at most 128 characters")
            binding = Binding(tenant_id=p.tenant_id, project_id=pid, connection_id=conn.id, route_id=key.id,
                              alias=alias, deployment_name=body.get("deployment_name"))
            s.add(binding)
            try:
                s.flush()
            except IntegrityError as exc:
                raise HTTPException(422, "alias already bound or deployment name missing") from exc
            jobs.enqueue(s, "verify_binding", f"{binding.id}:initial", tenant_id=p.tenant_id,
                         payload={"binding_id": str(binding.id)})
            audit.record(s, p.tenant_id, "user", p.user_id, "binding_change", str(binding.id), {"route_id": key.id})
            return {"id": str(binding.id), "alias": alias, "route_id": key.id, "status": binding.status}

        return idempotent(request, p, compute)

    @app.post("/api/projects/{pid}/bindings/{bid}/verify")
    def request_verification(pid: uuid.UUID, bid: uuid.UUID, request: Request) -> dict[str, Any]:
        p = tenant_member(request, write=True)
        token = request.headers.get("idempotency-key", "")

        def compute(s: Session) -> dict[str, Any]:
            project_or_404(s, pid)
            binding = s.get(Binding, bid)
            if binding is None or binding.project_id != pid:
                raise HTTPException(404, "not found")
            job_id = jobs.enqueue(s, "verify_binding", f"{bid}:manual:{token}", tenant_id=p.tenant_id,
                                  payload={"binding_id": str(bid)})
            return {"binding_id": str(bid), "job_id": str(job_id) if job_id else None, "queued": True}

        return idempotent(request, p, compute)

    @app.post("/api/projects/{pid}/keys")
    def create_key(pid: uuid.UUID, request: Request) -> dict[str, Any]:
        p = tenant_member(request, write=True)

        def compute(s: Session) -> dict[str, Any]:
            project_or_404(s, pid)
            new = keys.generate()
            row = ApiKey(tenant_id=p.tenant_id, project_id=pid, key_hash=new.key_hash, prefix=new.prefix,
                         last_four=new.last_four, created_by=p.user_id)
            s.add(row)
            s.flush()
            audit.record(s, p.tenant_id, "user", p.user_id, "key_create", str(row.id))
            return {"id": str(row.id), "key": new.plaintext, "prefix": new.prefix, "last_four": new.last_four}

        # The plaintext key is returned once and never stored, including in the idempotency record.
        return idempotent(request, p, compute, stored=lambda r: {**r, "key": None})

    @app.delete("/api/projects/{pid}/keys/{kid}")
    def revoke_key(pid: uuid.UUID, kid: uuid.UUID, request: Request) -> dict[str, Any]:
        p = tenant_member(request, write=True)
        with services.factory.begin() as s:
            assert p.tenant_id is not None
            tenancy.set_tenant(s, p.tenant_id)
            project_or_404(s, pid)
            row = s.get(ApiKey, kid)
            if row is None or row.project_id != pid:
                raise HTTPException(404, "not found")
            if row.state != "revoked":
                row.state, row.revoked_at = "revoked", clock.now()
                audit.record(s, p.tenant_id, "user", p.user_id, "key_revoke", str(kid))
            return {"id": str(kid), "state": "revoked"}

    @app.get("/api/projects/{pid}/requests")
    def list_requests(pid: uuid.UUID, request: Request) -> dict[str, Any]:
        p = tenant_member(request, write=False)
        with services.factory.begin() as s:
            assert p.tenant_id is not None
            tenancy.set_tenant(s, p.tenant_id)
            project_or_404(s, pid)
            rows = s.execute(
                select(RequestLog).where(RequestLog.project_id == pid)
                .order_by(RequestLog.received_at.desc()).limit(100)
            ).scalars().all()
            return {"data": [
                {"id": str(r.id), "received_at": r.received_at.isoformat(), "alias": r.alias, "route_id": r.route_id,
                 "allowlist_version": r.allowlist_version, "state": r.state, "code": r.code, "flags": list(r.flags)}
                for r in rows
            ]}

    # ------------------------------------------------------------------ operator API (/ops host in production)
    @app.post("/api/ops/allowlist/versions")
    def publish(body: dict[str, Any], request: Request) -> JSONResponse:
        p = operator(request)
        try:
            with services.factory.begin() as s:
                result = policy_store.publish_draft(s, str(body.get("version")), body.get("routes") or [], p.user_id)
        except PublishRefused as exc:
            raise HTTPException(422, {"refused_route": exc.route_id, "reason": exc.reason}) from exc
        except policy_store.VersionConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except AllowlistError as exc:
            raise HTTPException(422, str(exc)) from exc
        return JSONResponse({"version": result.version, "sha256": result.sha256_hex, "state": "draft"},
                            status_code=201 if result.created else 200)

    @app.post("/api/ops/allowlist/versions/{version}/approve")
    def approve(version: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
        p = operator(request)
        if body.get("confirm") != version:
            raise HTTPException(422, "type the version to confirm")
        try:
            with services.factory.begin() as s:
                row = policy_store.approve(s, version, p.user_id, clock.now())
                return {"version": row.version, "state": row.state,
                        "activate_after": row.activate_after.isoformat() if row.activate_after else None}
        except policy_store.NotOperator as exc:
            raise HTTPException(403, "operator only") from exc
        except AllowlistError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/ops/routes/{route_id}/suspend")
    def suspend(route_id: str, request: Request) -> dict[str, Any]:
        p = operator(request)
        now = clock.now()
        with services.factory.begin() as s:
            changed = s.execute(
                update(Route).where(Route.id == route_id, Route.global_status == "active")
                .values(global_status="suspended", status_reason="operator_suspension", status_changed_at=now)
            ).rowcount  # type: ignore[attr-defined]
            if changed:
                jobs.enqueue(s, "notify_route_suspended", f"{route_id}:{now.isoformat()}",
                             payload={"route_id": route_id, "changed_at": now.isoformat(),
                                      "reason": "operator_suspension"})
                audit.record(s, None, "operator", p.user_id, "route_suspend", route_id)
        return {"route_id": route_id, "global_status": "suspended"}

    @app.post("/api/ops/routes/{route_id}/resume")
    def resume(route_id: str, request: Request) -> dict[str, Any]:
        p = operator(request)
        try:
            with services.factory.begin() as s:
                verification.resume_route(s, route_id, p.user_id, clock.now())
                audit.record(s, None, "operator", p.user_id, "route_resume", route_id)
        except SQLAlchemyError as exc:
            raise HTTPException(409, "no matching check newer than the suspension") from exc
        return {"route_id": route_id, "global_status": "active"}

    return app

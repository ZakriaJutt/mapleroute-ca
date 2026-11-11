"""Console JSON API for the core path (B1 subset of TRD.md "API contracts").

Sign-in (B2): the default authenticator is the server-side session of ``console.auth`` (local
provider: password + TOTP; OIDC deferred). Unit tests may inject a fake authenticator; nothing
else does. Role checks use ``core.permissions``. Tenant mutations carry an ``Idempotency-Key``
header stored in ``form_token``; a second submit returns the first result. Foreign identifiers return 404 (MH-09).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from console.auth import Authenticator, Principal, SessionAuthenticator, SignInLimits, origin_of
from console.auth import register as register_auth
from core import audit, clock, identity, jobs, keys, permissions, policy_store, reports, tenancy, verification
from core.allowlist import AllowlistError, PublishRefused, RouteKey, listed
from core.config import constants_hash
from core.crypto import KeyService, encrypt_secret
from core.mail import Mailer, MemoryMailer
from core.models import (
    ApiKey,
    Binding,
    ConnectionSecret,
    FormToken,
    Project,
    ProviderConnection,
    Report,
    RequestLog,
    Route,
)
from core.secretvalue import SecretValue
from core.storage import MemoryObjectStore, ObjectStore, StorageError

# Format check only. A host name is never evidence of location.
AZURE_HOST = re.compile(
    r"^[a-z0-9][a-z0-9-]{1,62}\.(openai\.azure\.com|services\.ai\.azure\.com|cognitiveservices\.azure\.com)$"
)
__all__ = ["Authenticator", "ConsoleServices", "Principal", "create_app"]

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",  # ASVS 3.4.1
    "X-Content-Type-Options": "nosniff",  # 3.4.4
    "Referrer-Policy": "no-referrer",  # 3.4.5
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


@dataclass
class ConsoleServices:
    factory: sessionmaker[Session]  # role mapleroute_console: tenant screens and API
    key_service: KeyService
    authenticator: Authenticator | None = None  # None: the session cookie (production); tests may inject
    ops_factory: sessionmaker[Session] | None = None  # role mapleroute_operator: /ops routes only
    mailer: Mailer = field(default_factory=MemoryMailer)
    store: ObjectStore = field(default_factory=MemoryObjectStore)
    public_base_url: str = "https://console.mapleroute.localhost"
    limits: SignInLimits = field(default_factory=SignInLimits)

    def ops(self) -> sessionmaker[Session]:
        # Without an operator factory the console role is used, and the database refuses ops writes.
        return self.ops_factory or self.factory


def create_app(services: ConsoleServices) -> FastAPI:
    app = FastAPI(title="MapleRoute console", docs_url=None, redoc_url=None, openapi_url=None)
    allowed_origin = origin_of(services.public_base_url)
    authenticator: Authenticator = services.authenticator or SessionAuthenticator(services.factory, allowed_origin)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        # A cross-origin unsafe request is refused before any route, signed in or not (sign-in CSRF, 3.5.1).
        origin = request.headers.get("origin")
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and origin is not None and origin != allowed_origin:
            response: Response = JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def principal(request: Request) -> Principal:
        p = authenticator(request)
        if p is None:
            raise HTTPException(401, "sign-in required")
        return p

    def tenant_member(request: Request, action: str) -> Principal:
        p = principal(request)
        if p.tenant_id is None or p.role is None:
            raise HTTPException(404, "not found")
        if not permissions.allowed(p.role, action):
            raise HTTPException(403, "role not permitted")
        return p

    def operator(request: Request, sensitive: bool = False) -> Principal:
        """Operator routes. Approve, suspend and resume also need a second factor and an authentication
        under five minutes old (TRD.md "Operator sign-in", ASVS 6.8.4, 7.5.3)."""
        p = principal(request)
        if not p.is_operator:
            raise HTTPException(403, "operator only")
        if sensitive and (not identity.has_mfa(p.amr) or not identity.recent_auth(p.auth_time, clock.now())):
            raise HTTPException(401, "re-authentication required")
        return p

    register_auth(app, factory=services.factory, key_service=services.key_service, mailer=services.mailer,
                  limits=services.limits, public_base_url=services.public_base_url, principal=principal)

    def project_or_404(s: Session, pid: uuid.UUID) -> Project:
        project = s.get(Project, pid)  # row-level security hides other tenants' rows
        if project is None:
            raise HTTPException(404, "not found")
        return project

    def idempotent(request: Request, p: Principal, compute: Callable[[Session], dict[str, Any]],
                   stored: Callable[[dict[str, Any]], dict[str, Any]] = lambda r: r) -> dict[str, Any]:
        raw = request.headers.get("idempotency-key")
        if not raw or len(raw) > 128:
            raise HTTPException(400, "Idempotency-Key header required")
        # Scoped to method and path: the same key on another endpoint is a different submission (B1-010).
        token = f"{request.method} {request.url.path} {raw}"
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
        except SQLAlchemyError:
            return JSONResponse({"status": "unavailable", "process": "console"}, status_code=503)
        deps = {"database": "ok", "mail": "ok" if services.mailer.ping() else "unavailable",
                "storage": "ok" if services.store.ping() else "unavailable"}
        ok = all(v == "ok" for v in deps.values())
        return JSONResponse({"status": "ok" if ok else "unavailable", "process": "console",
                             "constants_hash": constants_hash(), "dependencies": deps}, status_code=200 if ok else 503)

    # ------------------------------------------------------------------ tenant API
    @app.post("/api/projects/{pid}/connections")
    def create_connection(pid: uuid.UUID, body: dict[str, Any], request: Request) -> dict[str, Any]:
        p = tenant_member(request, "connection.write")
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
        p = tenant_member(request, "route.write")

        def compute(s: Session) -> dict[str, Any]:
            project_or_404(s, pid)
            try:
                connection_id = uuid.UUID(str(body.get("connection_id")))
            except ValueError as exc:
                raise HTTPException(422, "connection_id must be a UUID") from exc
            conn = s.get(ProviderConnection, connection_id)
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
            # Only the identifying columns: the console role cannot write any verification field (B1-005).
            try:
                with s.begin_nested():
                    row = s.execute(
                        insert(Binding).values(tenant_id=p.tenant_id, project_id=pid, connection_id=conn.id,
                                               route_id=key.id, alias=alias,
                                               deployment_name=body.get("deployment_name"))
                        .returning(Binding.id, Binding.status)
                    ).one()
            except IntegrityError as exc:
                raise HTTPException(422, "alias already bound or deployment name missing") from exc
            jobs.enqueue(s, "verify_binding", f"{row.id}:initial", tenant_id=p.tenant_id,
                         payload={"binding_id": str(row.id)})
            audit.record(s, p.tenant_id, "user", p.user_id, "binding_change", str(row.id), {"route_id": key.id})
            return {"id": str(row.id), "alias": alias, "route_id": key.id, "status": row.status}

        return idempotent(request, p, compute)

    @app.post("/api/projects/{pid}/bindings/{bid}/verify")
    def request_verification(pid: uuid.UUID, bid: uuid.UUID, request: Request) -> dict[str, Any]:
        p = tenant_member(request, "route.write")
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
        p = tenant_member(request, "key.write")

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
        p = tenant_member(request, "key.write")
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
        p = tenant_member(request, "request_log.read")
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

    # ------------------------------------------------------------------ reports (stored files, B2)
    @app.get("/api/reports")
    def list_reports(request: Request) -> dict[str, Any]:
        p = tenant_member(request, "report.read")
        with services.factory.begin() as s:
            assert p.tenant_id is not None
            tenancy.set_tenant(s, p.tenant_id)
            rows = s.execute(select(Report).where(Report.state == "ready")
                             .order_by(Report.period_start.desc())).scalars().all()
            base = services.public_base_url.rstrip("/")
            return {"data": [
                {"id": str(r.id), "kind": r.kind, "period_start": r.period_start.isoformat(),
                 "period_end": r.period_end.isoformat(), "sha256": r.sha256.hex() if r.sha256 else None,
                 # R-16: built from the one public base URL; the file endpoint needs the session.
                 "file_url": f"{base}/api/reports/{r.id}/file"}
                for r in rows
            ]}

    @app.get("/api/reports/{rid}/file")
    def report_file(rid: uuid.UUID, request: Request) -> Response:
        """The only way a stored file leaves: an authorised request by a member of the owning tenant."""
        p = tenant_member(request, "report.read")
        assert p.tenant_id is not None
        try:
            with services.factory.begin() as s:
                tenancy.set_tenant(s, p.tenant_id)
                row, data = reports.read_report(s, services.store, p.tenant_id, rid)
                audit.record(s, p.tenant_id, "user", p.user_id, "report_download", str(rid))
        except reports.ReportUnavailable as exc:
            raise HTTPException(404, "not found") from exc
        except StorageError as exc:
            raise HTTPException(503, "report storage is unavailable") from exc
        return Response(data, media_type=row.content_type or "application/octet-stream", headers={
            "Content-Disposition": f'attachment; filename="mapleroute-report-{row.period_start}-{row.kind}.'
                                   f'{(row.object_key or "x.bin").rsplit(".", 1)[-1]}"',
            "X-Report-SHA256": row.sha256.hex() if row.sha256 else ""})

    # ------------------------------------------------------------------ operator API (/ops host in production)
    @app.post("/api/ops/allowlist/versions")
    def publish(body: dict[str, Any], request: Request) -> JSONResponse:
        p = operator(request)
        try:
            with services.ops().begin() as s:
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
        p = operator(request, sensitive=True)
        if body.get("confirm") != version:
            raise HTTPException(422, "type the version to confirm")
        try:
            with services.ops().begin() as s:
                row = policy_store.approve(s, version, p.user_id, clock.now())
                return {"version": row.version, "state": row.state,
                        "activate_after": row.activate_after.isoformat() if row.activate_after else None}
        except policy_store.NotOperator as exc:
            raise HTTPException(403, "operator only") from exc
        except AllowlistError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/ops/routes/{route_id}/suspend")
    def suspend(route_id: str, request: Request) -> dict[str, Any]:
        p = operator(request, sensitive=True)
        now = clock.now()
        with services.ops().begin() as s:
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
        p = operator(request, sensitive=True)
        try:
            with services.ops().begin() as s:
                verification.resume_route(s, route_id, p.user_id, clock.now())
                audit.record(s, None, "operator", p.user_id, "route_resume", route_id)
        except SQLAlchemyError as exc:
            raise HTTPException(409, "no matching check newer than the suspension") from exc
        return {"route_id": route_id, "global_status": "active"}

    return app

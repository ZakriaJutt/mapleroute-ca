"""Data plane: OpenAI-format endpoints on the fail-closed path (T-3.1.2, T-3.1.3, T-3.1.6, MH-01, MH-03).

Order per request: authenticate the key, set the tenant from it, evaluate ``forwardable``, commit
the log row, then forward once. Every failure before the commit rejects with ``forwarded: false``.
Bodies and credentials exist only in memory; nothing here logs them.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core import clock, keys, locks, policy_store, requestlog, tenancy
from core.allowlist import RouteKey
from core.config import ALIAS_MAX_LEN, UNSUPPORTED_PARAMETERS, constants_hash
from core.crypto import KeyService, decrypt_secret
from core.eligibility import BindingState, Decision, Rejection, evaluate
from core.errors import CONTRACT, Code, error_body
from core.logging import correlation, log_event
from core.models import ApiKey, Binding, ConnectionSecret, ProviderConnection, Route
from core.providers import AwsSessionProvider, InferenceClient, UpstreamError, UpstreamTimeout
from core.secretvalue import SecretValue
from gateway.forward import forward, forward_stream


class NoExceptionText:
    """Outermost-but-one ASGI layer: any exception that escapes a handler becomes a generic 500 and
    is logged by class only. Starlette's ServerErrorMiddleware would re-raise it to the server,
    which logs the exception text (B1-006)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Any) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # noqa: BLE001 - never let exception text reach the server log
            log_event("unhandled_exception", error_class=type(exc).__name__, http_status=500)
            if started:
                return
            body = json.dumps({"error": {"type": "server_error", "code": None, "message": "Internal error.",
                                         "param": None, "request_id": None, "allowlist_version": None,
                                         "forwarded": None}}).encode()
            await send({"type": "http.response.start", "status": 500,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})


class RateLimiter:
    """Per-key fixed one-minute window, in process memory (no shared cache, R-05)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._lock = threading.Lock()
        self._windows: dict[uuid.UUID, tuple[int, int]] = {}

    def allow(self, key_id: uuid.UUID, now: datetime) -> bool:
        minute = int(now.timestamp() // 60)
        with self._lock:
            window, count = self._windows.get(key_id, (minute, 0))
            if window != minute:
                window, count = minute, 0
            if count >= self.per_minute:
                return False
            self._windows[key_id] = (window, count + 1)
            return True


@dataclass
class GatewayServices:
    factory: sessionmaker[Session]
    clients: dict[str, InferenceClient]
    aws_sessions: AwsSessionProvider
    key_service: KeyService
    limiter: RateLimiter = field(default_factory=lambda: RateLimiter(600))


@dataclass
class _Ctx:
    request_id: uuid.UUID
    received_at: datetime
    endpoint: str
    alias: str = ""
    allowlist_version: str | None = None
    tenant_id: uuid.UUID | None = None


def _headers(ctx: _Ctx, route_id: str | None = None) -> dict[str, str]:
    h = {"X-MapleRoute-Request-Id": str(ctx.request_id)}
    if route_id:
        h["X-MapleRoute-Route"] = route_id
    if ctx.allowlist_version:
        h["X-MapleRoute-Allowlist-Version"] = ctx.allowlist_version
    return h


def _reject(ctx: _Ctx, code: Code, param: str | None = None, **extra: Any) -> JSONResponse:
    log_event("request_rejected", request_id=ctx.request_id, code=code.value,
              http_status=CONTRACT[code].http_status, allowlist_version=ctx.allowlist_version)
    body = error_body(code, request_id=str(ctx.request_id), allowlist_version=ctx.allowlist_version,
                      alias=ctx.alias or None, param=param, **extra)
    return JSONResponse(body, status_code=CONTRACT[code].http_status, headers=_headers(ctx))


def _bearer(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _load_binding_state(
    s: Session, project_id: uuid.UUID, alias: str
) -> tuple[BindingState, ProviderConnection] | None:
    row = s.execute(
        select(Binding, Route, ProviderConnection)
        .join(Route, Route.id == Binding.route_id)
        .join(ProviderConnection, ProviderConnection.id == Binding.connection_id)
        .where(Binding.project_id == project_id, Binding.alias == alias)
    ).one_or_none()
    if row is None:
        return None
    b, r, c = row
    state = BindingState(
        binding_id=b.id, tenant_id=b.tenant_id, project_id=b.project_id, alias=b.alias,
        route=RouteKey(r.provider, r.source_region, r.deployment_class, r.identifier, r.model_version),
        route_global_status=r.global_status, status=b.status, last_verified_at=b.last_verified_at,
        deployment_name=b.deployment_name, connection_id=c.id, connection_provider=c.provider,
        connection_region=c.source_region, connection_state=c.state, endpoint_host=c.endpoint_host,
    )
    return state, c


def _unsupported(body: dict[str, Any]) -> str | None:
    if body.get("store") is True:
        return "store"
    for name in sorted(UNSUPPORTED_PARAMETERS):
        if name in body:
            return name
    return None


def create_app(services: GatewayServices) -> FastAPI:
    app = FastAPI(title="MapleRoute gateway", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(NoExceptionText)

    def authenticate(request: Request) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID] | Code:
        token = _bearer(request)
        if token is None or not keys.well_formed(token):
            return Code.INVALID_API_KEY
        try:
            with services.factory.begin() as s:
                row = s.execute(
                    text("SELECT api_key_id, tenant_id, project_id, state FROM resolve_api_key(:h)"),
                    {"h": keys.hash_key(token)},
                ).one_or_none()
        except SQLAlchemyError:
            return Code.AUDIT_UNAVAILABLE
        if row is None or row.state != "active":
            return Code.INVALID_API_KEY
        return row.api_key_id, row.tenant_id, row.project_id

    def credential_for(decision: Decision, conn: ProviderConnection, secret: ConnectionSecret | None) -> SecretValue:
        if decision.provider == "aws":
            assert conn.role_arn and conn.external_id
            return services.aws_sessions.assume_role(conn.role_arn, conn.external_id, decision.source_region)
        if secret is None:
            raise LookupError("no stored credential")
        return decrypt_secret(services.key_service, conn.tenant_id, conn.id, bytes(secret.ciphertext),
                              bytes(secret.wrapped_data_key))

    def handle(request: Request, raw: bytes, endpoint: str) -> Response:
        ctx = _Ctx(uuid.uuid4(), clock.now(), endpoint)
        with correlation(str(ctx.request_id)):
            auth = authenticate(request)
            if isinstance(auth, Code):
                return _reject(ctx, auth)
            key_id, tenant_id, project_id = auth
            ctx.tenant_id = tenant_id
            try:
                parsed = json.loads(raw) if raw else None
            except ValueError:
                parsed = None
            body: dict[str, Any] = parsed if isinstance(parsed, dict) else {}
            model = body.get("model")
            ctx.alias = model[:ALIAS_MAX_LEN] if isinstance(model, str) else ""
            stream = endpoint == "chat" and body.get("stream") is True
            pre: tuple[Code, str | None] | None = None
            if not isinstance(parsed, dict):
                pre = (Code.UNSUPPORTED_PARAMETER, None)
            elif isinstance(model, str) and len(model) > ALIAS_MAX_LEN:
                # Never serve a truncated alias on another binding (B1-008); the row keeps the prefix.
                pre = (Code.ROUTE_NOT_ELIGIBLE, "model")
            elif (param := _unsupported(body)) is not None:
                pre = (Code.UNSUPPORTED_PARAMETER, param)
            elif not services.limiter.allow(key_id, ctx.received_at):
                pre = (Code.RATE_LIMITED, None)

            outcome: Decision | Rejection
            credential: SecretValue | None = None
            try:
                with services.factory.begin() as s:
                    tenancy.set_tenant(s, tenant_id)
                    version = policy_store.load_active(s)
                    ctx.allowlist_version = version.version if version else None
                    if not pre:
                        # Shared binding lock: a mismatch being applied for this binding finishes first
                        # (B1-001); every row committed here is visible to its window flagging.
                        locks.binding_lock(s, project_id, ctx.alias, shared=True)
                    found = None if pre else _load_binding_state(s, project_id, ctx.alias)
                    if pre:
                        outcome = Rejection(pre[0], allowlist_version=ctx.allowlist_version)
                    else:
                        outcome = evaluate(found[0] if found else None, version, ctx.received_at)
                    if isinstance(outcome, Decision) and found is not None:
                        try:
                            secret = s.get(ConnectionSecret, found[1].id)
                            credential = credential_for(outcome, found[1], secret)
                        except Exception as exc:  # noqa: BLE001 - no credential: reject, never forward
                            log_event("credential_unavailable", request_id=ctx.request_id,
                                      error_class=type(exc).__name__)
                            outcome = Rejection(Code.ROUTE_UNVERIFIED, outcome.route_id, outcome.allowlist_version,
                                                outcome.route_status, outcome.binding_verified_at)
                    if isinstance(outcome, Rejection):
                        row = requestlog.NewRow(
                            ctx.request_id, tenant_id, project_id, key_id, ctx.received_at, endpoint, ctx.alias,
                            "rejected", outcome.code.value, CONTRACT[outcome.code].http_status, outcome.route_id,
                            outcome.allowlist_version, outcome.route_status, outcome.binding_verified_at, len(raw),
                        )
                    else:
                        row = requestlog.NewRow(
                            ctx.request_id, tenant_id, project_id, key_id, ctx.received_at, endpoint, ctx.alias,
                            "forwarding", None, None, outcome.route_id, outcome.allowlist_version,
                            outcome.route_status, outcome.binding_verified_at, len(raw),
                        )
                    requestlog.insert(s, row)
                    s.execute(update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=ctx.received_at))
                # committed: only now may a byte go upstream (AD-04)
            except SQLAlchemyError as exc:
                log_event("audit_insert_failed", request_id=ctx.request_id, error_class=type(exc).__name__)
                return _reject(ctx, Code.AUDIT_UNAVAILABLE)

            if isinstance(outcome, Rejection):
                return _reject(ctx, outcome.code, param=pre[1] if pre else None)
            assert credential is not None
            if stream:
                return _stream(ctx, outcome, body, credential)
            return _send(ctx, outcome, body, credential)

    def _finish(ctx: _Ctx, state: str, **fields: Any) -> None:
        assert ctx.tenant_id is not None
        try:
            with services.factory.begin() as s:
                tenancy.set_tenant(s, ctx.tenant_id)
                requestlog.transition(s, ctx.request_id, ctx.received_at, state, clock.now(), **fields)
        except SQLAlchemyError as exc:
            # The row stays `forwarding`; sweep_outcomes moves it to `unknown_outcome` (R-02).
            log_event("completion_update_failed", request_id=ctx.request_id, error_class=type(exc).__name__)

    def _send(ctx: _Ctx, d: Decision, body: dict[str, Any], credential: SecretValue) -> Response:
        started = time.monotonic()
        try:
            resp = forward(services.clients, d, ctx.endpoint, body, credential)
        except UpstreamTimeout:
            _finish(ctx, "upstream_error", code=Code.UPSTREAM_TIMEOUT.value, http_status=504,
                    upstream_ms=int((time.monotonic() - started) * 1000))
            return _upstream_reject(ctx, d, Code.UPSTREAM_TIMEOUT)
        except UpstreamError as err:
            _finish(ctx, "upstream_error", code=Code.UPSTREAM_ERROR.value, http_status=502,
                    upstream_ms=int((time.monotonic() - started) * 1000))
            return _upstream_reject(ctx, d, Code.UPSTREAM_ERROR, provider_status=err.status,
                                    provider_code=err.provider_code)
        except Exception as exc:  # noqa: BLE001 - adapter failure: class only, never its text (B1-006)
            _adapter_failed(ctx, exc)
            return _upstream_reject(ctx, d, Code.UPSTREAM_ERROR)
        payload = json.dumps(resp.body).encode()
        elapsed = int((time.monotonic() - started) * 1000)
        _finish(ctx, "completed", http_status=200, input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens, provider_request_id=resp.provider_request_id,
                response_bytes=len(payload), upstream_ms=elapsed,
                latency_ms=int((clock.now() - ctx.received_at).total_seconds() * 1000))
        log_event("request_completed", request_id=ctx.request_id, route_id=d.route_id, http_status=200,
                  upstream_ms=elapsed)
        return Response(payload, media_type="application/json", headers=_headers(ctx, d.route_id))

    def _upstream_reject(ctx: _Ctx, d: Decision, code: Code, **extra: Any) -> JSONResponse:
        log_event("upstream_failed", request_id=ctx.request_id, route_id=d.route_id, code=code.value)
        body = error_body(code, request_id=str(ctx.request_id), allowlist_version=ctx.allowlist_version,
                          alias=ctx.alias or None, **extra)
        return JSONResponse(body, status_code=CONTRACT[code].http_status, headers=_headers(ctx, d.route_id))

    def _adapter_failed(ctx: _Ctx, exc: BaseException) -> None:
        log_event("adapter_failed", request_id=ctx.request_id, error_class=type(exc).__name__,
                  code=Code.UPSTREAM_ERROR.value)
        _finish(ctx, "upstream_error", code=Code.UPSTREAM_ERROR.value, http_status=502)

    def _stream(ctx: _Ctx, d: Decision, body: dict[str, Any], credential: SecretValue) -> Response:
        try:
            upstream = forward_stream(services.clients, d, body, credential)
            first = next(upstream, None)
        except UpstreamTimeout:
            _finish(ctx, "upstream_error", code=Code.UPSTREAM_TIMEOUT.value, http_status=504)
            return _upstream_reject(ctx, d, Code.UPSTREAM_TIMEOUT)
        except UpstreamError as err:
            _finish(ctx, "upstream_error", code=Code.UPSTREAM_ERROR.value, http_status=502)
            return _upstream_reject(ctx, d, Code.UPSTREAM_ERROR, provider_status=err.status,
                                    provider_code=err.provider_code)
        except Exception as exc:  # noqa: BLE001 - adapter failure: class only, never its text (B1-006)
            _adapter_failed(ctx, exc)
            return _upstream_reject(ctx, d, Code.UPSTREAM_ERROR)
        return StreamingResponse(
            relay(ctx, first, upstream), media_type="text/event-stream", headers=_headers(ctx, d.route_id)
        )

    def relay(ctx: _Ctx, first: bytes | None, upstream: Iterator[bytes]) -> Iterator[bytes]:
        """Pass chunks through unbuffered. A client disconnect closes this generator: client_aborted."""
        sent = 0
        state, code = "completed", None
        try:
            if first is not None:
                sent += len(first)
                yield first
            for chunk in upstream:
                sent += len(chunk)
                yield chunk
        except GeneratorExit:
            state = "client_aborted"
            raise
        except (UpstreamError, UpstreamTimeout):
            state, code = "upstream_error", Code.UPSTREAM_ERROR.value
        except Exception as exc:  # noqa: BLE001 - mid-stream adapter failure: end the stream, log class only
            state, code = "upstream_error", Code.UPSTREAM_ERROR.value
            log_event("adapter_failed", request_id=ctx.request_id, error_class=type(exc).__name__)
        finally:
            _finish(ctx, state, code=code, http_status=200, response_bytes=sent)

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        return await _dispatch(request, "chat")

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> Response:
        return await _dispatch(request, "embeddings")

    async def _dispatch(request: Request, endpoint: str) -> Response:
        raw = await request.body()
        return await run_in_threadpool(handle, request, raw, endpoint)

    @app.get("/v1/models")
    def models(request: Request) -> Response:
        ctx = _Ctx(uuid.uuid4(), clock.now(), "chat")
        auth = authenticate(request)
        if isinstance(auth, Code):
            return _reject(ctx, auth)
        _, tenant_id, project_id = auth
        try:
            with services.factory.begin() as s:
                tenancy.set_tenant(s, tenant_id)
                version = policy_store.load_active(s)
                aliases = s.execute(select(Binding.alias).where(Binding.project_id == project_id)).scalars().all()
                usable = []
                for alias in aliases:
                    found = _load_binding_state(s, project_id, alias)
                    if found and isinstance(evaluate(found[0], version, ctx.received_at), Decision):
                        usable.append(alias)
        except SQLAlchemyError:
            return _reject(ctx, Code.AUDIT_UNAVAILABLE)
        data = [{"id": a, "object": "model", "owned_by": "mapleroute"} for a in sorted(usable)]
        return JSONResponse({"object": "list", "data": data}, headers=_headers(ctx))

    @app.get("/healthz")
    def healthz() -> Response:
        try:
            with services.factory() as s:
                s.execute(text("SELECT 1"))
            return JSONResponse({"status": "ok", "process": "gateway", "constants_hash": constants_hash()})
        except SQLAlchemyError:
            return JSONResponse({"status": "unavailable", "process": "gateway"}, status_code=503)

    app.state.services = services
    return app

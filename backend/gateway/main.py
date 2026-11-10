"""Gateway entry point: ``python -m gateway.main``. B1 wires the provider fakes only."""

from __future__ import annotations

import uvicorn

from core.config import constants_hash, settings
from core.crypto import local_key_service
from core.db import session_factory
from core.fakes import FakeAwsSessions, FakeInference
from core.logging import configure, log_event
from gateway.app import GatewayServices, RateLimiter, create_app


def build() -> object:
    cfg = settings()
    fake = FakeInference()
    services = GatewayServices(
        factory=session_factory(),
        clients={"aws": fake, "azure": fake},
        aws_sessions=FakeAwsSessions(),
        key_service=local_key_service(),
        limiter=RateLimiter(cfg.rate_limit_per_minute),
    )
    return create_app(services)


def main() -> None:
    configure()
    cfg = settings()
    log_event("gateway_start", process="gateway", constants_hash=constants_hash(), port=cfg.gateway_port)
    # access_log off: request lines are emitted by core.logging with the allow-listed fields only.
    uvicorn.run(build(), host="127.0.0.1", port=cfg.gateway_port, access_log=False, log_level="warning")  # type: ignore[arg-type]


if __name__ == "__main__":
    main()

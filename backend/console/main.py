"""Console entry point: ``python -m console.main``. Sign-in through the local identity provider;
mail through SMTP (Mailpit locally) and report files through S3 (MinIO locally), from settings."""

from __future__ import annotations

import uvicorn

from console.app import ConsoleServices, create_app
from core.config import constants_hash, settings
from core.crypto import local_key_service
from core.db import session_factory
from core.logging import configure, log_event, quiet_server_loggers
from core.mail import SmtpMailer
from core.storage import S3ObjectStore


def main() -> None:
    configure()
    cfg = settings()
    log_event("console_start", process="console", constants_hash=constants_hash(), port=cfg.console_port)
    app = create_app(ConsoleServices(
        session_factory(cfg.console_database_url), local_key_service(),
        ops_factory=session_factory(cfg.operator_database_url),
        mailer=SmtpMailer.from_settings(cfg), store=S3ObjectStore.from_settings(cfg),
        public_base_url=cfg.public_base_url,
    ))
    quiet_server_loggers()
    uvicorn.run(app, host="127.0.0.1", port=cfg.console_port, access_log=False, log_level="warning",
                log_config=None)


if __name__ == "__main__":
    main()

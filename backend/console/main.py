"""Console entry point: ``python -m console.main``. Sign-in is not built in B1 (admits nobody)."""

from __future__ import annotations

import uvicorn

from console.app import ConsoleServices, create_app
from core.config import constants_hash, settings
from core.crypto import local_key_service
from core.db import session_factory
from core.logging import configure, log_event


def main() -> None:
    configure()
    cfg = settings()
    log_event("console_start", process="console", constants_hash=constants_hash(), port=cfg.console_port)
    app = create_app(ConsoleServices(session_factory(), local_key_service()))
    uvicorn.run(app, host="127.0.0.1", port=cfg.console_port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()

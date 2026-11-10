"""Structured JSON logging with a field allow-list and a correlation ID (T-3.1.8, R-07, R-12).

No web-framework imports here. Bodies, credential headers and provider error text are never
passed to the logger; anything not in ``ALLOWED_FIELDS`` is dropped before formatting, so a
caller mistake cannot leak content. There is no debug switch that widens the list (AD-05).
"""

from __future__ import annotations

import contextvars
import json
import logging as _std
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)

ALLOWED_FIELDS = frozenset(
    {
        "event",
        "process",
        "tenant_id",
        "project_id",
        "request_id",
        "route_id",
        "allowlist_version",
        "binding_id",
        "connection_id",
        "code",
        "http_status",
        "state",
        "result",
        "reason",
        "job_kind",
        "job_id",
        "attempts",
        "latency_ms",
        "upstream_ms",
        "count",
        "constants_hash",
        "port",
        "status",
        "provider",
        "error_class",
    }
)

_LOGGER_NAME = "mapleroute"


def get_correlation_id() -> str | None:
    return _correlation_id.get()


@contextmanager
def correlation(correlation_id: str) -> Iterator[None]:
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)


def filter_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in ALLOWED_FIELDS:
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            out[key] = value
        else:
            out[key] = str(value)
    return out


class _JsonFormatter(_std.Formatter):
    def format(self, record: _std.LogRecord) -> str:
        fields = getattr(record, "mr_fields", {})
        doc: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "correlation_id": getattr(record, "mr_correlation_id", None),
            **fields,
        }
        return json.dumps(doc, sort_keys=True)


def configure(stream: Any = None) -> None:
    logger = _std.getLogger(_LOGGER_NAME)
    logger.handlers.clear()
    handler = _std.StreamHandler(stream or sys.stdout)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(_std.INFO)
    logger.propagate = False


def log_event(event: str, level: int = _std.INFO, **fields: Any) -> None:
    """Emit one structured line. Only allow-listed fields survive."""
    safe = filter_fields({"event": event, **fields})
    _std.getLogger(_LOGGER_NAME).log(
        level, event, extra={"mr_fields": safe, "mr_correlation_id": get_correlation_id()}
    )

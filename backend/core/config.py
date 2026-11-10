"""The only place configuration and shared constants are read (AGENTS.md, R-06).

Environment variables are read once, by ``settings()``. Constants that decide
eligibility live here so every process uses the same values; ``constants_hash``
lets each process print the same fingerprint at start (IT-18).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

# --- Eligibility constants (TRD.md "Eligible routes") ---------------------------------
CANADA: dict[str, frozenset[str]] = {
    "aws": frozenset({"ca-central-1", "ca-west-1"}),
    "azure": frozenset({"canadacentral", "canadaeast"}),
}
CLASSES: dict[str, frozenset[str]] = {
    "aws": frozenset({"in_region", "geo_ca"}),
    "azure": frozenset({"Standard", "ProvisionedManaged"}),
}
# Validity of the last matching check; the worst-case bound, not the interval.
VALIDITY: dict[str, timedelta] = {"aws": timedelta(hours=24), "azure": timedelta(hours=1)}
CHECK_INTERVAL: dict[str, timedelta] = {"aws": timedelta(hours=6), "azure": timedelta(minutes=15)}
# Consecutive failed checks that raise an access_failed alert (TRD.md residual window).
FAILED_CHECKS_ALERT_THRESHOLD = 2
# sweep_outcomes moves rows in `forwarding` older than this to `unknown_outcome`.
FORWARDING_SWEEP_AFTER = timedelta(minutes=15)
ALIAS_MAX_LEN = 128
# Gateway timeouts (TRD.md "Jobs, retries, timeouts").
CONNECT_TIMEOUT_S = 5
FIRST_BYTE_TIMEOUT_S = 60
TOTAL_TIMEOUT_S = 600
# Request parameters that need provider-side state or storage (error `unsupported_parameter`).
UNSUPPORTED_PARAMETERS = frozenset(
    {"files", "file_ids", "attachments", "batch", "background", "previous_response_id"}
)


def constants_hash() -> str:
    """Fingerprint of the shared constants; printed by every process at start (R-06)."""
    payload = {
        "canada": {k: sorted(v) for k, v in CANADA.items()},
        "classes": {k: sorted(v) for k, v in CLASSES.items()},
        "validity": {k: v.total_seconds() for k, v in VALIDITY.items()},
        "interval": {k: v.total_seconds() for k, v in CHECK_INTERVAL.items()},
        "failed_alert": FAILED_CHECKS_ALERT_THRESHOLD,
        "sweep": FORWARDING_SWEEP_AFTER.total_seconds(),
        "unsupported": sorted(UNSUPPORTED_PARAMETERS),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True)
class Settings:
    gateway_database_url: str
    console_database_url: str
    worker_database_url: str
    operator_database_url: str
    migrate_database_url: str
    environment: str
    provider_mode: str
    rate_limit_per_minute: int
    fake_kms_key_hex: str | None
    gateway_port: int
    console_port: int
    public_base_url: str


ALLOWED_PROVIDER_MODES = frozenset({"fake"})


@lru_cache(maxsize=1)
def settings() -> Settings:
    env = os.environ
    db = env.get("MAPLEROUTE_DATABASE", "mapleroute_dev")

    def role_url(role: str) -> str:
        default = f"postgresql+psycopg://mapleroute_{role}@localhost:5432/{db}"
        return env.get(f"MAPLEROUTE_{role.upper()}_DATABASE_URL", default)

    s = Settings(
        gateway_database_url=role_url("gateway"),
        console_database_url=role_url("console"),
        worker_database_url=role_url("worker"),
        operator_database_url=role_url("operator"),
        migrate_database_url=env.get(
            "MAPLEROUTE_MIGRATE_DATABASE_URL", "postgresql+psycopg://zakria@localhost:5432/mapleroute_dev"
        ),
        environment=env.get("MAPLEROUTE_ENV", "local"),
        # B1: only fakes exist. Real Bedrock/Azure adapters are blocked (no accounts).
        provider_mode=env.get("MAPLEROUTE_PROVIDER_MODE", "fake"),
        rate_limit_per_minute=int(env.get("MAPLEROUTE_RATE_LIMIT_PER_MINUTE", "600")),
        fake_kms_key_hex=env.get("MAPLEROUTE_FAKE_KMS_KEY_HEX"),
        gateway_port=int(env.get("MAPLEROUTE_GATEWAY_PORT", "8110")),
        console_port=int(env.get("MAPLEROUTE_CONSOLE_PORT", "3110")),
        public_base_url=env.get("MAPLEROUTE_PUBLIC_BASE_URL", "http://localhost:3110"),
    )
    if s.provider_mode not in ALLOWED_PROVIDER_MODES:
        raise RuntimeError(f"provider mode {s.provider_mode!r} is not implemented; only 'fake' exists")
    return s

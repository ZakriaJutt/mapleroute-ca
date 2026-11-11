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
from pathlib import Path

from core.secretvalue import SecretValue

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
# One check of a binding at a time (B1-003): a check holds the binding's lease for its whole run,
# provider reads included. A lease older than this is taken over (a dead worker cannot block), so
# every provider read timeout must be well below it.
CHECK_LEASE = timedelta(minutes=2)
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

# --- Console sign-in (B2; TRD.md "Identity", ASVS 7.1.1) -----------------------------
SESSION_IDLE = timedelta(minutes=30)  # 7.3.1: re-authentication after 30 minutes without a request
SESSION_ABSOLUTE = timedelta(hours=12)  # 7.3.2: re-authentication at most 12 hours after sign-in
OPERATOR_REAUTH = timedelta(minutes=5)  # approve, suspend, resume need an authentication this recent
ENROL_LINK_TTL = timedelta(minutes=15)  # emailed enrolment link, one use
INVITE_TTL = timedelta(days=7)  # emailed invitation link, one use, bound to the invited email
LOCKOUT_THRESHOLD = 10  # consecutive failed sign-ins before the credential is locked
LOCKOUT_PERIOD = timedelta(minutes=15)
PASSWORD_MIN, PASSWORD_MAX = 12, 128  # ASVS 6.2.1 (at least 8) and 6.2.9 (at least 64 allowed)
SESSION_COOKIE = "__Host-mr_session"
REPORT_LINK_TTL_S = 300  # signed report links last 5 minutes (TRD.md API contracts, R-16)


def constants_hash() -> str:
    """Fingerprint of the shared constants; printed by every process at start (R-06)."""
    payload = {
        "canada": {k: sorted(v) for k, v in CANADA.items()},
        "classes": {k: sorted(v) for k, v in CLASSES.items()},
        "validity": {k: v.total_seconds() for k, v in VALIDITY.items()},
        "interval": {k: v.total_seconds() for k, v in CHECK_INTERVAL.items()},
        "failed_alert": FAILED_CHECKS_ALERT_THRESHOLD,
        "sweep": FORWARDING_SWEEP_AFTER.total_seconds(),
        "check_lease": CHECK_LEASE.total_seconds(),
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
    # Console sign-in. Only the local provider is built (B2); OIDC is deferred (TRD.md AD-13).
    identity_providers: frozenset[str]
    # Mail: local Mailpit has no authentication; production sets a provider's host and credentials.
    smtp_host: str
    smtp_port: int
    smtp_starttls: bool
    smtp_username: str | None
    smtp_password: SecretValue | None
    mail_from: str
    # Object storage (reports). Local MinIO sets an endpoint; production uses S3 in ca-central-1.
    s3_endpoint_url: str | None
    s3_region: str
    s3_bucket: str
    s3_access_key_id: str | None
    s3_secret_access_key: SecretValue | None


ALLOWED_PROVIDER_MODES = frozenset({"fake"})
ALLOWED_IDENTITY_PROVIDERS = frozenset({"local"})
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of the gitignored backend/.env; the process environment wins."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


@lru_cache(maxsize=1)
def settings() -> Settings:
    env = {**_env_file(Path(os.environ.get("MAPLEROUTE_ENV_FILE", str(ENV_FILE)))), **os.environ}
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
        identity_providers=frozenset(
            p.strip() for p in env.get("MAPLEROUTE_IDENTITY_PROVIDERS", "local").split(",") if p.strip()
        ),
        smtp_host=env.get("MAPLEROUTE_SMTP_HOST", "127.0.0.1"),
        smtp_port=int(env.get("MAPLEROUTE_SMTP_PORT", "1025")),
        smtp_starttls=env.get("MAPLEROUTE_SMTP_STARTTLS", "false").lower() == "true",
        smtp_username=env.get("MAPLEROUTE_SMTP_USERNAME") or None,
        smtp_password=SecretValue(v) if (v := env.get("MAPLEROUTE_SMTP_PASSWORD")) else None,
        mail_from=env.get("MAPLEROUTE_MAIL_FROM", "MapleRoute <no-reply@mapleroute.localhost>"),
        s3_endpoint_url=env.get("MAPLEROUTE_S3_ENDPOINT_URL") or None,
        s3_region=env.get("MAPLEROUTE_S3_REGION", "ca-central-1"),
        s3_bucket=env.get("MAPLEROUTE_S3_BUCKET", "mapleroute-dev"),
        s3_access_key_id=env.get("MAPLEROUTE_S3_ACCESS_KEY_ID") or None,
        s3_secret_access_key=SecretValue(v) if (v := env.get("MAPLEROUTE_S3_SECRET_ACCESS_KEY")) else None,
    )
    if not s.identity_providers or not s.identity_providers <= ALLOWED_IDENTITY_PROVIDERS:
        raise RuntimeError("identity providers must be a non-empty subset of {'local'}; OIDC is not built")
    if s.environment != "local" and (s.s3_endpoint_url is not None or s.s3_region != "ca-central-1"):
        # MH-11: outside local development, stored files live in ca-central-1 only.
        raise RuntimeError("object storage outside local development must be S3 in ca-central-1")
    if s.provider_mode not in ALLOWED_PROVIDER_MODES:
        raise RuntimeError(f"provider mode {s.provider_mode!r} is not implemented; only 'fake' exists")
    return s

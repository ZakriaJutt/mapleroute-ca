"""Time-based one-time passwords (RFC 6238: HMAC-SHA1, 6 digits, 30-second step) for the local
identity provider (B2). Standard library only.

Each code is accepted once: the caller stores the last accepted step and passes it back, and a
step at or before it is refused (ASVS 6.5.1). The server clock is the time source, never the
client (6.5.8). Seeds are 160 random bits from ``secrets`` (6.5.3).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import urllib.parse
from datetime import datetime

STEP_S = 30
DIGITS = 6
# One step either side for clock drift between the authenticator and the server.
DRIFT_STEPS = 1


def new_seed() -> bytes:
    return secrets.token_bytes(20)


def seed_base32(seed: bytes) -> str:
    return base64.b32encode(seed).decode("ascii").rstrip("=")


def provisioning_uri(seed: bytes, account: str, issuer: str = "MapleRoute") -> str:
    label = urllib.parse.quote(f"{issuer}:{account}")
    query = urllib.parse.urlencode({"secret": seed_base32(seed), "issuer": issuer, "digits": DIGITS,
                                    "period": STEP_S, "algorithm": "SHA1"})
    return f"otpauth://totp/{label}?{query}"


def step_of(at: datetime) -> int:
    return int(at.timestamp()) // STEP_S


def code_at(seed: bytes, step: int) -> str:
    digest = hmac.new(seed, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(value).zfill(DIGITS)


def verify(seed: bytes, code: str, at: datetime, last_step: int | None) -> int | None:
    """Return the matched step if ``code`` is valid at ``at`` and newer than ``last_step``; else None."""
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = step_of(at)
    matched: int | None = None
    for step in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        # Compare every candidate so timing does not reveal which step matched.
        if hmac.compare_digest(code_at(seed, step), code) and matched is None:
            matched = step
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched

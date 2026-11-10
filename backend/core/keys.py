"""Project API keys: 256-bit random token, stored as SHA-256; shown once (T-3.1.2, MH-05)."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass

KEY_PREFIX = "mr_"
_KEY_RE = re.compile(r"^mr_[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True)
class NewKey:
    plaintext: str  # returned once to the creator, never stored or logged
    key_hash: bytes
    prefix: str
    last_four: str


def generate() -> NewKey:
    token = KEY_PREFIX + secrets.token_urlsafe(32)
    return NewKey(token, hash_key(token), token[:7], token[-4:])


def well_formed(token: str) -> bool:
    return bool(_KEY_RE.match(token))


def hash_key(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()

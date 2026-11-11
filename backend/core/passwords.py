"""Password policy and hashing for the local identity provider (B2).

Argon2id with the library's RFC 9106 low-memory profile. Length 12 to 128, any characters, no
composition rules, verified exactly as typed (ASVS 6.2.1, 6.2.5, 6.2.8, 6.2.9). A short built-in
list of common and context words is refused; the 3,000-entry list of 6.2.4 and a breached-password
check (6.2.12) are not built.
"""

from __future__ import annotations

from argon2 import PasswordHasher, profiles
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from core.config import PASSWORD_MAX, PASSWORD_MIN
from core.secretvalue import SecretValue

_HASHER = PasswordHasher.from_parameters(profiles.RFC_9106_LOW_MEMORY)
# Context-specific words (6.1.2, 6.2.11): a password made only of these, repeated, is refused.
_BLOCKED = frozenset({
    "password", "passw0rd", "123456789012", "qwertyuiopas", "mapleroute", "maple", "route", "canada",
    "letmein", "welcome", "admin", "changeme", "iloveyou", "monkey", "dragon", "football", "baseball",
})


class PasswordRejected(ValueError):
    pass


def check_policy(password: SecretValue, email: str) -> None:
    value = password.reveal()
    if not PASSWORD_MIN <= len(value) <= PASSWORD_MAX:
        raise PasswordRejected(f"password must be {PASSWORD_MIN} to {PASSWORD_MAX} characters")
    lowered = value.lower()
    local_part = email.split("@", 1)[0].lower()
    if lowered in _BLOCKED or lowered == email.lower() or (len(local_part) >= 4 and local_part in lowered
                                                          and len(lowered) - len(local_part) < 6):
        raise PasswordRejected("password is too easy to guess")
    for word in _BLOCKED:
        if lowered.replace(word, "").strip("0123456789!@#$%^&*()-_=+. ") == "":
            raise PasswordRejected("password is too easy to guess")


def hash_password(password: SecretValue) -> str:
    return _HASHER.hash(password.reveal())


def verify_password(stored_hash: str, password: SecretValue) -> bool:
    try:
        return _HASHER.verify(stored_hash, password.reveal())
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# A fixed hash, so an unknown email costs the same verification time as a known one (6.3.8).
DUMMY_HASH = _HASHER.hash("not-a-real-password-placeholder")

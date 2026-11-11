"""Local identity provider: password plus TOTP authenticator code (B2, T-4.1.1).

Stands in for the Microsoft and Google OIDC providers of TRD.md AD-13, which are deferred because
they need registered applications. It produces the same ``core.identity.Identity`` an OIDC callback
would: (idp ``local``, random subject), the email verified at enrolment, ``amr`` ``pwd`` + ``otp``.

Email is not an authentication factor (ASVS 6.3.6): the emailed enrolment link only proves the
address before a credential exists. An address that already has a credential gets a notice, not a
link; there is no email recovery or reset (a lost authenticator needs a new enrolment by the
operator, recorded as not built). Responses never reveal whether an address is enrolled (6.3.8).
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from core import passwords, totp
from core.config import ENROL_LINK_TTL, LOCKOUT_PERIOD, LOCKOUT_THRESHOLD
from core.crypto import KeyService, decrypt_with_context, encrypt_with_context
from core.identity import Identity, token_hash
from core.mail import Mail, Mailer
from core.models import EmailChallenge, LocalCredential, UserAccount
from core.secretvalue import SecretValue

IDP = "local"
AMR = ("pwd", "otp")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,189}\.[A-Za-z]{2,63}$")


class LinkInvalid(Exception):
    """Unknown, expired or already used link (one message for all three)."""


@dataclass(frozen=True)
class Enrolled:
    user_id: uuid.UUID
    totp_seed: SecretValue  # base32, shown once to the user for their authenticator app
    provisioning_uri: SecretValue


def normalise_email(email: object) -> str | None:
    if not isinstance(email, str):
        return None
    value = email.strip().lower()
    return value if len(value) <= 254 and _EMAIL.match(value) else None


def _seed_context(user_id: uuid.UUID) -> dict[str, str]:
    return {"user_id": str(user_id), "purpose": "totp_seed"}


def request_enrolment(s: Session, mailer: Mailer, email: str, now: datetime, base_url: str) -> None:
    """Send an enrolment link, or a notice if the address is already enrolled. Same outcome to the caller."""
    exists = s.execute(select(LocalCredential.user_id)
                       .where(LocalCredential.email_normalised == email)).scalar_one_or_none()
    if exists is not None:
        mailer.send(Mail(email, "MapleRoute sign-in", SecretValue(
            "Someone asked to enrol this address with MapleRoute. It already has a sign-in, so nothing changed.\n"
            "MapleRoute has no email reset. If you did not ask, you can ignore this message.\n"), "enrol_exists"))
        return
    token = secrets.token_urlsafe(32)
    s.execute(insert(EmailChallenge).values(id=uuid.uuid4(), purpose="enrol", email_normalised=email,
                                            token_hash=token_hash(token), expires_at=now + ENROL_LINK_TTL))
    minutes = int(ENROL_LINK_TTL.total_seconds() // 60)
    mailer.send(Mail(email, "Finish setting up your MapleRoute sign-in", SecretValue(
        f"Open this link within {minutes} minutes to set a password and an authenticator app:\n\n"
        f"{base_url.rstrip('/')}/enrol#token={token}\n\n"
        "The link works once. If you did not ask for it, ignore this message.\n"), "enrol"))


def complete_enrolment(s: Session, ks: KeyService, token: str, display_name: str, password: SecretValue,
                       now: datetime) -> Enrolled:
    """Use the link once, create the identity and its factors. Raises LinkInvalid or PasswordRejected."""
    try:
        th = token_hash(token)
    except UnicodeEncodeError:
        raise LinkInvalid() from None
    challenge = s.execute(select(EmailChallenge).where(
        EmailChallenge.token_hash == th, EmailChallenge.purpose == "enrol")).scalar_one_or_none()
    if challenge is None or challenge.used_at is not None or challenge.expires_at <= now:
        raise LinkInvalid()
    passwords.check_policy(password, challenge.email_normalised)  # before use, so a weak password can retry
    used = s.execute(update(EmailChallenge).where(EmailChallenge.id == challenge.id, EmailChallenge.used_at.is_(None))
                     .values(used_at=now)).rowcount  # type: ignore[attr-defined]
    taken = s.execute(select(LocalCredential.user_id).where(
        LocalCredential.email_normalised == challenge.email_normalised)).scalar_one_or_none()
    if not used or taken is not None:
        raise LinkInvalid()
    user_id = uuid.uuid4()
    s.execute(insert(UserAccount).values(id=user_id, idp=IDP, idp_subject=uuid.uuid4().hex,
                                         email=challenge.email_normalised, display_name=display_name[:200]))
    seed = totp.new_seed()
    env = encrypt_with_context(ks, _seed_context(user_id), seed)
    s.execute(insert(LocalCredential).values(
        user_id=user_id, email_normalised=challenge.email_normalised, password_hash=passwords.hash_password(password),
        totp_ciphertext=env.ciphertext, totp_wrapped_key=env.wrapped_data_key, totp_kms_key_arn=env.kms_key_arn))
    return Enrolled(user_id, SecretValue(totp.seed_base32(seed)),
                    SecretValue(totp.provisioning_uri(seed, challenge.email_normalised)))


def _check(s: Session, ks: KeyService, cred: LocalCredential | None, password: SecretValue, code: str,
           now: datetime) -> bool:
    """Both factors, lockout and code replay. Updates counters; the caller commits even on failure."""
    if cred is None:
        passwords.verify_password(passwords.DUMMY_HASH, password)  # same work for an unknown address
        return False
    if cred.locked_until is not None and cred.locked_until > now:
        # Same Argon2 work as the other refusals, so a locked address is not told apart by timing (B2-S03).
        passwords.verify_password(cred.password_hash, password)
        return False
    password_ok = passwords.verify_password(cred.password_hash, password)
    seed = decrypt_with_context(ks, _seed_context(cred.user_id), cred.totp_ciphertext, cred.totp_wrapped_key)
    step = totp.verify(seed, code, now, cred.totp_last_step)
    if not password_ok or step is None:
        failed = cred.failed_count + 1
        locked = failed >= LOCKOUT_THRESHOLD
        s.execute(update(LocalCredential).where(LocalCredential.user_id == cred.user_id).values(
            failed_count=0 if locked else failed, locked_until=now + LOCKOUT_PERIOD if locked else cred.locked_until))
        return False
    s.execute(update(LocalCredential).where(LocalCredential.user_id == cred.user_id).values(
        failed_count=0, locked_until=None, totp_last_step=step,
        totp_confirmed_at=cred.totp_confirmed_at or now))
    return True


def _identity(s: Session, user_id: uuid.UUID, now: datetime) -> Identity:
    u = s.execute(select(UserAccount.idp_subject, UserAccount.email, UserAccount.display_name)
                  .where(UserAccount.id == user_id)).one()
    return Identity(IDP, u.idp_subject, u.email, u.display_name, AMR, now)


def authenticate(s: Session, ks: KeyService, email: str, password: SecretValue, code: str,
                 now: datetime) -> Identity | None:
    cred = s.execute(select(LocalCredential).where(LocalCredential.email_normalised == email)
                     .with_for_update()).scalar_one_or_none()
    if not _check(s, ks, cred, password, code, now) or cred is None:
        return None
    return _identity(s, cred.user_id, now)


def reauthenticate(s: Session, ks: KeyService, user_id: uuid.UUID, password: SecretValue, code: str,
                   now: datetime) -> Identity | None:
    cred = s.execute(select(LocalCredential).where(LocalCredential.user_id == user_id)
                     .with_for_update()).scalar_one_or_none()
    if cred is None or not _check(s, ks, cred, password, code, now):
        return None
    return _identity(s, user_id, now)

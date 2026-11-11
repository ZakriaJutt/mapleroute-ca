"""Outbound mail through one SMTP interface (B2). Local: Mailpit at 127.0.0.1:1025, no
authentication. Production: a provider's SMTP host with STARTTLS and credentials, chosen by
settings only (core.config).

Message bodies carry one-time links, so they are never logged; only the purpose is.
"""

from __future__ import annotations

import smtplib
import ssl
import threading
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from core.config import Settings
from core.logging import log_event
from core.secretvalue import SecretValue


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: SecretValue  # holds one-time links; never printed
    purpose: str  # loggable: enrol, enrol_exists, invitation


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...

    def ping(self) -> bool: ...


class MailUnavailable(Exception):
    pass


class SmtpMailer:
    def __init__(self, host: str, port: int, sender: str, starttls: bool = False,
                 username: str | None = None, password: SecretValue | None = None, timeout_s: float = 5) -> None:
        self.host, self.port, self.sender = host, port, sender
        self.starttls, self.username, self._password, self.timeout_s = starttls, username, password, timeout_s

    @classmethod
    def from_settings(cls, cfg: Settings) -> SmtpMailer:
        return cls(cfg.smtp_host, cfg.smtp_port, cfg.mail_from, cfg.smtp_starttls, cfg.smtp_username,
                   cfg.smtp_password)

    def _connect(self) -> smtplib.SMTP:
        conn = smtplib.SMTP(self.host, self.port, timeout=self.timeout_s)
        if self.starttls:
            conn.starttls(context=ssl.create_default_context())
        if self.username and self._password is not None:
            conn.login(self.username, self._password.reveal())
        return conn

    def send(self, mail: Mail) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, mail.to, mail.subject
        msg.set_content(mail.body.reveal())
        try:
            with self._connect() as conn:
                conn.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            # The exception text can echo the message; only its class is logged.
            log_event("mail_failed", reason=mail.purpose, error_class=type(exc).__name__)
            raise MailUnavailable(mail.purpose) from None
        log_event("mail_sent", reason=mail.purpose)

    def ping(self) -> bool:
        try:
            with self._connect() as conn:
                return conn.noop()[0] == 250
        except (OSError, smtplib.SMTPException):
            return False


@dataclass
class MemoryMailer:
    """Fake for unit tests and fully offline runs."""

    sent: list[Mail] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, mail: Mail) -> None:
        with self._lock:
            self.sent.append(mail)

    def ping(self) -> bool:
        return True

"""Mail adapter: off (default) | mock (records an outbox, for tests) | smtp (skeleton, env-configured)."""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

log = logging.getLogger("ff_gateway")


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    enabled: bool

    async def send(self, mail: Mail) -> None: ...


class NullMailer:
    """Default: sends nothing. ``enabled`` False means callers skip issuing tokens at all."""

    enabled = False

    async def send(self, mail: Mail) -> None:
        return None


class MockMailer:
    enabled = True

    def __init__(self) -> None:
        self.outbox: list[Mail] = []

    async def send(self, mail: Mail) -> None:
        self.outbox.append(mail)


class SmtpMailer:
    """Minimal SMTP sender (stdlib, run in a thread). Credentials come from settings/env only."""

    enabled = True

    def __init__(self, host: str, port: int, user: str | None, password: str | None,
                 sender: str, starttls: bool = True) -> None:  # fmt: skip
        self._host, self._port, self._user, self._password = host, port, user, password
        self._from, self._starttls = sender, starttls

    def _send_blocking(self, mail: Mail) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self._from, mail.to, mail.subject
        msg.set_content(mail.body)
        with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
            if self._starttls:
                smtp.starttls()
            if self._user:
                smtp.login(self._user, self._password or "")
            smtp.send_message(msg)

    async def send(self, mail: Mail) -> None:
        try:
            await asyncio.to_thread(self._send_blocking, mail)
        except Exception as e:  # never break the request because mail failed; never log the body (has the token)
            log.warning("smtp send failed (%s)", type(e).__name__)


def build_mailer(settings) -> Mailer:
    backend = (settings.mail_backend or "off").lower()
    if backend == "mock":
        return MockMailer()
    if backend == "smtp":
        if not settings.smtp_host:
            log.warning("FF_GATEWAY_MAIL_BACKEND=smtp but FF_GATEWAY_SMTP_HOST is empty; mail is off")
            return NullMailer()
        return SmtpMailer(settings.smtp_host, settings.smtp_port, settings.smtp_user,
                          settings.smtp_password, settings.mail_from, settings.smtp_starttls)  # fmt: skip
    return NullMailer()

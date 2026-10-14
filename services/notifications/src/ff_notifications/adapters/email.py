"""Email providers for the optional daily digest: ``MockEmail`` and an SMTP skeleton (off)."""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmailResult:
    sent: bool
    reason: str | None = None
    retryable: bool = False


class EmailProvider(Protocol):
    async def send(self, to: str, subject: str, body: str) -> EmailResult: ...


@dataclass(slots=True)
class MockEmail:
    sent: list[dict] = field(default_factory=list)
    fail_times: int = 0  # simulate transient failures

    async def send(self, to: str, subject: str, body: str) -> EmailResult:
        if self.fail_times > 0:
            self.fail_times -= 1
            return EmailResult(False, "mock_failure", retryable=True)
        self.sent.append({"to": to, "subject": subject, "body": body})
        return EmailResult(True)


class SmtpEmail:
    """Skeleton SMTP sender, configured from env (host/port/user/password/from). UNVERIFIED."""

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
    ) -> None:
        self.host, self.port, self.sender = host, port, sender
        self.username, self.password, self.starttls = username, password, starttls

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> EmailResult:
        try:
            await asyncio.to_thread(self._send_sync, to, subject, body)
        except smtplib.SMTPRecipientsRefused:
            return EmailResult(False, "recipient_refused")
        except (smtplib.SMTPException, OSError) as exc:
            return EmailResult(False, f"smtp:{type(exc).__name__}", retryable=True)
        return EmailResult(True)

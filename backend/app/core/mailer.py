"""Outgoing email — one function every module uses, so there is exactly one
place that knows about SMTP.

Delivery is real SMTP when SMTP_HOST is configured; otherwise each message is
saved as an .eml file under <media_root>/outbox (open it in any mail client to
see exactly what would have been sent). Either way the caller gets a
MailResult saying which happened, and can tell the user honestly.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from pathlib import Path

from app.core.config import settings


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime: str = "application/pdf"


@dataclass
class MailResult:
    delivered: bool  # True = handed to an SMTP server
    backend: str  # "smtp" | "outbox"
    detail: str = ""


@dataclass
class Mail:
    to: list[str]
    subject: str
    html: str
    text: str = ""
    cc: list[str] = field(default_factory=list)
    reply_to: str = ""
    from_name: str = ""
    attachments: list[Attachment] = field(default_factory=list)


def smtp_configured() -> bool:
    return bool(settings.smtp_host)


def _build(mail: Mail) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = mail.subject
    message["From"] = formataddr((mail.from_name or settings.mail_from_name, settings.mail_from))
    message["To"] = ", ".join(mail.to)
    if mail.cc:
        message["Cc"] = ", ".join(mail.cc)
    if mail.reply_to:
        message["Reply-To"] = mail.reply_to
    message["Message-ID"] = make_msgid()
    message.set_content(mail.text or "This message is best viewed in an HTML-capable mail client.")
    message.add_alternative(mail.html, subtype="html")
    for attachment in mail.attachments:
        maintype, _, subtype = attachment.mime.partition("/")
        message.add_attachment(attachment.content, maintype=maintype, subtype=subtype or "octet-stream", filename=attachment.filename)
    return message


def _send_smtp(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


def _save_outbox(message: EmailMessage) -> str:
    outbox = Path(settings.media_root) / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = outbox / f"{stamp}.eml"
    path.write_bytes(bytes(message))
    return str(path)


async def send(mail: Mail) -> MailResult:
    message = _build(mail)
    if smtp_configured():
        # smtplib blocks; keep the event loop free while it talks to the server.
        await asyncio.to_thread(_send_smtp, message)
        return MailResult(delivered=True, backend="smtp")
    path = await asyncio.to_thread(_save_outbox, message)
    return MailResult(delivered=False, backend="outbox", detail=path)


def layout(*, heading: str, body_html: str, button: tuple[str, str] | None = None, brand: str = "#1a7a8c", sender: str = "") -> str:
    """Simple, client-safe HTML (tables + inline styles — the only CSS every
    mail client honours)."""
    cta = ""
    if button:
        label, url = button
        cta = (
            f'<p style="margin:28px 0"><a href="{escape(url, quote=True)}" '
            f'style="background:{brand};color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:8px;'
            f'font-weight:600;display:inline-block">{escape(label)}</a></p>'
            f'<p style="font-size:12px;color:#64748b">Or paste this link into your browser:<br>'
            f'<span style="word-break:break-all">{escape(url)}</span></p>'
        )
    return f"""<!doctype html><html><body style="margin:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 12px"><tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden">
<tr><td style="height:6px;background:{brand}"></td></tr>
<tr><td style="padding:32px">
<h1 style="margin:0 0 16px;font-size:20px">{escape(heading)}</h1>
<div style="font-size:14px;line-height:1.6;color:#334155">{body_html}</div>
{cta}
</td></tr>
<tr><td style="padding:16px 32px;background:#f8fafc;font-size:12px;color:#94a3b8">{escape(sender or settings.mail_from_name)}</td></tr>
</table></td></tr></table></body></html>"""

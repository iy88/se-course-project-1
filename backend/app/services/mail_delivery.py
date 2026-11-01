"""Deliver authentication codes by SMTP or to a private acceptance mailbox."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import Settings
from app.core.private_files import exclusive_lock, require_private


def deliver_code(settings: Settings, purpose: str, email: str, code: str) -> None:
    if settings.mail_backend == 'capture':
        _capture(settings, purpose, email, code)
        return
    message = EmailMessage()
    message['From'] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
    message['To'] = email
    message['Subject'] = '邮箱验证码'
    message.set_content(f'您的验证码是：{code}\n有效期为 {settings.verification_code_ttl_seconds} 秒。\n如非本人操作，请忽略此邮件。')
    context = ssl.create_default_context()
    if settings.smtp_security == 'ssl':
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds, context=context) as smtp:
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)


def _capture(settings: Settings, purpose: str, email: str, code: str) -> None:
    path = settings.mail_capture_path
    assert path is not None
    # Refuse symlink substitution and validate permissions again at the point of use.
    require_private(path.parent, directory=True)
    if path.is_symlink():
        raise OSError('invalid private mailbox')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        require_private(path, fd=fd)
        record = (json.dumps({'purpose': purpose, 'email': email.strip().lower(), 'code': code}, ensure_ascii=False) + '\n').encode('utf-8')
        with exclusive_lock(fd), os.fdopen(fd, 'ab', closefd=False) as stream:
            stream.write(record)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)

"""Deliver authentication codes by SMTP or to a private acceptance mailbox."""

from __future__ import annotations

import fcntl
import json
import os
import smtplib
import ssl
import stat
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import Settings


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
    parent = path.parent.stat()
    if path.parent.is_symlink() or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
        raise OSError('invalid private mailbox directory')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise OSError('invalid private mailbox')
        record = (json.dumps({'purpose': purpose, 'email': email.strip().lower(), 'code': code}, ensure_ascii=False) + '\n').encode('utf-8')
        fcntl.flock(fd, fcntl.LOCK_EX)
        with os.fdopen(fd, 'ab', closefd=False) as stream:
            stream.write(record)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)

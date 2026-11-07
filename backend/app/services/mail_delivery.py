"""Deliver authentication codes by SMTP or to a private acceptance mailbox."""

from __future__ import annotations

import json
import os
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import Settings
from app.core.private_files import exclusive_lock, require_private



class _NoIPv4AddressError(OSError):
    """The SMTP host has no usable IPv4 address (fall back to system-default resolution)."""


def _connect_ipv4(host: str, port: int, timeout: float) -> socket.socket:
    """Resolve and connect to the SMTP host over IPv4 only.

    When IPv6 egress is unreachable on some servers, the stdlib waits on each address
    in turn until the socket times out (smtp.163.com has 2 AAAA records, potentially
    accumulating 2×SMTP_TIMEOUT), so a send request far exceeds the frontend timeout
    even though the mail eventually arrives. SMTP sending does not need IPv6, so use
    IPv4 explicitly here; fall back to stdlib default behavior only when the host has
    no IPv4 record.
    """
    addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    if not addresses:
        raise _NoIPv4AddressError(f'no IPv4 address for {host}')
    last_error: OSError | None = None
    for family, socktype, proto, _canonname, sockaddr in addresses:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or _NoIPv4AddressError(f'no IPv4 address for {host}')


class _IPv4SMTP(smtplib.SMTP):
    """STARTTLS mode: force IPv4 during connection."""

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        if self.debuglevel > 0:
            self._print_debug('connect:', (host, port))
        return _connect_ipv4(host, port, timeout)


class _IPv4SMTP_SSL(smtplib.SMTP_SSL):
    """SSL mode: force IPv4 during connection while TLS still validates the certificate against the original hostname."""

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        if self.debuglevel > 0:
            self._print_debug('connect:', (host, port))
        raw_socket = _connect_ipv4(host, port, timeout)
        return self.context.wrap_socket(raw_socket, server_hostname=host)


def _open_smtp_ssl(settings: Settings, context: ssl.SSLContext) -> smtplib.SMTP_SSL:
    try:
        return _IPv4SMTP_SSL(
            settings.smtp_host, settings.smtp_port,
            timeout=settings.smtp_timeout_seconds, context=context,
        )
    except _NoIPv4AddressError:
        return smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port,
            timeout=settings.smtp_timeout_seconds, context=context,
        )


def _open_smtp_starttls(settings: Settings) -> smtplib.SMTP:
    try:
        return _IPv4SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
    except _NoIPv4AddressError:
        return smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)


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
        with _open_smtp_ssl(settings, context) as smtp:
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    else:
        with _open_smtp_starttls(settings) as smtp:
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

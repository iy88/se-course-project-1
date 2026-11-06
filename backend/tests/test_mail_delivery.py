"""SMTP 发信连接策略：优先 IPv4，避免 IPv6 不可达时逐地址等待超时。

背景：smtp.163.com 有 2 个 A 与 2 个 AAAA 记录。服务器 IPv6 出站不可达时，
stdlib 会按解析顺序对两个 IPv6 地址各等待一次 SMTP_TIMEOUT（默认 10s），
总耗时可达 20s 以上；此时邮件最终仍经 IPv4 送达，但接口早已超过前端超时。
"""

import socket
import ssl
from types import SimpleNamespace

import pytest

from app.services import mail_delivery as mail


def _settings(**overrides):
    base = dict(
        mail_backend='smtp',
        smtp_host='smtp.example.com',
        smtp_port=465,
        smtp_security='ssl',
        smtp_username='sender@example.com',
        smtp_password='secret',
        smtp_from_email='sender@example.com',
        smtp_from_name='CampusMarket',
        smtp_timeout_seconds=10,
        verification_code_ttl_seconds=600,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_connect_ipv4_only_requests_ipv4_and_skips_failed_addresses(monkeypatch):
    calls = []
    requested_families = []

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        requested_families.append(family)
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('192.0.2.1', port)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('192.0.2.2', port)),
        ]

    class FakeSocket:
        def __init__(self, family, socktype, proto):
            self.family = family
            self.closed = False

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, sockaddr):
            calls.append(sockaddr[0])
            if sockaddr[0] == '192.0.2.1':
                raise OSError('unreachable')

        def close(self):
            self.closed = True

    monkeypatch.setattr(mail.socket, 'getaddrinfo', fake_getaddrinfo)
    monkeypatch.setattr(mail.socket, 'socket', FakeSocket)

    sock = mail._connect_ipv4('smtp.example.com', 465, 10)
    assert requested_families == [socket.AF_INET], '只应请求 IPv4 地址'
    assert calls == ['192.0.2.1', '192.0.2.2']
    assert sock.family == socket.AF_INET


def test_connect_ipv4_raises_when_host_has_no_ipv4(monkeypatch):
    monkeypatch.setattr(mail.socket, 'getaddrinfo', lambda *a, **k: [])
    with pytest.raises(mail._NoIPv4AddressError):
        mail._connect_ipv4('ipv6-only.example.com', 465, 10)


def test_ssl_connect_wraps_ipv4_socket_with_original_hostname(monkeypatch):
    plain = object()
    wrapped = object()
    monkeypatch.setattr(mail, '_connect_ipv4', lambda host, port, timeout: plain)

    class FakeContext:
        def wrap_socket(self, sock, server_hostname=None):
            assert sock is plain
            assert server_hostname == 'smtp.example.com', 'TLS 必须按原主机名校验证书'
            return wrapped

    smtp = mail._IPv4SMTP_SSL.__new__(mail._IPv4SMTP_SSL)
    smtp.context = FakeContext()
    smtp.debuglevel = 0
    assert smtp._get_socket('smtp.example.com', 465, 10) is wrapped


def test_ssl_connector_falls_back_when_no_ipv4(monkeypatch):
    fallback_calls = []

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout=None, context=None):
            fallback_calls.append((host, port))

    def no_ipv4(*args, **kwargs):
        raise mail._NoIPv4AddressError('no ipv4')

    monkeypatch.setattr(mail, '_IPv4SMTP_SSL', no_ipv4)
    monkeypatch.setattr(mail.smtplib, 'SMTP_SSL', FakeSMTPSSL)
    smtp = mail._open_smtp_ssl(_settings(), ssl.create_default_context())
    assert isinstance(smtp, FakeSMTPSSL)
    assert fallback_calls == [('smtp.example.com', 465)]


def test_deliver_code_ssl_uses_ipv4_connector_and_sends_message(monkeypatch):
    captured = {}

    class FakeSMTP:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, username, password):
            captured['login'] = (username, password)

        def send_message(self, message):
            captured['to'] = message['To']
            captured['subject'] = message['Subject']
            captured['body'] = message.get_content()

    def fake_open(settings, context):
        captured['opened'] = (settings.smtp_host, settings.smtp_port)
        return FakeSMTP()

    monkeypatch.setattr(mail, '_open_smtp_ssl', fake_open)
    mail.deliver_code(_settings(), 'register', 'user@example.com', '123456')

    assert captured['opened'] == ('smtp.example.com', 465)
    assert captured['login'] == ('sender@example.com', 'secret')
    assert captured['to'] == 'user@example.com'
    assert captured['subject'] == '邮箱验证码'
    assert '123456' in captured['body']


def test_deliver_code_starttls_uses_ipv4_connector(monkeypatch):
    captured = {'starttls': False}

    class FakeSMTP:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self, context=None):
            captured['starttls'] = True

        def login(self, username, password):
            pass

        def send_message(self, message):
            captured['sent'] = True

    def fake_open(settings):
        captured['opened'] = settings.smtp_security
        return FakeSMTP()

    monkeypatch.setattr(mail, '_open_smtp_starttls', fake_open)
    mail.deliver_code(_settings(smtp_security='starttls'), 'register', 'user@example.com', '123456')

    assert captured['opened'] == 'starttls'
    assert captured['starttls'] is True
    assert captured['sent'] is True

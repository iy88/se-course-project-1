"""WebSocket 接入：真实路由握手、JWT 严格校验、在线注册与断开清理。"""

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import quote

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.api.v1.auth import router as auth_router
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import Base, get_db
from app.models import User
from app.ws.endpoint import ws_endpoint
from app.ws.manager import manager


def _make_token(sub, *, secret: str | None = None, expired: bool = False) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "role": "user",
        "iat": now,
        "exp": now + timedelta(days=-1 if expired else 1),
    }
    if sub is not None:
        payload["sub"] = sub
    return pyjwt.encode(
        payload,
        secret or settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _ws_url(token: str | None = None) -> str:
    if token is None:
        return "/ws"
    return f"/ws?token={quote(token, safe='')}"


def _expect_rejected(client: TestClient, token: str | None, expected_code: int = 4401) -> int:
    """连接真实 /ws 路由并读取关闭码；拒绝必须发生在注册在线连接之前。"""
    code = None
    try:
        with client.websocket_connect(_ws_url(token)) as ws:
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                code = exc.code
    except WebSocketDisconnect as exc:
        code = exc.code
    assert code == expected_code
    return code


def _wait_offline(user_id: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not manager.is_online(user_id):
            return
        time.sleep(0.01)
    raise AssertionError(f"用户 {user_id} 的在线连接未清理")


@pytest.fixture
def ws_env(tmp_path):
    """临时 SQLite + 真实 websocket/auth 路由，不启动 app.main lifespan、不接触原库。

    连接池刻意设为 pool_size=1、max_overflow=0，用真实 HTTP 读库验证 WS 不会长期占用连接。
    """
    db_path = tmp_path / "ws-test.db"
    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    with Session(sync_engine) as session:
        normal = User(
            email="ws-normal@test.edu",
            display_name="WS 正常用户",
            password_hash=hash_password("secret123"),
            role="user",
            status="normal",
        )
        banned = User(
            email="ws-banned@test.edu",
            display_name="WS 封禁用户",
            password_hash=hash_password("secret123"),
            role="user",
            status="banned",
        )
        session.add_all([normal, banned])
        session.commit()
        normal_id, banned_id = normal.id, banned.id
    sync_engine.dispose()

    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.25,
    )
    SessionMaker = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with SessionMaker() as session:
            yield session

    test_app = FastAPI()
    # 与 app.main 的实际装配一致：同一 ws_endpoint 注册到 /ws 路由。
    test_app.add_api_websocket_route("/ws", ws_endpoint)
    test_app.include_router(auth_router, prefix="/api/v1")
    test_app.dependency_overrides[get_db] = override_get_db

    with TestClient(test_app) as client:
        try:
            yield SimpleNamespace(
                client=client,
                normal_id=normal_id,
                banned_id=banned_id,
                db_path=db_path,
                async_engine=async_engine,
            )
        finally:
            # 在 TestClient 自身的事件循环中释放连接，避免跨 loop 的清理异常。
            assert client.portal is not None
            client.portal.call(async_engine.dispose)

    test_app.dependency_overrides.clear()
    manager._connections.clear()


def test_valid_token_connects_pings_and_disconnects(ws_env):
    user_id = ws_env.normal_id
    token = create_access_token(user_id, "user")
    with ws_env.client.websocket_connect(_ws_url(token)) as ws:
        assert manager.is_online(user_id)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    _wait_offline(user_id)


def test_open_ws_releases_db_connection_for_real_http_read(ws_env):
    """WS 与 HTTP 共用 pool_size=1：WS 保持打开时 /auth/me 仍须真实读库成功。

    这不是断言 db.close 被调用；未在鉴权后归还连接时，HTTP 取不到唯一连接，
    会在 pool_timeout 后失败。
    """
    user_id = ws_env.normal_id
    token = create_access_token(user_id, "user")
    with ws_env.client.websocket_connect(_ws_url(token)) as ws:
        assert manager.is_online(user_id)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        # 直接观察真实连接池：WS 收循环期间不应有连接被占用。
        assert ws_env.async_engine.pool.checkedout() == 0

        resp = ws_env.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == user_id
        assert body["email"] == "ws-normal@test.edu"

        # HTTP 完成后 WS 仍存活，可继续收发；说明小连接池可被正常复用。
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    _wait_offline(user_id)


def test_db_query_failure_rejects_1011_and_releases_connection(ws_env):
    """资格查询异常仍以 1011 关闭，且失败路径同样把连接归还池。"""
    token = create_access_token(ws_env.normal_id, "user")
    sync_engine = create_engine(f"sqlite:///{ws_env.db_path}")
    with sync_engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE users")
    sync_engine.dispose()

    _expect_rejected(ws_env.client, token, expected_code=1011)
    assert not manager.is_online(ws_env.normal_id)
    # 直接检查真实连接池状态，避免只依赖错误码而漏掉会话仍被占用。
    assert ws_env.async_engine.pool.checkedout() == 0


def test_anonymous_connection_is_rejected_without_registration(ws_env):
    _expect_rejected(ws_env.client, None)
    assert not manager.is_online(ws_env.normal_id)


def test_banned_user_can_open_read_connection(ws_env):
    """封禁只限制写操作；本人通知/处置沟通的 WS 读取连接仍可建立。"""
    user_id = ws_env.banned_id
    token = create_access_token(user_id, "user")
    with ws_env.client.websocket_connect(_ws_url(token)) as ws:
        assert manager.is_online(user_id)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    _wait_offline(user_id)


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "wrong_signature",
        "missing_sub",
        "numeric_sub",
        "non_numeric_sub",
        "negative_sub",
        "zero_sub",
        "fraction_sub",
        "space_sub",
        "overflow_sub",
        "very_long_numeric_sub",
        "unknown_user",
        "garbage",
    ],
)
def test_invalid_identity_is_rejected_without_registration(ws_env, case):
    user_id = ws_env.normal_id
    if case == "expired":
        token = _make_token(str(user_id), expired=True)
    elif case == "wrong_signature":
        token = _make_token(str(user_id), secret="not-the-real-secret")
    elif case == "missing_sub":
        token = _make_token(None)
    elif case == "numeric_sub":
        token = _make_token(user_id)
    elif case == "non_numeric_sub":
        token = _make_token("not-a-number")
    elif case == "negative_sub":
        token = _make_token("-1")
    elif case == "zero_sub":
        token = _make_token("0")
    elif case == "fraction_sub":
        token = _make_token(f"{user_id}.5")
    elif case == "space_sub":
        token = _make_token(f" {user_id}")
    elif case == "overflow_sub":
        token = _make_token(str(2**63))
    elif case == "very_long_numeric_sub":
        token = _make_token("9" * 5000)
    elif case == "unknown_user":
        token = create_access_token(999_999, "user")
    else:
        token = "definitely-not-a-jwt"

    _expect_rejected(ws_env.client, token)
    assert not manager.is_online(user_id)


def test_only_own_connection_is_registered_and_cleanup_is_per_socket(ws_env):
    """同一用户的两条连接互不顶替；单条断开只移除自身，全部断开后清理用户。"""
    user_id = ws_env.normal_id
    token = create_access_token(user_id, "user")
    with ws_env.client.websocket_connect(_ws_url(token)) as first:
        with ws_env.client.websocket_connect(_ws_url(token)) as second:
            assert manager.is_online(user_id)
            second.send_json({"type": "ping"})
            assert second.receive_json() == {"type": "pong"}
        # first 仍在线，且仍可通信
        first.send_json({"type": "ping"})
        assert first.receive_json() == {"type": "pong"}
    _wait_offline(user_id)

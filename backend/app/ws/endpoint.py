"""WS 入口：token 鉴权接入，客户端保活 ping。"""

import re

from fastapi import WebSocket

from app.api.deps import DbSession
from app.core.security import decode_access_token
from app.models import User
from app.ws.manager import manager

# 与 JWT 签发保持一致：sub 是正整数的十进制字符串，不接受旧式 uid 或其他类型。
_USER_ID_RE = re.compile(r"[1-9][0-9]*")
_AUTH_CLOSE_CODE = 4401
_MAX_USER_ID = 2**63 - 1


async def _reject(websocket: WebSocket, code: int) -> None:
    """先完成握手再以业务关闭码拒绝，避免客户端只能看到 403/1006 而无法停止重试。"""
    try:
        await websocket.accept()
    except Exception:  # pragma: no cover - 客户端可能已断开
        return
    try:
        await websocket.close(code=code)
    except Exception:  # pragma: no cover - 关闭阶段同样可能已断开
        pass


def _parse_user_id(token: str) -> int | None:
    payload = decode_access_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    # 当前签发固定为 str(user_id)；缺失、数字类型、符号、小数及非数字均拒绝。
    if not isinstance(sub, str) or _USER_ID_RE.fullmatch(sub) is None:
        return None
    # 避免超长数字触发 Python 的 int 转换限制或 SQLite BIGINT 溢出。
    if len(sub) > 19:
        return None
    user_id = int(sub)
    if user_id > _MAX_USER_ID:
        return None
    return user_id


async def ws_endpoint(websocket: WebSocket, db: DbSession) -> None:
    token = websocket.query_params.get("token", "")
    user_id = _parse_user_id(token)
    if user_id is None:
        await _reject(websocket, _AUTH_CLOSE_CODE)
        return

    authenticated_user_id: int | None = None
    db_failed = False
    try:
        user = await db.get(User, user_id)
        if user is not None:
            # 只保留纯 int；关闭会话后不再读取可能已过期的 ORM 实例。
            authenticated_user_id = int(user.id)
    except Exception:
        db_failed = True
    finally:
        # 身份校验结束立即归还连接池：WS 长连接不能占用 SQL 连接，
        # 否则 pool_size 较小时会阻塞普通 HTTP 请求。依赖退出时的再次 close 是幂等的。
        await db.close()

    if db_failed:
        # 资格查询失败按服务端错误关闭，不注册在线连接。
        await _reject(websocket, 1011)
        return
    if authenticated_user_id is None:
        await _reject(websocket, _AUTH_CLOSE_CODE)
        return

    # 封禁用户仍可建立只读推送连接，接收本人通知与处置沟通；写权限由 HTTP 接口校验。
    await manager.connect(authenticated_user_id, websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except Exception:
        pass
    finally:
        manager.disconnect(authenticated_user_id, websocket)

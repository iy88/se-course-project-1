"""WS 入口：token 鉴权接入，客户端保活 ping。"""

import jwt as pyjwt

from app.core.config import get_settings
from app.ws.manager import manager


async def ws_endpoint(websocket) -> None:  # noqa: ANN001 - FastAPI WebSocket
    token = websocket.query_params.get("token", "")
    try:
        payload = pyjwt.decode(token, get_settings().jwt_secret, algorithms=[get_settings().jwt_algorithm])
        user_id = int(payload["sub"])
    except pyjwt.PyJWTError:
        await websocket.close(code=4401)
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except Exception:
        pass
    finally:
        manager.disconnect(user_id, websocket)

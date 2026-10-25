"""WebSocket 连接管理器：用户级在线注册与事件推送。"""

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[user_id].add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        self._connections[user_id].discard(ws)
        if not self._connections[user_id]:
            self._connections.pop(user_id, None)

    async def push_to_user(self, user_id: int, payload: dict) -> None:
        """向该用户全部在线连接推送 JSON；离线则跳过（消息已落库）。"""
        for ws in list(self._connections.get(user_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:  # pragma: no cover
                self.disconnect(user_id, ws)

    async def push_to_users(self, user_ids: list[int], payload: dict) -> None:
        for uid in set(user_ids):
            await self.push_to_user(uid, payload)

    def is_online(self, user_id: int) -> bool:
        return bool(self._connections.get(user_id))


manager = ConnectionManager()

"""应用入口：建表、路由装配、超时扫描后台任务。"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.session import Base, engine
from app.ws.endpoint import ws_endpoint
from app.ws.manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    task = asyncio.create_task(_timeout_scan_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _timeout_scan_loop() -> None:
    from app.services.trade_timeout import scan_once

    settings = get_settings()
    while True:
        try:
            await scan_once()
        except Exception:  # pragma: no cover - 扫描异常不中断循环
            pass
        await asyncio.sleep(settings.timeout_scan_interval_seconds)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.v1 import api_router

    app.include_router(api_router, prefix="/api/v1")
    app.add_api_websocket_route("/ws", ws_endpoint)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()

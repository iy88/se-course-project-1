"""应用入口：按配置建表/增量升级、路由装配、超时扫描后台任务。"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.audit_integration import install_audit
from app.core.config import get_settings
from app.db.migrations import upgrade_additive_schema
from app.db.session import Base, engine
from app.ws.endpoint import ws_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_for_runtime()
    # 生产禁止任何自动 DDL；PostgreSQL 结构必须由独立迁移命令建立。
    if not settings.is_production:
        if settings.database_url.startswith("sqlite"):
            async with engine.begin() as conn:
                if settings.db_auto_create:
                    await conn.run_sync(Base.metadata.create_all)
                # D-51：已有 SQLite 库只追加缺失列，不重建、不清空。
                await conn.run_sync(upgrade_additive_schema)
        elif settings.db_auto_create:
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
        with contextlib.suppress(Exception):  # pragma: no cover - 扫描异常不中断循环
            await scan_once()
        await asyncio.sleep(settings.timeout_scan_interval_seconds)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_for_runtime()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    from app.api.v1 import api_router

    app.include_router(api_router, prefix="/api/v1")
    app.add_api_websocket_route("/ws", ws_endpoint)
    # 审计是必需集成：模块缺失/装配失败必须让启动失败，禁止静默跳过。
    install_audit(app)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()

"""Role-aware application assembly and lifecycle.

``combined`` is the compatibility single-process entry: HTTP + WS plus an
in-process official Taskiq ``Receiver``/``SchedulerLoop`` over an InMemoryBroker.
``api`` owns only HTTP, ``ws`` owns only the gateway, and ``jobs`` is the
transitional all-in-one real Taskiq process. New split production uses the native
``worker`` and ``scheduler`` roles through ``app.manage taskiq-worker`` /
``taskiq-scheduler``. No role starts a hand-written consumer/retry loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.audit_integration import install_audit
from app.core.config import get_settings, set_runtime_role
from app.db.migrations import upgrade_additive_schema
from app.db.session import Base, dispose_engine, engine
from app.jobs.runtime import JobsRuntime
from app.kv.base import reset_kv
from app.observability import install_observability, probe_event_loop_lag
from app.realtime.admission import install_admission_handler
from app.realtime.dispatcher import HeartbeatLoop
from app.realtime.gateway import get_gateway
from app.realtime.health import readiness
from app.ws.endpoint import ws_endpoint

logger = logging.getLogger(__name__)


async def _prepare_dev_schema() -> None:
    settings = get_settings()
    if settings.is_production:
        return
    if settings.database_url.startswith("sqlite"):
        async with engine.begin() as conn:
            if settings.db_auto_create:
                await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(upgrade_additive_schema)
    elif settings.db_auto_create:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_for_runtime()
    role = settings.app_role
    tasks: list[asyncio.Task] = []
    jobs: JobsRuntime | None = None
    heartbeat: HeartbeatLoop | None = None
    gateway = None

    if role in {"combined", "api"}:
        await _prepare_dev_schema()

    if role in {"combined", "ws"}:
        gateway = get_gateway()
        await gateway.start()

    tasks.append(asyncio.create_task(probe_event_loop_lag(), name="event-loop-lag"))

    if role == "combined":
        # Compatibility boundary: official Taskiq in-memory receiver/scheduler.
        jobs = JobsRuntime(settings, inline=True)
        await jobs.start()
    elif role == "jobs":
        # Transitional all-in-one jobs process over the real Redis broker.
        jobs = JobsRuntime(settings, inline=False)
        await jobs.start()
    elif role in {"api", "ws"}:
        from app.realtime.heartbeat import instance_name

        heartbeat = HeartbeatLoop(settings, name=instance_name(settings))
        tasks.append(asyncio.create_task(heartbeat.run(), name="heartbeat"))

    try:
        yield
    finally:
        if heartbeat is not None:
            heartbeat.stop()
        if jobs is not None:
            await jobs.stop()
        if gateway is not None:
            await gateway.stop()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(task, timeout=settings.graceful_shutdown_seconds)
        await reset_kv()
        await dispose_engine()


def create_app(role: str | None = None) -> FastAPI:
    if role is not None:
        set_runtime_role(role)
    settings = get_settings()
    settings.validate_for_runtime()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.role = settings.app_role
    app.state.release_id = settings.release_id
    app.state.protocol_version = settings.realtime_protocol_version
    install_observability(app)

    install_admission_handler(app)

    if settings.app_role in {"combined", "api"}:
        from app.api.v1 import api_router

        app.include_router(api_router, prefix="/api/v1")
        # Audit is a required integration; a missing module must fail startup.
        install_audit(app)

        @app.get("/api/health")
        async def health() -> dict:
            payload, ok = await readiness(settings, gateway=get_gateway())
            # Legacy Jenkins check requires body.status == "ok"; keep the
            # detailed readiness verdict under a separate key instead of
            # letting it overwrite this compatibility field.
            payload = dict(payload)
            payload["readiness_status"] = payload.pop("status", "unknown")
            return {"status": "ok" if ok else "not_ready", **payload}

    if settings.app_role in {"combined", "ws"}:
        app.add_api_websocket_route("/ws", ws_endpoint)

    if settings.app_role == "jobs":
        # The transitional jobs role keeps only a loopback health surface.
        pass

    @app.get("/health/live")
    async def live() -> dict:
        return {"status": "ok", "role": settings.app_role, "release_id": settings.release_id}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        payload, ok = await readiness(
            settings,
            gateway=get_gateway() if settings.app_role in {"ws", "combined"} else None,
        )
        return JSONResponse(payload, status_code=200 if ok else 503)

    return app

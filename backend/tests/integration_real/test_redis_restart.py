"""Redis restart/loss: WS must recover from PostgreSQL, not the lost stream."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.realtime.events import emit_events

from .support import create_user, token_for
from .test_cross_process import _connect, _next_event, _start, _stop, _wait, _wait_cli


async def _ping(port: int) -> bool:
    import redis.asyncio as aioredis

    client = aioredis.Redis(host="127.0.0.1", port=port, socket_connect_timeout=0.5)
    try:
        return bool(await client.ping())
    except Exception:  # noqa: BLE001
        return False
    finally:
        await client.aclose()


async def _kill_own_ws_reader(settings) -> None:
    """External Redis: kill only this run's named WS reader and own stream."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1)
    marker = settings.redis_key_prefix + "ws-reader"
    try:
        for entry in await client.client_list():
            name = str(entry.get("name") or "")
            if name.startswith(marker):
                await client.execute_command("CLIENT", "KILL", "ID", entry["id"])
        await client.delete(settings.redis_key_prefix + settings.realtime_stream_name)
    finally:
        await client.aclose()


async def test_redis_restart_or_loss_recovers_ws_from_postgres(tmp_path):
    control_path = os.environ.get("INTEGRATION_REDIS_CONTROL")
    control = json.loads(Path(control_path).read_text(encoding="utf-8")) if control_path else None
    port = int(control["port"]) if control else 0
    env_file = Path(os.environ["INTEGRATION_ENV_FILE"])
    api_port = int(os.environ["INTEGRATION_API_PORT"])
    ws_port = int(os.environ["INTEGRATION_WS_PORT"])
    settings = get_settings()
    user = await create_user(f"redis-restart-{secrets.token_hex(4)}")
    logs = {role: tmp_path / f"{role}.log" for role in ("api", "ws", "worker", "scheduler")}
    processes: list[subprocess.Popen] = []
    sockets: list = []
    worker: subprocess.Popen | None = None
    try:
        processes.append(_start([sys.executable, "-m", "app.manage", "taskiq-scheduler"],
                                logs["scheduler"], str(env_file)))
        worker = _start([sys.executable, "-m", "app.manage", "taskiq-worker"],
                        logs["worker"], str(env_file))
        processes.append(worker)
        processes.append(_start([sys.executable, "-m", "app.manage", "serve-ws"],
                                logs["ws"], str(env_file)))
        processes.append(_start([sys.executable, "-m", "app.manage", "serve-api"],
                                logs["api"], str(env_file)))
        await _wait(f"http://127.0.0.1:{ws_port}/health/ready")
        await _wait(f"http://127.0.0.1:{api_port}/api/health")
        await _wait_cli("scheduler", env_file)
        await _wait_cli("worker", env_file)

        ws, _ = await _connect(token_for(user), api_port, ws_port)
        sockets.append(ws)
        async with get_sessionmaker()() as db, db.begin():
            await emit_events(db, [user.id], event_type="test", payload={"type": "test", "n": 1})
        first = await _next_event(ws)
        assert first["user_seq"] == 1

        # Stop the only worker first: the second event cannot be published to a
        # stream and must still reach the client through PG reconciliation.
        _stop(worker)
        worker = None

        if control is not None:
            # Managed Redis: real process SHUTDOWN without saving, then restart
            # on the same port after the WS fallback delivered the event.
            import redis.asyncio as aioredis

            killer = aioredis.Redis(host="127.0.0.1", port=port, socket_connect_timeout=1)
            try:
                # redis-py shutdown() consumes the expected disconnect.
                await killer.shutdown(nosave=True)
            finally:
                await killer.aclose()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and await _ping(port):
                await asyncio.sleep(0.2)
            assert not await _ping(port)
        else:
            # External dedicated CI Redis cannot be restarted from the job:
            # drop only this run's named WS reader and its own stream, never
            # CLIENT KILL TYPE normal (other projects may share the instance).
            await _kill_own_ws_reader(settings)

        async with get_sessionmaker()() as db, db.begin():
            await emit_events(db, [user.id], event_type="test", payload={"type": "test", "n": 2})
        second = await _next_event(ws)
        assert second["user_seq"] == 2
        assert second["payload"]["n"] == 2

        if control is not None:
            restarted = await asyncio.to_thread(
                subprocess.Popen, control["args"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
            control["pid"] = restarted.pid
            Path(control_path).write_text(json.dumps(control), encoding="utf-8")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not await _ping(port):
                await asyncio.sleep(0.2)
            assert await _ping(port)

        worker = _start([sys.executable, "-m", "app.manage", "taskiq-worker"],
                        logs["worker"], str(env_file))
        processes.append(worker)
        worker_health = await _wait_cli("worker", env_file)
        assert worker_health["checks"]["task_probe"]["status"] == "ok"
    finally:
        for sock in sockets:
            with contextlib.suppress(Exception):
                await sock.close()
        for process in reversed(processes):
            _stop(process)
        for role, path in logs.items():
            if path.exists() and path.stat().st_size:
                tail = path.read_text(errors="replace")[-2000:]
                if "Traceback" in tail or "ERROR" in tail:
                    print(f"--- {role} log tail ---\n{tail}", file=sys.stderr)

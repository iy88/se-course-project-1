"""Cross-process API + two WS gateways + native Taskiq worker/scheduler."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import websockets
from app.models.realtime import RealtimeEvent
from sqlmodel import select

from .support import create_conversation, create_user, session, token_for

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _start(args: list[str], log: Path, env_file: str | None = None,
           role: str | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    if role is not None:
        env["APP_RUNTIME_ROLE"] = role
    if env_file is not None:
        env["APP_ENV_FILE"] = env_file
    handle = log.open("ab")
    return subprocess.Popen(
        args,
        cwd=BACKEND_ROOT,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


async def _wait(url: str, *, expected: int = 200, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(url)
                if response.status_code == expected:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise AssertionError(f"service did not become ready: {url}")


async def _wait_cli(role: str, env_file: Path, *, timeout: float = 40.0) -> dict:
    deadline = time.monotonic() + timeout
    last = "no probe"
    while time.monotonic() < deadline:
        env = dict(os.environ)
        env["APP_ENV_FILE"] = str(env_file)
        env["APP_RUNTIME_ROLE"] = role
        completed = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "app.manage", "health", "--role", role],
            cwd=BACKEND_ROOT, env=env, capture_output=True, text=True, timeout=30, check=False,
        )
        last = completed.stdout or completed.stderr
        if completed.returncode == 0:
            return json.loads(completed.stdout)
        await asyncio.sleep(0.5)
    raise AssertionError(f"{role} readiness did not pass: {last[-1000:]}")


async def _ticket(client: httpx.AsyncClient, token: str, since: int = 0) -> dict:
    response = await client.post(
        "/api/v1/realtime/ticket",
        json={"since": since},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _connect(token: str, api_port: int, ws_port: int) -> tuple[websockets.WebSocketClientProtocol, dict]:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", trust_env=False) as client:
        ticket = await _ticket(client, token)
    ws = await websockets.connect(
        f"ws://127.0.0.1:{ws_port}/ws?ticket={ticket['ticket']}",
        origin=f"http://127.0.0.1:{api_port}",
        proxy=None,
    )
    hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    assert hello["type"] == "hello"
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if frame["type"] == "replay_complete":
            break
        assert frame["type"] != "resync_required"
    return ws, ticket


async def _next_event(ws) -> dict:
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
        if frame["type"] == "event":
            return frame


async def test_api_ws_worker_scheduler_cross_process_two_devices_and_ack(tmp_path):
    api_port = int(os.environ["INTEGRATION_API_PORT"])
    ws_port = int(os.environ["INTEGRATION_WS_PORT"])
    ws2_port = int(os.environ["INTEGRATION_WS2_PORT"])
    base_env = Path(os.environ["INTEGRATION_ENV_FILE"])
    ws2_env = base_env.with_name(".env.ws2")
    base_text = base_env.read_text()
    ws2_env.write_text(
        base_text.replace(f"WS_PORT={ws_port}", f"WS_PORT={ws2_port}")
        .replace("WS_RECONCILE_SECONDS=1", "WS_RECONCILE_SECONDS=3600")
    )
    ws2_env.chmod(0o600)
    ws1_env = base_env.with_name(".env.ws1")
    ws1_env.write_text(base_text.replace("WS_RECONCILE_SECONDS=1", "WS_RECONCILE_SECONDS=3600"))
    ws1_env.chmod(0o600)
    sender = await create_user(f"xp-sender-{secrets.token_hex(4)}")
    recipient = await create_user(f"xp-recipient-{secrets.token_hex(4)}")
    conversation = await create_conversation(sender.id, recipient.id)
    logs = {role: tmp_path / f"{role}.log" for role in ("api", "ws", "ws2", "worker", "scheduler")}
    processes: list[subprocess.Popen] = []
    sockets: list = []
    try:
        processes.append(_start([sys.executable, "-m", "app.manage", "taskiq-scheduler"],
                                logs["scheduler"], str(base_env)))
        processes.append(_start([sys.executable, "-m", "app.manage", "taskiq-worker"],
                                logs["worker"], str(base_env)))
        processes.append(_start([sys.executable, "-m", "app.manage", "serve-ws"],
                                logs["ws"], str(ws1_env)))
        processes.append(_start([sys.executable, "-m", "app.manage", "serve-ws"],
                                logs["ws2"], str(ws2_env)))
        processes.append(_start([sys.executable, "-m", "app.manage", "serve-api"],
                                logs["api"], str(base_env)))
        await _wait(f"http://127.0.0.1:{ws_port}/health/ready")
        await _wait(f"http://127.0.0.1:{ws2_port}/health/ready")
        await _wait(f"http://127.0.0.1:{api_port}/api/health")
        scheduler = await _wait_cli("scheduler", base_env)
        assert scheduler["checks"]["scheduler"]["dispatch_count"] >= 1
        worker = await _wait_cli("worker", base_env)
        assert worker["checks"]["task_probe"]["status"] == "ok"

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", trust_env=False) as client:
            health = await client.get("/api/health")
            assert health.headers.get("x-request-id")
            assert health.json()["status"] == "ok"
            assert health.json()["readiness_status"] in {"ready", "degraded"}
            me = await client.get("/api/v1/realtime/watermark",
                                  headers={"Authorization": f"Bearer {token_for(recipient)}"})
            assert me.status_code == 200

        sender_ws, _ = await _connect(token_for(sender), api_port, ws_port)
        device_one, _ = await _connect(token_for(recipient), api_port, ws_port)
        device_two, _ = await _connect(token_for(recipient), api_port, ws2_port)
        sockets.extend([sender_ws, device_one, device_two])

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", trust_env=False) as client:
            response = await client.post(
                f"/api/v1/conversations/{conversation.id}/messages",
                json={"content": f"cross-process-{secrets.token_hex(4)}"},
                headers={"Authorization": f"Bearer {token_for(sender)}"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            expected_text = "cross-process"

        frames = await asyncio.gather(_next_event(device_one), _next_event(device_two), _next_event(sender_ws))
        assert frames[0]["event_id"] == frames[1]["event_id"]
        assert frames[0]["user_seq"] == frames[1]["user_seq"] == 1
        assert frames[0]["payload"]["type"] == "message"
        assert frames[0]["payload"]["message_id"] == body["id"]
        assert expected_text in frames[0]["payload"]["content"]
        for ws, frame in zip((device_one, device_two, sender_ws), frames, strict=True):
            await ws.send(json.dumps({"type": "ack", "user_seq": frame["user_seq"],
                                      "event_id": frame["event_id"]}))

        # The Taskiq worker (not a direct function call) confirmed the outbox row.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            async with session() as db:
                row = (await db.exec(
                    select(RealtimeEvent).where(RealtimeEvent.recipient_user_id == recipient.id)
                )).first()
                if row is not None and row.delivered_at is not None:
                    break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("Taskiq worker did not confirm the outbox event")

        # The one-time ticket is consumed: a second handshake with the same value
        # is rejected with the business auth close code instead of authenticating.
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", trust_env=False) as client:
            replay_ticket = await _ticket(client, token_for(recipient), since=1)
        first = await websockets.connect(
            f"ws://127.0.0.1:{ws_port}/ws?ticket={replay_ticket['ticket']}",
            origin=f"http://127.0.0.1:{api_port}",
            proxy=None,
        )
        sockets.append(first)
        await asyncio.wait_for(first.recv(), timeout=10)  # hello
        with pytest.raises(Exception) as closed:
            second = await websockets.connect(
                f"ws://127.0.0.1:{ws_port}/ws?ticket={replay_ticket['ticket']}",
                origin=f"http://127.0.0.1:{api_port}",
                proxy=None,
            )
            await asyncio.wait_for(second.recv(), timeout=10)
            await second.close()
        exc = closed.value
        code = getattr(exc, "code", None) or getattr(getattr(exc, "rcvd", None), "code", None)
        assert code == 4401, f"unexpected close: {exc!r}"
    finally:
        for ws in sockets:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001, S110 - best-effort test cleanup
                pass
        for process in reversed(processes):
            _stop(process)
        for role, path in logs.items():
            if path.exists() and path.stat().st_size:
                tail = path.read_text(errors="replace")[-2000:]
                if "Traceback" in tail or "ERROR" in tail:
                    print(f"--- {role} log tail ---\n{tail}", file=sys.stderr)

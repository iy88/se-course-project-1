"""Real Taskiq gates: reclaim after kill, retries and terminal failure."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.jobs.broker import build_bundle
from app.models.realtime import ServiceHeartbeat
from sqlmodel import select

from . import probe_tasks
from .support import session

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _start(role: str | None, env_file: Path, log: Path) -> subprocess.Popen:
    command = ([sys.executable, "-m", "app.manage", "taskiq-scheduler"] if role == "scheduler"
               else [sys.executable, "-m", "app.manage", "taskiq-worker"])
    env = dict(os.environ)
    env["APP_ENV_FILE"] = str(env_file)
    handle = log.open("ab")
    return subprocess.Popen(command, cwd=BACKEND_ROOT, env=env, stdout=handle,
                            stderr=subprocess.STDOUT, start_new_session=True)


def _stop(process: subprocess.Popen, *, force: bool = False) -> None:
    if process.poll() is not None:
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, sig)
    try:
        process.wait(timeout=10 if force else 20)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


async def _redis(settings):
    import redis.asyncio as aioredis
    return aioredis.Redis.from_url(settings.redis_url, decode_responses=True, max_connections=2)


async def _read_json(client, key: str) -> dict | None:
    raw = await client.get(key)
    return json.loads(raw) if raw else None


async def _wait_value(client, key: str, predicate, timeout: float = 25.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await _read_json(client, key)
        if last is not None and predicate(last):
            return last
        await asyncio.sleep(0.2)
    raise AssertionError(f"timed out waiting for {key}: {last}")


async def _wait_cli(role: str, env_file: Path, timeout: float = 40.0) -> dict:
    deadline = time.monotonic() + timeout
    last = ""
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
    raise AssertionError(f"{role} readiness failed: {last[-1000:]}")


async def _enqueue(name: str, *args) -> None:
    # A fresh broker per call avoids reusing a Redis pool bound to a previous
    # pytest event loop (each integration test gets a fresh loop).
    bundle = build_bundle(probe_tasks._settings)
    probe_tasks.register(bundle.broker, probe_tasks._settings)
    task = bundle.broker.find_task(name)
    assert task is not None
    try:
        await task.kiq(*args)
    finally:
        await bundle.broker.shutdown()
        if bundle.retry_source is not None:
            await bundle.retry_source.shutdown()
        await bundle.scheduler_heartbeat.close()


async def test_killed_worker_task_is_reclaimed_by_another_process(tmp_path):
    env_file = Path(os.environ["INTEGRATION_ENV_FILE"])
    settings = probe_tasks._settings
    client = await _redis(settings)
    log = tmp_path / "worker.log"
    token = ""
    worker = _start(None, env_file, log)
    scheduler = _start("scheduler", env_file, tmp_path / "scheduler.log")
    try:
        await _wait_cli("scheduler", env_file)
        await _wait_cli("worker", env_file)
        token = secrets.token_hex(8)
        await _enqueue(probe_tasks.SLOW_PROBE_TASK, token)
        key = settings.redis_key_prefix + "test:task:" + token
        started = await _wait_value(client, key, lambda value: value.get("phase") == "started", timeout=20)
        old_pid = started["pid"]
        _stop(worker, force=True)
        worker = _start(None, env_file, log)
        await _wait_value(client, key,
                          lambda value: value.get("phase") == "started" and value["pid"] != old_pid,
                          timeout=40)
        await client.set(settings.redis_key_prefix + "test:release:" + token, "1", ex=60)
        done = await _wait_value(client, key, lambda value: value.get("phase") == "done")
        # Completion must come from the process that reclaimed the task.
        assert isinstance(done["pid"], int)
        assert done["pid"] != old_pid
    finally:
        _stop(worker)
        _stop(scheduler)
        with contextlib.suppress(Exception):
            await client.delete(settings.redis_key_prefix + "test:task:" + token,
                                settings.redis_key_prefix + "test:release:" + token)
        await client.aclose()


async def test_retry_success_and_terminal_failure_are_observable(tmp_path):
    env_file = Path(os.environ["INTEGRATION_ENV_FILE"])
    settings = probe_tasks._settings
    client = await _redis(settings)
    log = tmp_path / "worker-retry.log"
    worker = _start(None, env_file, log)
    scheduler = _start("scheduler", env_file, tmp_path / "scheduler-retry.log")
    try:
        await _wait_cli("scheduler", env_file)
        await _wait_cli("worker", env_file)
        token = secrets.token_hex(8)
        await _enqueue(probe_tasks.RETRY_PROBE_TASK, token, 1)
        key = settings.redis_key_prefix + "test:task:" + token
        success = await _wait_value(client, key, lambda value: value.get("phase") == "success", timeout=30)
        assert success["count"] == 2

        failing = secrets.token_hex(8)
        await _enqueue(probe_tasks.RETRY_PROBE_TASK, failing, 99)
        terminal_key = settings.redis_key_prefix + "jobs:terminal-failure:" + settings.release_id
        terminal = await _wait_value(
            client, terminal_key,
            lambda value: value.get("task_name") == probe_tasks.RETRY_PROBE_TASK,
            timeout=40,
        )
        assert terminal["error"] == "RetryableJobError"
        async with session() as db:
            row = (await db.exec(
                select(ServiceHeartbeat).where(ServiceHeartbeat.role == "worker",
                                               ServiceHeartbeat.release_id == settings.release_id)
            )).first()
            assert row is not None
            assert int((row.details or {}).get("terminal_failures") or 0) >= 1
            assert (row.details or {}).get("last_terminal_failure")
    finally:
        _stop(worker)
        _stop(scheduler)
        with contextlib.suppress(Exception):
            await client.delete(settings.redis_key_prefix + "test:task:" + token,
                                settings.redis_key_prefix + "test:release:" + token)
        await client.aclose()




async def test_worker_readiness_fails_when_no_worker_is_running(tmp_path):
    env_file = Path(os.environ["INTEGRATION_ENV_FILE"])
    env = dict(os.environ)
    env["APP_ENV_FILE"] = str(env_file)
    env["APP_RUNTIME_ROLE"] = "worker"
    completed = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "app.manage", "health", "--role", "worker"],
        cwd=BACKEND_ROOT, env=env, capture_output=True, text=True, timeout=20, check=False,
    )
    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["checks"]["task_probe"]["status"] == "failed"

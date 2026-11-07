"""验收专用测试服务启动器：只读 .env.dev，向进程注入可受控 UTC 时钟。

不修改业务代码：在导入 FastAPI 应用之前，把会读取墙上时间的服务/路由模块的
``datetime`` 名称替换成 ``ClockDateTime``。``now()`` 返回
``真实UTC + offset``，offset 从运行目录的普通文本文件读取，每步动态生效。

用途仅限 7 天等待/冻结暂停场景；不修改数据库时间字段，不缩短 7 天规则。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime as RealDateTime
from datetime import timedelta
from pathlib import Path

from app.core.private_files import protect_private, require_private

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class ClockDateTime(RealDateTime):
    _clock_file: Path | None = None

    @classmethod
    def configure(cls, path: Path) -> None:
        cls._clock_file = path

    @classmethod
    def now(cls, tz=None):
        offset = 0
        path = cls._clock_file
        if path is not None:
            try:
                raw = path.read_text(encoding="ascii").strip()
                offset = int(raw or "0")
            except (OSError, ValueError):
                offset = 0
        return RealDateTime.now(tz) + timedelta(seconds=offset)


PATCH_MODULES = (
    "app.services.trade_wait",
    "app.services.trade_timeout",
    "app.services.trade_ops",
    "app.services.moderation",
    "app.services.cases",
    "app.services.conversations",
    "app.services.stored_objects",
    "app.api.v1.trades",
    "app.api.v1.products",
    "app.api.v1.categories",
    "app.api.v1.comments",
    "app.api.v1.notifications",
    "app.api.v1.admin.stats",
    "app.api.v1.admin.trades",
)


def _install_clock(clock_file: Path) -> list[str]:
    import importlib

    ClockDateTime.configure(clock_file)
    patched: list[str] = []
    for name in PATCH_MODULES:
        module = importlib.import_module(name)
        if hasattr(module, "datetime"):
            module.datetime = ClockDateTime  # type: ignore[attr-defined]
            patched.append(name)
    return patched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动验收专用测试服务（.env.dev + 受控时钟）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--ws-port", type=int, required=True)
    parser.add_argument("--clock-file", default=str(PROJECT_ROOT / "var" / "acceptance-real" / "clock.txt"))
    args = parser.parse_args(argv)

    clock_file = Path(args.clock_file).expanduser().resolve()
    clock_file.parent.mkdir(parents=True, exist_ok=True)
    if not clock_file.exists():
        clock_file.write_text("0\n", encoding="ascii")
        protect_private(clock_file)

    # 仅允许本轮私有隔离目录内的临时配置，与时钟文件位于同一目录。
    selected = os.environ.get("APP_ENV_FILE", "")
    if not selected:
        raise RuntimeError("acceptance server requires a private dotenv")
    env_path = Path(selected)
    if (env_path.is_symlink() or env_path.name != "runtime.env" or env_path.parent.resolve() != clock_file.parent
            or clock_file.parent.parent != (PROJECT_ROOT / "var").resolve()
            or not re.fullmatch(r"acceptance_[0-9a-f]{32}-.+", clock_file.parent.name)):
        raise RuntimeError("invalid acceptance dotenv path")
    require_private(env_path)
    from app.core.config import load_settings

    settings = load_settings(env_path)
    if not settings.database_schema.startswith("acceptance_") or not clock_file.parent.name.startswith(settings.database_schema + "-"):
        raise RuntimeError("acceptance server requires disposable schema")

    children: list[subprocess.Popen] = []
    try:
        from dotenv import set_key

        if not settings.redis_url:
            from redis import Redis
            from redis.exceptions import ConnectionError as RedisConnectionError
            from tests.integration_real.runner import _free_ports

            binary = shutil.which("redis-server")
            if binary is None:
                raise RuntimeError("split acceptance requires redis-server on PATH")
            port = _free_ports(1)[0]
            redis_process = subprocess.Popen([
                binary, "--bind", "127.0.0.1", "--port", str(port), "--save", "",
                "--appendonly", "no", "--dir", str(clock_file.parent),
            ])
            children.append(redis_process)
            url = f"redis://127.0.0.1:{port}/0"
            with Redis.from_url(url, socket_connect_timeout=1) as client:
                deadline = time.monotonic() + 10
                while redis_process.poll() is None and time.monotonic() < deadline:
                    try:
                        if client.ping():
                            break
                    except (OSError, RedisConnectionError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("acceptance Redis did not start")
            set_key(str(env_path), "REDIS_URL", url)
            set_key(str(env_path), "REDIS_KEY_PREFIX", settings.database_schema + ":")

        for key, value in {
            "API_PORT": str(args.port), "WS_PORT": str(args.ws_port),
            "WS_HOST": args.host, "WS_WORKERS": "1", "TASKIQ_WORKER_PROCESSES": "1",
            "TASKIQ_EXTRA_TASK_MODULES": "tests.acceptance_real.worker_clock",
        }.items():
            set_key(str(env_path), key, value)
        protect_private(env_path)

        for command in ("taskiq-worker", "taskiq-scheduler", "serve-ws"):
            children.append(subprocess.Popen(
                [sys.executable, "-m", "app.manage", command],
                env={**os.environ, "PROJECT1_ACCEPTANCE_CLOCK_FILE": str(clock_file)},
            ))

        from app.core.config import set_runtime_role
        set_runtime_role("api")
        _install_clock(clock_file)
        import uvicorn
        from app.main import app

        server = uvicorn.Server(uvicorn.Config(
            app, host=args.host, port=args.port, log_level="warning",
            access_log=False, lifespan="on",
        ))
        finished = threading.Event()
        stop_file = clock_file.with_suffix('.stop')

        def watch_services():
            while not finished.wait(0.1):
                if stop_file.is_file():
                    require_private(stop_file)
                    server.should_exit = True
                    return
                if any(child.poll() is not None for child in children):
                    server.should_exit = True
                    return

        watcher = threading.Thread(target=watch_services, daemon=True)
        watcher.start()
        try:
            server.run()
        finally:
            finished.set()
            watcher.join(timeout=2)
        return int(any(child.poll() is not None for child in children))
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    raise SystemExit(main())

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
import sys
import threading
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

    patched = _install_clock(clock_file)
    # 时钟补丁必须先于 app.main 导入；uvicorn 会复用已加载的模块。
    import uvicorn
    from app.main import app

    print(
        "acceptance clock server: "
        f"env={settings.environment} "
        f"clock_file={clock_file.name} patched={len(patched)}",
        flush=True,
    )
    server = uvicorn.Server(uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
        lifespan="on",
    ))
    finished = threading.Event()
    stop_file = clock_file.with_suffix('.stop')

    def watch_stop_file():
        while not finished.wait(0.1):
            if stop_file.is_file():
                require_private(stop_file)
                server.should_exit = True
                return

    watcher = threading.Thread(target=watch_stop_file, daemon=True)
    watcher.start()
    try:
        server.run()
    finally:
        finished.set()
        watcher.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

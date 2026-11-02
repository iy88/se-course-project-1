"""对象登记回收命令：默认只列出，显式 ``--delete`` 才清理未引用 staged 对象。

只允许后端 ``.env.dev`` 中配置的开发目标；没有定时任务、
没有证据 TTL，也不删除任何仍被业务表引用的对象。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import load_settings
from app.devtools._support import load_dev_config, make_async_engine
from app.services.stored_objects import cleanup_unreferenced_staged
from app.storage.base import StorageError, build_storage


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="objects",
        description=(
            "列出或清理 .env.dev test 环境中已确认无业务引用的 staged 对象；"
            "证据对象默认保留。"
        ),
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="实际删除未引用 staged 对象（证据保留）；默认只列出",
    )
    parser.add_argument("--limit", type=int, default=100, help="单次最多处理对象数")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    config = load_dev_config(require_storage=True)
    settings = load_settings(config.env_file)
    try:
        storage = build_storage(settings)
    except StorageError as exc:
        print(f"objects: 存储配置不可用：{type(exc).__name__}", file=sys.stderr)
        return 2

    engine = make_async_engine(config.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await cleanup_unreferenced_staged(
                session,
                storage,
                dry_run=not args.delete,
                limit=args.limit,
            )
    finally:
        await engine.dispose()

    print(
        ("objects: "
         f"dry_run={result.dry_run} candidates={len(result.candidates)} "
         f"deleted={len(result.deleted)} retained={len(result.retained)} "
         f"errors={len(result.errors)}")
    )
    return 0 if result.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(_run(_parse_args(argv)))
    except Exception as exc:  # noqa: BLE001 - CLI 不输出可能含连接串/SDK 正文的异常
        print(f"objects: 失败：{type(exc).__name__}", file=sys.stderr)
        return 1


run = main


if __name__ == "__main__":
    raise SystemExit(main())

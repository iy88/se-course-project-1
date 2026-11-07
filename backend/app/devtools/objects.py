"""Object-registration cleanup command: lists by default; only an explicit ``--delete`` removes unreferenced staged objects.

Only the development target configured in backend ``.env.dev`` is allowed. There is no
scheduled job and no evidence TTL, and objects still referenced by business tables are never deleted.
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
            "List or clean up staged objects in the .env.dev test environment that are confirmed "
            "to have no business references; evidence objects are retained by default."
        ),
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete unreferenced staged objects (evidence is retained); list only by default",
    )
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of objects to process per run")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    config = load_dev_config(require_storage=True)
    settings = load_settings(config.env_file)
    try:
        storage = build_storage(settings)
    except StorageError as exc:
        print(f"objects: storage configuration unavailable: {type(exc).__name__}", file=sys.stderr)
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
    except Exception as exc:  # noqa: BLE001 - CLI must not print exceptions that may contain connection strings or SDK bodies
        print(f"objects: failed: {type(exc).__name__}", file=sys.stderr)
        return 1


run = main


if __name__ == "__main__":
    raise SystemExit(main())

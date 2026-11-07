"""Append missing realtime/runtime settings without rewriting existing dotenv text.

Run with backend/.venv/bin/python. Preview by default; --apply creates private
backups and atomically replaces each selected file. Existing values win.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv.parser import parse_stream
from app.core.config import Settings

GROUPS = (
    ("Web 进程和监听，角色由启动命令/systemd选择。", (
        "api_workers", "ws_workers", "ws_host", "ws_port")),
    ("SQL 池为每进程上限；split 总和还需预留迁移、运维和发布余量。", (
        "api_db_", "ws_db_", "jobs_db_", "db_pool_", "db_connection_budget",
        "db_pre_ping", "db_recycle_", "db_lock_", "db_statement_", "db_idle_")),
    ("Redis 各池分别计数；生产需要 Redis 8.2+、ACL、AOF、noeviction 及内存预算。", (
        "redis_control_", "redis_publish_", "redis_reader_", "redis_stream_",
        "redis_connect_", "redis_socket_", "redis_connection_budget")),
    ("持久事件、outbox、准入及清理；业务与事件同事务。", (
        "realtime_", "outbox_", "retention_", "idempotency_")),
    ("Taskiq 官方 worker/scheduler；scheduler 只运行一份，reclaim 覆盖执行及预取等待。", (
        "taskiq_",)),
    ("WS 有界流、心跳、补拉与连接限制；不要为生产压测放宽 Origin。", (
        "ws_", "graceful_shutdown_")),
)
OVERRIDES = {"db_connection_budget": 48, "redis_connection_budget": 160}
DEV_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"


def values(raw: bytes) -> dict[str, str | None]:
    result = {}
    for item in parse_stream(io.StringIO(raw.decode("utf-8"))):
        if item.error:
            raise ValueError("invalid dotenv syntax (contents withheld)")
        if item.key is not None:
            if item.key in result:
                raise ValueError(f"duplicate dotenv key: {item.key}")
            result[item.key] = item.value
    return result


def origin_list(raw: str, *, prod: bool) -> str:
    for item in raw.split(","):
        parsed = urlsplit(item.strip())
        if (parsed.scheme not in ({"https"} if prod else {"http", "https"})
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or "*" in item or any(c in item for c in "\r\n")):
            raise ValueError("explicit valid origins are required")
    return raw


def render(raw: bytes, *, prod_origins: str | None = None) -> tuple[bytes, list[str]]:
    current = values(raw)
    environment = current.get("ENVIRONMENT")
    if environment not in {"dev", "prod"}:
        raise ValueError("ENVIRONMENT must explicitly select dev or prod")
    additions: list[str] = []
    seen = set(current)
    groups: list[str] = []

    def add(key: str, value) -> str | None:
        if key in seen or value is None or value == "":
            return None
        seen.add(key)
        additions.append(key)
        return f"{key}={str(value).lower() if isinstance(value, bool) else value}"

    auth = []
    if "ALLOWED_ORIGINS" not in current:
        origin = prod_origins if environment == "prod" else DEV_ORIGINS
        if not origin:
            raise ValueError("missing production ALLOWED_ORIGINS; pass --prod-origins")
        auth.append(add("ALLOWED_ORIGINS", origin_list(origin, prod=environment == "prod")))
    auth.extend([add("ALLOW_MISSING_ORIGIN", False), add("ALLOW_QUERY_TOKEN", False)])
    if any(auth):
        groups.append("# 显式 WS Origin 白名单；拒绝缺失来源与旧 query JWT。\n" + "\n".join(x for x in auth if x))
    for comment, prefixes in GROUPS:
        lines = []
        for name, field in Settings.model_fields.items():
            if not any(name == prefix or name.startswith(prefix) for prefix in prefixes):
                continue
            default = OVERRIDES.get(name, field.default)
            if not isinstance(default, (str, int, float, bool)):
                continue
            line = add(name.upper(), default)
            if line:
                lines.append(line)
        if lines:
            groups.append("# " + comment + "\n" + "\n".join(lines))
    if not additions:
        return raw, []
    newline = "\r\n" if b"\r\n" in raw else "\n"
    suffix = "\n\n# Runtime / realtime 配置迁移 v1；原有内容和值原样保留。\n" + "\n\n".join(groups) + "\n"
    return raw + suffix.replace("\n", newline).encode("utf-8"), additions


def apply(path: Path, before: bytes, after: bytes, backup_dir: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("dotenv must be a regular non-symlink file")
    if path.read_bytes() != before:
        raise ValueError("dotenv changed during migration; retry preview")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"{path.name}.{stamp}.{secrets.token_hex(4)}.bak"
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(before)
        stream.flush()
        os.fsync(stream.fileno())
    fd, temp = tempfile.mkstemp(prefix=path.name + ".migrating-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != before:
            raise ValueError("dotenv changed during migration; original preserved")
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, action="append")
    parser.add_argument("--prod-origins", help="required only when prod lacks ALLOWED_ORIGINS")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "var/env-backups")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        plans = []
        for path in args.env_file or [ROOT / "backend/.env.dev", ROOT / "backend/.env.prod"]:
            if path.is_symlink() or not path.is_file():
                raise ValueError("dotenv must be a regular non-symlink file")
            before = path.read_bytes()
            after, added = render(before, prod_origins=args.prod_origins)
            plans.append((path, before, after, added))
        for path, before, after, added in plans:
            backup = apply(path, before, after, args.backup_dir) if args.apply and added else None
            print(json.dumps({"file": str(path), "mode": "apply" if args.apply else "preview",
                              "added_keys": added, "backup": str(backup) if backup else None}, ensure_ascii=False))
        return 0
    except (OSError, ValueError):
        print("dotenv migration failed; inspect syntax, duplicate keys, explicit origins and file ownership; values withheld", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

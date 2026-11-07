"""Disposable resources owned by one acceptance run; never mutates the base schema."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from dotenv import dotenv_values, set_key
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import load_migration_settings, validate_migration_context
from app.core.private_files import protect_private, require_private
from app.devtools._support import (
    BACKEND_ROOT,
    FORBIDDEN_INHERITED_ENV,
    PROJECT_ROOT,
    DevConfig,
    GuardError,
    make_async_engine,
    write_private_json,
)

_PATTERN = re.compile(r"^acceptance_[0-9a-f]{32}$")

class Sandbox:
    def __init__(self, config: DevConfig):
        self.base = config
        self._fingerprint = self._target_fingerprint(config)
        self.name = "acceptance_" + secrets.token_hex(16)
        self._jwt_secret = secrets.token_urlsafe(48)
        self._file_secret = secrets.token_urlsafe(48)
        self.root = Path(tempfile.mkdtemp(prefix=self.name + "-", dir=PROJECT_ROOT / "var"))
        self.manifest = self.root / "ownership.json"
        self.config: DevConfig | None = None
        self.schema_created = False
        self.schema_pending = False
        self.process = None
        self.clock_file: Path | None = None
        self.active = False
        self.baseline = None
        self.cleanup_failures: list[str] = []
        self.evidence: dict[str, object] = {}
        self._migration = None
        self._write_manifest("allocated")

    @classmethod
    def recover(cls, path: Path, config: DevConfig) -> Sandbox:
        path = path.expanduser()
        if path.is_symlink() or path.name != "ownership.json":
            raise GuardError("恢复清单路径非法")
        root = path.parent.resolve()
        if root.parent != (PROJECT_ROOT / "var").resolve() or root.is_symlink():
            raise GuardError("恢复目录不在受控位置")
        require_private(root, directory=True)
        require_private(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("name", "")
        if data.get("version") != 1 or not _PATTERN.fullmatch(name) or not root.name.startswith(name + "-"):
            raise GuardError("恢复清单所有权标识非法")
        database = "postgresql" if config.database_url.startswith("postgresql+") else "sqlite"
        if (data.get("database") != database or data.get("backend") != config.storage_backend
                or data.get("target_fingerprint") != cls._target_fingerprint(config)):
            raise GuardError("恢复配置与原运行不一致")
        pid = data.get("server_pid")
        if pid:
            try:
                os.kill(int(pid), 0)
            except ProcessLookupError:
                pass
            except PermissionError:
                raise GuardError("无法确认原服务已停止") from None
            else:
                raise GuardError("原测试服务可能仍在运行；先确认并停止该服务")
        obj = cls.__new__(cls)
        obj.base, obj.name, obj.root, obj.manifest = config, name, root, path
        obj._fingerprint = cls._target_fingerprint(config)
        obj._jwt_secret = ""
        obj._file_secret = ""
        obj.config = None
        obj.schema_created = bool(data.get("schema_created"))
        obj.schema_pending = bool(data.get("schema_pending"))
        obj.active = bool(data.get("active"))
        obj.baseline = data.get("baseline")
        obj.process = None
        obj.clock_file = None
        obj.cleanup_failures = []
        obj.evidence = {}
        obj._migration = None
        if obj.schema_pending:
            migration = load_migration_settings(config.env_file)
            validate_migration_context(migration)
            obj._migration = migration
        return obj

    @staticmethod
    def _target_fingerprint(config: DevConfig) -> str:
        db = make_url(config.database_url)
        migration = None
        if db.drivername == "postgresql+asyncpg":
            m = load_migration_settings(config.env_file)
            validate_migration_context(m)
            migration = (m.migration_database_url, m.migration_owner_role, m.app_role)
        target = (config.environment, config.database_url, config.settings.database_schema,
                  migration, config.storage_backend, config.oss_region, config.oss_endpoint,
                  config.oss_media_bucket, config.oss_evidence_bucket, config.oss_access_key_id,
                  config.oss_access_key_secret, config.settings.kv_backend, config.settings.redis_url)
        return hashlib.sha256(repr(target).encode()).hexdigest()

    def _write_manifest(self, state: str) -> None:
        write_private_json(self.manifest, {"version": 1, "name": self.name, "state": state,
            "schema_created": self.schema_created, "schema_pending": self.schema_pending,
            "active": self.active, "server_pid": self.process.pid if self.process else None,
            "baseline": self.baseline, "database": "postgresql" if self.base.database_url.startswith("postgresql+") else "sqlite",
            "backend": self.base.storage_backend, "target_fingerprint": self._fingerprint})

    async def _base_sentinel(self):
        engine = make_async_engine(self.base.database_url)
        try:
            async with engine.connect() as conn:
                schema = self.base.settings.database_schema
                rows = (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname=:schema ORDER BY tablename"), {"schema": schema})).scalars().all()
                counts = {}
                for table in ("users", "audit_events", "stored_objects"):
                    if table in rows:
                        counts[table] = (await conn.execute(text(f'SELECT count(*) FROM "{schema}"."{table}"'))).scalar_one()
                return {"tables": list(rows), "counts": counts}
        finally:
            await engine.dispose()

    async def _create_pg(self):
        migration = load_migration_settings(self.base.env_file)
        validate_migration_context(migration)
        url = make_url(migration.migration_database_url)
        app_url = make_url(self.base.database_url)
        if (url.host, url.port or 5432, url.database) != (app_url.host, app_url.port or 5432, app_url.database) or migration.app_role != app_url.username:
            raise GuardError("迁移与应用连接目标不一致")
        self._migration = migration
        self.baseline = await self._base_sentinel()
        self.schema_pending = True
        self._write_manifest("schema_pending")
        engine = create_async_engine(migration.migration_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                identity = (await conn.execute(text("SELECT current_database(), current_user"))).one()
                if tuple(identity) != (url.database, url.username):
                    raise GuardError("迁移连接身份与所选配置不一致")
                await conn.execute(text(f'SET ROLE "{migration.migration_owner_role}"'))
                await conn.execute(text(f'CREATE SCHEMA "{self.name}"'))
                await conn.execute(text(f'CREATE TABLE "{self.name}"._acceptance_owner (token text NOT NULL)'))
                await conn.execute(text(f'INSERT INTO "{self.name}"._acceptance_owner VALUES (:token)'), {"token": self.name})
                await conn.execute(text(f'GRANT USAGE ON SCHEMA "{self.name}" TO "{migration.app_role}"'))
                await conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{self.name}" GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{migration.app_role}"'))
                await conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{self.name}" GRANT USAGE, SELECT ON SEQUENCES TO "{migration.app_role}"'))
            self.schema_created = True
            self._write_manifest("schema_created")
        finally:
            await engine.dispose()

    async def _create_sqlite(self, url: str):
        import app.models  # noqa: F401  # pyright: ignore[reportUnusedImport]
        from app.db.session import Base
        engine = make_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    def create(self) -> DevConfig:
        if self.config is not None:
            raise GuardError("隔离环境不能重复创建")
        if not _PATTERN.fullmatch(self.name) or self.name == self.base.settings.database_schema:
            raise GuardError("隔离标识非法或与基础 schema 相同")
        settings = self.base.settings
        if settings is None:
            raise GuardError("缺少经过校验的设置")
        journal = self.root / "storage-journal.jsonl"
        fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        protect_private(journal)
        updates = {"jwt_secret": self._jwt_secret, "file_url_secret": self._file_secret,
                   "mail_capture_path":self.root / "mailbox.jsonl",
                   "storage_operation_journal": journal, "database_schema": self.name, "storage_key_prefix": self.name + "/",
                   "redis_key_prefix": self.name + ":" if settings.kv_backend == "redis" else "",
                   "storage_local_root": self.root / "storage"}
        if self.base.database_url.startswith("postgresql+"):
            asyncio.run(self._create_pg())
            env = self.server_env()
            result = subprocess.run([sys.executable, "-m", "app.manage", "migrate"], cwd=BACKEND_ROOT,
                env=env, capture_output=True, timeout=120, check=False)
            if result.returncode:
                raise GuardError(f"隔离 schema 迁移失败（exit={result.returncode}）")
        else:
            updates["database_url"] = "sqlite+aiosqlite:///" + str(self.root / "sandbox.db")
            asyncio.run(self._create_sqlite(updates["database_url"]))
        settings = settings.model_copy(update=updates)
        self.config = replace(self.base, settings=settings, database_url=settings.database_url,
            database_schema=self.name, storage_local_root=settings.storage_local_root, jwt_secret=settings.jwt_secret, acceptance_sandbox=True, credentials_path=self.root / "identities.json")
        self._write_manifest("ready")
        return self.config

    def server_env(self) -> dict[str, str]:
        path = self.root / "runtime.env"
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            protect_private(path)
            values = {k: v for k, v in dotenv_values(self.base.env_file, interpolate=False).items() if v is not None and v.strip()}
            # SMTP credentials are unnecessary in the isolated test service.
            values = {k:v for k,v in values.items() if not k.startswith("SMTP_") or k=="SMTP_SECURITY"}
            values.update({"DATABASE_SCHEMA": self.name, "STORAGE_KEY_PREFIX": self.name + "/",
                           "MAIL_CAPTURE_PATH":str(self.root / "mailbox.jsonl"),
                           "STORAGE_LOCAL_ROOT": str(self.root / "storage"),
                           "STORAGE_OPERATION_JOURNAL": str(self.root / "storage-journal.jsonl"),
                           "JWT_SECRET": self._jwt_secret, "FILE_URL_SECRET": self._file_secret,
                           "TIMEOUT_SCAN_INTERVAL_SECONDS": "2",
                           # The existing acceptance client still uses the
                           # legacy query-token frame contract; this explicit
                           # test-only transition keeps that suite meaningful.
                           "ALLOW_QUERY_TOKEN": "true",
                           "ALLOW_MISSING_ORIGIN": "true",
                           "ALLOWED_ORIGINS": "http://localhost:5173"})
            if self.base.settings.kv_backend == "redis":
                values["REDIS_KEY_PREFIX"] = self.name + ":"
            if self.base.database_url.startswith("sqlite+"):
                values["DATABASE_URL"] = "sqlite+aiosqlite:///" + str(self.root / "sandbox.db")
            for key, value in values.items():
                set_key(str(path), key, value)
        env = {k: v for k, v in os.environ.items() if k not in FORBIDDEN_INHERITED_ENV}
        env["APP_ENV_FILE"] = str(path)
        return env

    async def _cleanup_redis(self):
        import redis.asyncio as redis
        if self.base.settings.kv_backend != "redis":
            return 0
        client = redis.from_url(self.base.settings.redis_url, decode_responses=True, socket_timeout=5)
        try:
            prefix = self.name + ":"
            claim_prefix = "autoclaim:" + prefix
            patterns = (prefix + "*", claim_prefix + "*:" + prefix + "*")
            keys = [key for pattern in patterns async for key in client.scan_iter(match=pattern, count=200)]
            if any(not key.startswith(prefix) and not (
                key.startswith(claim_prefix) and ":" + prefix in key[len(claim_prefix):]
            ) for key in keys):
                raise GuardError("Redis 返回前缀外 key")
            if keys:
                await client.delete(*keys)
            remaining = [key for pattern in patterns async for key in client.scan_iter(match=pattern, count=200)]
            if remaining:
                raise GuardError("Redis 隔离前缀清理后仍有 key")
            return len(keys)
        finally:
            await client.aclose()

    async def _drop_schema(self):
        if not self.schema_pending:
            return False
        if self._migration is None:
            raise GuardError("缺少隔离迁移配置")
        engine = create_async_engine(self._migration.migration_database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                url = make_url(self._migration.migration_database_url)
                identity = (await conn.execute(text("SELECT current_database(), current_user"))).one()
                if tuple(identity) != (url.database, url.username):
                    raise GuardError("迁移连接身份与所选配置不一致")
                await conn.execute(text(f'SET ROLE "{self._migration.migration_owner_role}"'))
                owner = (await conn.execute(text("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=:name"), {"name": self.name})).scalar_one_or_none()
                if owner is None:
                    self.schema_pending = False
                    self.schema_created = False
                    return True
                if owner != self._migration.migration_owner_role:
                    raise GuardError("schema 所有者不符，拒绝删除")
                marker = (await conn.execute(text("SELECT to_regclass(:marker)"), {"marker": self.name + "._acceptance_owner"})).scalar_one_or_none()
                if marker is None:
                    raise GuardError("schema 缺少所有权标记，拒绝删除")
                tokens = (await conn.execute(text(f'SELECT token FROM "{self.name}"._acceptance_owner'))).scalars().all()
                if tokens != [self.name]:
                    raise GuardError("schema 所有权标记不符，拒绝删除")
                await conn.execute(text(f'DROP SCHEMA "{self.name}" CASCADE'))
                exists = (await conn.execute(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:name)"), {"name": self.name})).scalar_one()
                if exists:
                    raise GuardError("隔离 schema 清理后仍存在")
            self.schema_created = False
            self.schema_pending = False
            return True
        finally:
            await engine.dispose()

    def cleanup(self) -> dict[str, object]:
        if not _PATTERN.fullmatch(self.name) or not self.root.name.startswith(self.name + "-"):
            raise GuardError("拒绝清理非本轮资源")
        failures = []
        def attempt(label, fn):
            try:
                self.evidence[label] = fn()
            except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
                failures.append(f"{label}: {type(exc).__name__}")
        if self.active and self.base.storage_backend == "oss":
            def clean_oss():
                from app.storage.base import build_storage
                from app.storage.oss import OssStorage
                settings = self.base.settings.model_copy(update={"storage_key_prefix": self.name + "/", "storage_operation_journal": self.root / "storage-journal.jsonl"})
                storage = build_storage(settings)
                if not isinstance(storage, OssStorage):
                    raise GuardError("存储后端不是 OSS")
                count = storage.cleanup_from_journal()
                self.evidence["oss_verification"] = "all journaled puts absent by HEAD; prefix listing not performed"
                return count
            attempt("oss_removed", clean_oss)
        if self.active:
            attempt("redis_removed", lambda: asyncio.run(self._cleanup_redis()))
        attempt("schema_removed", lambda: asyncio.run(self._drop_schema()))
        if self.baseline is not None:
            def compare():
                same = asyncio.run(self._base_sentinel()) == self.baseline
                if not same:
                    raise GuardError("base schema 哨兵变化")
                return same
            attempt("base_sentinel_unchanged", compare)
        # Never retain password files, even when external cleanup fails.
        for name in ("runtime.env", "mailbox.jsonl", "identities.json", "identities.json.lock", "sandbox.db", "sandbox.db-wal", "sandbox.db-shm"):
            attempt("remove_" + name, lambda name=name: (self.root / name).unlink(missing_ok=True))
        if self.base.storage_backend == "local":
            def remove_local_storage():
                storage_root = self.root / "storage"
                if storage_root.is_symlink():
                    raise GuardError("本地存储目录是符号链接")
                if storage_root.exists():
                    shutil.rmtree(storage_root)
            attempt("local_storage_removed", remove_local_storage)
        self.cleanup_failures = failures
        if failures:
            self._write_manifest("cleanup_failed")
        else:
            shutil.rmtree(self.root)
            self.evidence["local_root_absent"] = not self.root.exists()
        return {"cleanup_failures": failures, **self.evidence}

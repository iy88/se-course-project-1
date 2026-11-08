"""Service fingerprint and shared safety helpers for test seed / acceptance tools.

Used only by ``app.devtools`` and never loaded at service startup. All error messages,
reports, and logs avoid exposing connection strings, passwords, access keys, JWTs,
signed URLs, response bodies, or real database content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.private_files import exclusive_lock, protect_private

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env.dev"
PROD_ENV_FILE = BACKEND_ROOT / ".env.prod"
MAX_OBJECT_BYTES = 100 * 1024 * 1024

FORBIDDEN_INHERITED_ENV = frozenset(
    {
        "DATABASE_SCHEMA",
        "STORAGE_KEY_PREFIX",
        "STORAGE_OPERATION_JOURNAL",
        "REDIS_KEY_PREFIX",
        "ENVIRONMENT",
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "MIGRATION_OWNER_ROLE",
        "DB_AUTO_CREATE",
        "REDIS_URL",
        "STORAGE_BACKEND",
        "STORAGE_LOCAL_ROOT",
        "OSS_REGION",
        "OSS_ENDPOINT",
        "OSS_BUCKET",
        "OSS_MEDIA_BUCKET",
        "OSS_EVIDENCE_BUCKET",
        "OSS_ACCESS_KEY_ID",
        "OSS_ACCESS_KEY_SECRET",
        "OSS_TIMEOUT_SECONDS",
        "OSS_MAX_RETRIES",
        "JWT_SECRET",
        "JWT_ALGORITHM",
        "JWT_EXPIRE_DAYS",
        "FILE_URL_SECRET",
        "FILE_URL_EXPIRE_SECONDS",
        "DEV_EXPOSE_VERIFICATION_CODE",
    }
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PLACEHOLDER_MARKERS = ("replace", "change-me", "changeme", "your-", "todo", "<", ">")


class DevtoolError(RuntimeError):
    """An error that is safe to show to the operator; callers print only this class of message."""


class GuardError(DevtoolError):
    """The environment or target failed test-protection validation."""


class SeedError(DevtoolError):
    """Seed account state or credentials file is inconsistent."""


class StorageProbeError(DevtoolError):
    """Controlled-storage location verification failed."""


# ---------------------------------------------------------------------------
# Environment selection and validation
# ---------------------------------------------------------------------------


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def check_inherited_overrides(environ: Mapping[str, str] | None = None) -> None:
    """Reject process-environment overrides of connections, keys, or behavior; report names only, never values."""
    present = sorted(name for name in FORBIDDEN_INHERITED_ENV if name in _env(environ))
    if present:
        raise GuardError("Inherited configuration overrides detected; refusing to run: " + ", ".join(present))


def resolve_dev_env_file(
    environ: Mapping[str, str] | None = None,
    *,
    backend_root: Path = BACKEND_ROOT,
) -> Path:
    """Allow only the backend-directory .env.dev; reject an explicit .env.prod or any other path."""
    expected = (backend_root / ".env.dev").resolve()
    raw = _env(environ).get("APP_ENV_FILE")
    if raw is None:
        if not expected.is_file():
            raise GuardError("Missing backend .env.dev configuration file")
        return expected
    if not str(raw).strip():
        raise GuardError("APP_ENV_FILE must not be empty")

    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = backend_root / path
    resolved = path.resolve()
    if resolved == PROD_ENV_FILE.resolve() or resolved.name == ".env.prod":
        raise GuardError("Refusing to use .env.prod; test seed/acceptance may only use backend .env.dev")
    if resolved != expected:
        raise GuardError("APP_ENV_FILE must point to the backend .env.dev")
    if not resolved.is_file():
        raise GuardError("Missing backend .env.dev configuration file")
    return resolved


def resolve_explicit_dev_env_file(env_file: str | Path) -> Path:
    """An env_file already resolved by the manage command must also equal backend .env.dev exactly."""
    path = Path(env_file).expanduser()
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    resolved = path.resolve()
    if resolved == PROD_ENV_FILE.resolve() or resolved.name == ".env.prod":
        raise GuardError("Refusing to use .env.prod; test seed/acceptance may only use backend .env.dev")
    if resolved != DEFAULT_ENV_FILE.resolve():
        raise GuardError("env_file must point to the backend .env.dev")
    if not resolved.is_file():
        raise GuardError("Missing backend .env.dev configuration file")
    return resolved


def _is_placeholder(value: str | None) -> bool:
    if not value or not value.strip():
        return True
    lowered = value.strip().lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class DevConfig:
    env_file: Path
    environment: str
    database_url: str = field(repr=False)
    storage_backend: str
    storage_local_root: Path | None
    oss_region: str = field(repr=False)
    oss_endpoint: str = field(repr=False)
    oss_media_bucket: str
    oss_evidence_bucket: str
    oss_access_key_id: str = field(repr=False)
    oss_access_key_secret: str = field(repr=False)
    oss_timeout_seconds: float
    oss_max_retries: int
    jwt_secret: str = field(repr=False)
    jwt_algorithm: str
    settings: Any = field(default=None, repr=False)
    database_schema: str = "app"
    acceptance_sandbox: bool = False
    credentials_path: Path | None = None

    @property
    def database(self) -> URL:
        return make_url(self.database_url)

    @property
    def environment_fingerprint(self) -> str:
        """Digest derived from the selected target for report correlation; contains no secrets."""
        db = self.database
        raw = repr((db.drivername, db.host, db.port, db.database, db.username,
                    self.storage_backend, self.oss_endpoint, self.oss_media_bucket,
                    self.oss_evidence_bucket, self.database_schema))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def bucket_for_namespace(self) -> Mapping[str, str]:
        return {
            "product": self.oss_media_bucket,
            "avatar": self.oss_media_bucket,
            "chat": self.oss_media_bucket,
            "report": self.oss_evidence_bucket,
        }


def validate_dev_config_values(
    values: Mapping[str, str],
    *,
    env_file: Path,
    require_storage: bool = True,
) -> DevConfig:
    """Pure value validation shared by real loading and offline guard tests. Errors contain field names only."""
    if env_file.name == ".env.prod" or env_file.resolve() == PROD_ENV_FILE.resolve():
        raise GuardError("Refusing to use .env.prod; test seed/acceptance may only use backend .env.dev")

    missing = [name for name in ("ENVIRONMENT", "DATABASE_URL", "JWT_SECRET", "JWT_ALGORITHM") if not str(values.get(name, "")).strip()]
    if missing:
        raise GuardError("Missing configuration fields: " + ", ".join(missing))

    environment = str(values["ENVIRONMENT"]).strip().lower()
    if environment not in {"dev", "test"}:
        raise GuardError("ENVIRONMENT must be dev or test")

    database_url = str(values["DATABASE_URL"]).strip()
    try:
        parsed = make_url(database_url)
    except (ArgumentError, ValueError):
        raise GuardError("DATABASE_URL cannot be parsed") from None
    if parsed.drivername not in {"postgresql+asyncpg", "sqlite+aiosqlite"}:
        raise GuardError("DATABASE_URL must use postgresql+asyncpg or sqlite+aiosqlite")
    if parsed.drivername == "postgresql+asyncpg" and not all((parsed.username, parsed.database, parsed.host, parsed.password)):
        raise GuardError("DATABASE_URL is missing connection fields")

    oss_fields=("OSS_REGION","OSS_ENDPOINT","OSS_MEDIA_BUCKET","OSS_EVIDENCE_BUCKET","OSS_ACCESS_KEY_ID","OSS_ACCESS_KEY_SECRET")
    storage_backend = "oss" if any(str(values.get(field," ")).strip() for field in oss_fields) else "local"
    if require_storage:
        if storage_backend == "local" and not str(values.get("STORAGE_LOCAL_ROOT", "")).strip():
            raise GuardError("Local storage requires STORAGE_LOCAL_ROOT")
        for name in ("OSS_MEDIA_BUCKET", "OSS_EVIDENCE_BUCKET"):
            if storage_backend == "oss" and not str(values.get(name, "")).strip():
                raise GuardError(f"{name} must not be empty")
        if storage_backend == "oss" and not str(values.get("OSS_ENDPOINT", "")).strip().lower().startswith("https://"):
            raise GuardError("OSS_ENDPOINT must be an HTTPS URL")
        if storage_backend == "oss" and _is_placeholder(str(values.get("OSS_REGION", ""))):
            raise GuardError("OSS_REGION must not be empty or a placeholder")
        if storage_backend == "oss" and _is_placeholder(str(values.get("OSS_ACCESS_KEY_ID", ""))):
            raise GuardError("OSS_ACCESS_KEY_ID must not be empty or a placeholder")
        if storage_backend == "oss" and _is_placeholder(str(values.get("OSS_ACCESS_KEY_SECRET", ""))):
            raise GuardError("OSS_ACCESS_KEY_SECRET must not be empty or a placeholder")

    if not str(values["JWT_SECRET"]).strip():
        raise GuardError("JWT_SECRET must not be empty or a placeholder")
    if _is_placeholder(str(values["JWT_ALGORITHM"])):
        raise GuardError("JWT_ALGORITHM must not be empty or a placeholder")

    raw_timeout = str(values.get("OSS_TIMEOUT_SECONDS", "15") or "15")
    raw_retries = str(values.get("OSS_MAX_RETRIES", "2") or "2")
    try:
        timeout = float(raw_timeout)
        retries = int(raw_retries)
    except ValueError:
        raise GuardError("OSS_TIMEOUT_SECONDS/OSS_MAX_RETRIES have invalid format") from None

    return DevConfig(
        env_file=env_file,
        environment=environment,
        database_url=database_url,
        storage_backend=storage_backend,
        storage_local_root=Path(str(values["STORAGE_LOCAL_ROOT"])) if values.get("STORAGE_LOCAL_ROOT") else None,
        oss_region=str(values.get("OSS_REGION", "")).strip(),
        oss_endpoint=str(values.get("OSS_ENDPOINT", "")).strip().rstrip("/"),
        oss_media_bucket=str(values.get("OSS_MEDIA_BUCKET", "")).strip(),
        oss_evidence_bucket=str(values.get("OSS_EVIDENCE_BUCKET", "")).strip(),
        oss_access_key_id=str(values.get("OSS_ACCESS_KEY_ID", "")).strip(),
        oss_access_key_secret=str(values.get("OSS_ACCESS_KEY_SECRET", "")).strip(),
        oss_timeout_seconds=timeout,
        oss_max_retries=retries,
        jwt_secret=str(values["JWT_SECRET"]).strip(),
        jwt_algorithm=str(values["JWT_ALGORITHM"]).strip(),
    )


def load_dev_config(
    *,
    require_storage: bool = True,
    environ: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
    for_acceptance: bool = False,
) -> DevConfig:
    """Read .env.dev through the centralized configuration loader, then validate the dev environment and target fields."""
    check_inherited_overrides(environ)
    resolved_env_file = (
        resolve_explicit_dev_env_file(env_file)
        if env_file is not None
        else resolve_dev_env_file(environ)
    )

    try:
        from app.core.config import (
            ConfigurationError,
            load_settings,
            )
    except ModuleNotFoundError as exc:  # pragma: no cover - explicit dependency error until the config module is available
        raise GuardError(f"Missing configuration dependency module: {exc.name}") from None

    try:
        settings = load_settings(resolved_env_file, for_acceptance=for_acceptance)
    except ConfigurationError as exc:
        raise GuardError(str(exc)) from None

    values = {
        "ENVIRONMENT": settings.environment,
        "DATABASE_URL": settings.database_url,
        "STORAGE_LOCAL_ROOT": str(settings.storage_local_root) if settings.storage_local_root is not None else "",
        "OSS_REGION": settings.oss_region,
        "OSS_ENDPOINT": settings.oss_endpoint,
        "OSS_MEDIA_BUCKET": settings.oss_media_bucket,
        "OSS_EVIDENCE_BUCKET": settings.oss_evidence_bucket,
        "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
        "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
        "OSS_TIMEOUT_SECONDS": str(settings.oss_timeout_seconds),
        "OSS_MAX_RETRIES": str(settings.oss_max_retries),
        "JWT_SECRET": settings.jwt_secret,
        "JWT_ALGORITHM": settings.jwt_algorithm,
    }
    from dataclasses import replace
    config = validate_dev_config_values(values, env_file=resolved_env_file, require_storage=require_storage)
    return replace(config, settings=settings, database_schema=settings.database_schema)


# ---------------------------------------------------------------------------
# Database: read-only verification + seed session
# ---------------------------------------------------------------------------


def make_async_engine(url: str, *, schema: str | None = None) -> AsyncEngine:
    kwargs: dict[str, Any] = {"poolclass": NullPool, "future": True}
    if url.startswith("postgresql+asyncpg"):
        from app.core.config import validate_schema_identifier
        schema = validate_schema_identifier(schema or "app")
        kwargs["connect_args"] = {"timeout": 10, "command_timeout": 30, "server_settings": {"search_path": f'"{schema}"'}}
    return create_async_engine(url, **kwargs)


async def _prepare_connection(conn: AsyncConnection, url: str) -> None:
    if url.startswith("postgresql"):
        pass  # search_path is fixed on the engine connection


@dataclass(frozen=True)
class DatabaseIdentity:
    database: str
    user: str


async def probe_database(url: str, *, expect_test_target: bool = True) -> DatabaseIdentity:
    if url.startswith("sqlite+"):
        return DatabaseIdentity(database="sqlite", user="local")
    engine = make_async_engine(url)
    try:
        async with engine.connect() as conn:
            await _prepare_connection(conn, url)
            row = (await conn.execute(text("SELECT current_database(), current_user"))).one()
    except SQLAlchemyError as exc:
        raise GuardError(f"Unable to connect to the test database ({type(exc).__name__})") from None
    finally:
        await engine.dispose()

    identity = DatabaseIdentity(database=str(row[0]), user=str(row[1]))
    parsed = make_url(url)
    if expect_test_target and identity != DatabaseIdentity(parsed.database or "", parsed.username or ""):
        raise GuardError("Database session identity does not match the selected configuration")
    return identity


@asynccontextmanager
async def readonly_connection(url: str, *, schema: str | None = None) -> AsyncIterator[AsyncConnection]:
    engine = make_async_engine(url, schema=schema)
    try:
        async with engine.connect() as conn:
            await _prepare_connection(conn, url)
            yield conn
    finally:
        await engine.dispose()


async def readonly_mapping(
    url: str, sql: str, params: Mapping[str, Any] | None = None, *, schema: str | None = None
) -> Mapping[str, Any] | None:
    async with readonly_connection(url, schema=schema) as conn:
        row = (await conn.execute(text(sql), dict(params or {}))).mappings().first()
        return dict(row) if row is not None else None


async def readonly_rows(
    url: str, sql: str, params: Mapping[str, Any] | None = None, *, schema: str | None = None
) -> list[Mapping[str, Any]]:
    async with readonly_connection(url, schema=schema) as conn:
        result = await conn.execute(text(sql), dict(params or {}))
        return [dict(row) for row in result.mappings().all()]


def is_undefined_table(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None)
    return sqlstate == "42P01" or "undefinedtable" in type(orig).__name__.lower()


# ---------------------------------------------------------------------------
# JWT service fingerprint and HTTP client
# ---------------------------------------------------------------------------


def mint_fingerprint_token(
    config: DevConfig, *, user_id: int, role: str, run_id: str, ttl_seconds: int = 120
) -> str:
    """Sign a short-lived JWT locally for the real service to verify with its own .env.dev key."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "scope": "service-fingerprint",
        "run_id": run_id,
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)


def decode_fingerprint_token(config: DevConfig, token: str) -> dict[str, Any]:
    return jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])


# ---------------------------------------------------------------------------
# Controlled storage probe: uses only B's StorageBackend and this run's keys; never scans buckets
# ---------------------------------------------------------------------------


class StorageProbe:
    def __init__(self, backend: Any, settings: Any) -> None:
        self.backend = backend
        self.settings = settings

    @classmethod
    def build(cls, config: DevConfig) -> StorageProbe:
        try:
            from app.core.config import load_settings
            from app.storage.base import build_storage
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise StorageProbeError(f"Missing storage dependency module: {exc.name}") from None
        try:
            settings = config.settings or load_settings(config.env_file)
        except Exception as exc:  # noqa: BLE001 - configuration errors do not expose values
            raise StorageProbeError(f"Storage configuration failed to load ({type(exc).__name__})") from None
        try:
            backend = build_storage(settings)
        except Exception as exc:  # noqa: BLE001 - convert to a safe message only
            from app.storage.base import StorageError

            if isinstance(exc, StorageError):
                raise StorageProbeError(str(exc)) from None
            raise StorageProbeError(f"Storage client initialization failed ({type(exc).__name__})") from None
        return cls(backend, settings)

    def bucket_name_for(self, key: str) -> str:
        try:
            from app.storage.base import bucket_role_for_namespace, namespace_for_key
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise StorageProbeError(f"Missing storage dependency module: {exc.name}") from None
        try:
            role = bucket_role_for_namespace(namespace_for_key(key))
        except Exception as exc:  # noqa: BLE001 - sanitize all storage-layer exceptions
            raise StorageProbeError(str(exc)) from None
        return (
            str(self.settings.oss_media_bucket)
            if role == "media"
            else str(self.settings.oss_evidence_bucket)
        )

    def exists(self, key: str) -> bool:
        try:
            return bool(self.backend.exists(key))
        except Exception as exc:  # noqa: BLE001 - sanitize all storage-layer exceptions
            raise self._translated(exc) from None

    def read(self, key: str) -> bytes:
        try:
            content = self.backend.open(key)
        except Exception as exc:  # noqa: BLE001 - sanitize all storage-layer exceptions
            raise self._translated(exc) from None
        if not isinstance(content, bytes) or len(content) > MAX_OBJECT_BYTES:
            raise StorageProbeError("Object read returned invalid content or exceeded 100 MiB")
        return content

    def delete(self, key: str) -> None:
        try:
            self.backend.delete(key)
        except Exception as exc:  # noqa: BLE001 - sanitize all storage-layer exceptions
            raise self._translated(exc) from None

    @staticmethod
    def _translated(exc: Exception) -> StorageProbeError:
        try:
            from app.storage.base import StorageError

            if isinstance(exc, StorageError):
                return StorageProbeError(str(exc))
        except ModuleNotFoundError:  # pragma: no cover
            pass
        return StorageProbeError(f"Storage operation failed ({type(exc).__name__})")


# ---------------------------------------------------------------------------
# Credentials file permissions and atomic writes
# ---------------------------------------------------------------------------


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    protect_private(path, directory=True)


def file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    ensure_private_dir(path.parent)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        protect_private(temp)
        os.replace(temp, path)
        protect_private(path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@contextmanager
def credentials_lock(path: Path) -> Iterator[None]:
    ensure_private_dir(path.parent)
    lock_path = path.with_suffix(path.suffix + ".lock")
    if lock_path.is_symlink():
        raise OSError('Lock file must not be a symlink')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        protect_private(lock_path)
        with exclusive_lock(fd):
            yield
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Run records
# ---------------------------------------------------------------------------

def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def validate_run_id(run_id: str) -> str:
    if not _SAFE_ID_RE.fullmatch(run_id):
        raise GuardError("--run-id allows only letters, digits, dots, underscores, and hyphens, length 1-64")
    return run_id

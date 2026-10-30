"""Load runtime configuration exclusively from the selected dotenv file."""

from __future__ import annotations

import ipaddress
import os
import re
import stat
from email.utils import parseaddr
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values
from dotenv.parser import parse_stream
from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
DEFAULT_ENV_FILE = BACKEND_ROOT / '.env.dev'
PROD_ENV_FILE = BACKEND_ROOT / '.env.prod'
_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_PLACEHOLDER_MARKERS = ('replace', 'change-me', 'changeme', 'your-', 'todo', '<', '>')
_DEV_DEFAULT_SECRETS = {'dev-secret-change-me', 'dev-file-secret-change-me', 'secret', ''}


class ConfigurationError(RuntimeError):
    """Configuration errors contain field names, never values."""


def validate_schema_identifier(value: str) -> str:
    if len(value) > 63 or not _IDENTIFIER.fullmatch(value):
        raise ValueError('invalid database schema identifier')
    return value


def validate_storage_key_prefix(value: str) -> str:
    if not value:
        return ''
    prefix = value.removesuffix('/')
    if not prefix or any(not re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in prefix.split('/')):
        raise ValueError('invalid storage key prefix')
    return prefix + '/'


def is_placeholder_secret(value: str | None, *, min_length: int = 1) -> bool:
    if not value or len(value.strip()) < min_length:
        return True
    lowered = value.strip().lower()
    return lowered in _DEV_DEFAULT_SECRETS or any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _safe_url_info(url: str) -> tuple[str, str, str, str]:
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):
        raise ConfigurationError('DATABASE_URL is not a valid database URL') from None
    return parsed.drivername, parsed.username or '', parsed.database or '', parsed.host or ''


def resolve_env_file(env_file: str | Path | None = None) -> Path:
    raw = env_file if env_file is not None else os.environ.get('APP_ENV_FILE')
    if raw is None:
        return DEFAULT_ENV_FILE
    if not str(raw).strip():
        raise ConfigurationError('APP_ENV_FILE must not be blank')
    path = Path(raw).expanduser()
    if not path.is_absolute():
        backend_relative = BACKEND_ROOT / path
        repo_relative = PROJECT_ROOT / path
        path = repo_relative if not backend_relative.is_file() and repo_relative.is_file() else backend_relative
    return path.resolve()


def _load_base_settings(cls, path: Path):
    if not path.is_file():
        raise ConfigurationError('environment file not found')
    try:
        with path.open(encoding='utf-8') as stream:
            bindings = list(parse_stream(stream))
        keys = [binding.key for binding in bindings if binding.key is not None]
        if any(binding.error for binding in bindings) or len(keys) != len({key.lower() for key in keys}):
            raise ConfigurationError('invalid or duplicate dotenv entries')
        values = dotenv_values(path, interpolate=False)
    except (OSError, UnicodeError):
        raise ConfigurationError('cannot read environment file') from None
    unresolved = sorted(key for key, value in values.items() if value is not None and '${' in value)
    if unresolved:
        raise ConfigurationError('unresolved configuration fields: ' + ', '.join(unresolved))
    blank = sorted(key for key, value in values.items() if value is None or not value.strip())
    if blank:
        raise ConfigurationError('blank configuration fields: ' + ', '.join(blank))
    if any(key.upper() == 'MAIL_BACKEND' for key in values):
        raise ConfigurationError('MAIL_BACKEND is not configurable; normal execution uses SMTP')
    obsolete = sorted(key.upper() for key in values if key.upper() in {'KV_BACKEND', 'STORAGE_BACKEND', 'DATABASE_BACKEND'})
    if obsolete:
        raise ConfigurationError('backend selectors are not configurable: ' + ', '.join(obsolete))
    try:
        return cls(**{key.lower(): value for key, value in values.items()})
    except ValidationError as exc:
        fields = sorted({str(error['loc'][0]).upper() for error in exc.errors() if error.get('loc')})
        raise ConfigurationError('invalid or missing configuration fields: ' + (', '.join(fields) or 'unknown')) from None


class DotenvOnlySettings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore', case_sensitive=False)

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (init_settings,)


class Settings(DotenvOnlySettings):
    app_name: str
    environment: Literal['dev', 'test', 'prod']
    database_url: str
    db_auto_create: bool
    database_schema: str
    audit_trusted_proxies: str
    redis_url: str = ''
    redis_key_prefix: str = ''
    storage_key_prefix: str = ''
    storage_operation_journal: Path | None = None
    storage_local_root: Path | None = None
    oss_region: str = ''
    oss_endpoint: str = ''
    oss_media_bucket: str = ''
    oss_evidence_bucket: str = ''
    oss_access_key_id: str = ''
    oss_access_key_secret: str = ''
    oss_timeout_seconds: int = 15
    oss_max_retries: int = 2
    jwt_secret: str
    jwt_algorithm: str
    jwt_expire_days: int = 7
    file_url_secret: str
    file_url_expire_seconds: int = 3600
    upload_lease_expire_seconds: int = 600
    comment_rate_limit_count: int = 3
    comment_rate_limit_seconds: int = 60
    trade_confirm_timeout_days: int = 7
    timeout_scan_interval_seconds: int = 60
    verification_code_ttl_seconds: int = 600
    verification_send_interval_seconds: int = 60
    smtp_host: str = ''
    smtp_port: int = 465
    smtp_security: Literal['ssl', 'starttls']
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_from_email: str = ''
    smtp_from_name: str = ''
    smtp_timeout_seconds: int = 10
    mail_capture_path: Path | None = None

    @property
    def kv_backend(self) -> Literal['memory', 'redis']:
        return 'redis' if self.redis_url.strip() else 'memory'

    @property
    def storage_backend(self) -> Literal['local', 'oss']:
        fields = ('oss_region', 'oss_endpoint', 'oss_media_bucket', 'oss_evidence_bucket',
                  'oss_access_key_id', 'oss_access_key_secret')
        return 'oss' if any(getattr(self, field).strip() for field in fields) else 'local'

    @property
    def mail_backend(self) -> Literal['smtp', 'capture']:
        """Execution policy: SMTP normally, capture only in the validated runner sandbox."""
        return 'capture' if self.mail_capture_path is not None else 'smtp'

    @field_validator('database_schema')
    @classmethod
    def validate_schema(cls, value: str) -> str:
        return validate_schema_identifier(value)

    @field_validator('storage_key_prefix')
    @classmethod
    def validate_storage_prefix(cls, value: str) -> str:
        return validate_storage_key_prefix(value)

    @field_validator('redis_key_prefix')
    @classmethod
    def validate_redis_prefix(cls, value: str) -> str:
        if value and not re.fullmatch(r'[A-Za-z0-9_:-]+', value):
            raise ValueError('invalid Redis key prefix')
        return value

    @field_validator('oss_timeout_seconds', 'jwt_expire_days', 'file_url_expire_seconds', 'upload_lease_expire_seconds',
                     'comment_rate_limit_count', 'comment_rate_limit_seconds',
                     'trade_confirm_timeout_days', 'timeout_scan_interval_seconds',
                     'verification_code_ttl_seconds', 'verification_send_interval_seconds', 'smtp_timeout_seconds')
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('must be positive')
        return value

    @field_validator('oss_max_retries')
    @classmethod
    def validate_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError('must be non-negative')
        return value

    @field_validator('audit_trusted_proxies')
    @classmethod
    def validate_trusted_proxies(cls, value: str) -> str:
        if value.strip().lower() == 'none':
            return 'none'
        try:
            entries = value.split(',')
            if not all(entry.strip() for entry in entries):
                raise ValueError('empty proxy entry')
            for entry in entries:
                ipaddress.ip_network(entry.strip(), strict=False)
        except ValueError:
            raise ValueError('invalid trusted proxy list') from None
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == 'prod'

    def validate_for_runtime(self, env_file: Path | None = None, *, skip_smtp: bool = False) -> None:
        errors = []
        for field in ('database_url', 'jwt_secret', 'file_url_secret'):
            if not getattr(self, field).strip():
                errors.append(field.upper() + ' is required')
        for field in ('app_name', 'jwt_algorithm'):
            if not getattr(self, field).strip():
                errors.append(field.upper() + ' is required')
        for field in ('jwt_secret', 'file_url_secret'):
            if is_placeholder_secret(getattr(self, field)):
                errors.append(field.upper() + ' is missing or a placeholder')
        if self.mail_backend == 'smtp' and not skip_smtp:
            for field in ('smtp_host', 'smtp_username', 'smtp_password', 'smtp_from_email', 'smtp_from_name'):
                if is_placeholder_secret(getattr(self, field)) or any(c in getattr(self, field) for c in '\r\n'):
                    errors.append(field.upper() + ' is missing or a placeholder')
            address = self.smtp_from_email
            if parseaddr(address)[1] != address or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', address):
                errors.append('SMTP_FROM_EMAIL must be a valid email address')
            if not 1 <= self.smtp_port <= 65535:
                errors.append('SMTP_PORT must be between 1 and 65535')
        if self.mail_backend == 'capture':
            try:
                selected = env_file or resolve_env_file()
                capture = self.mail_capture_path
                root = PROJECT_ROOT / 'var'
                schema = self.database_schema
                if (self.environment not in {'dev', 'test'} or not re.fullmatch(r'acceptance_[0-9a-f]{32}', schema)
                    or capture is None or not capture.is_absolute() or capture.name != 'mailbox.jsonl'
                    or capture.parent.parent.resolve() != root.resolve()
                    or not capture.parent.name.startswith(schema + '-')
                    or capture.parent.is_symlink() or capture.is_symlink()
                    or selected.resolve().parent != capture.parent.resolve()):
                    raise ValueError()
                parent_stat = capture.parent.stat()
                if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) != 0o700:
                    raise ValueError()
                if capture.exists():
                    info = capture.stat()
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                        raise ValueError()
            except (OSError, ValueError):
                errors.append('MAIL_CAPTURE_PATH requires a private acceptance sandbox')
        if self.redis_key_prefix.strip() and not self.redis_url.strip():
            errors.append('REDIS_URL is required when REDIS_KEY_PREFIX is configured')
        if self.kv_backend == 'redis':
            if not self.redis_key_prefix.strip():
                errors.append('REDIS_KEY_PREFIX is required for redis')
            try:
                redis = urlsplit(self.redis_url)
                if redis.scheme not in {'redis', 'rediss'} or not redis.hostname:
                    errors.append('REDIS_URL must be a valid Redis URL')
            except ValueError:
                errors.append('REDIS_URL must be a valid Redis URL')
        if self.storage_backend == 'local' and self.storage_local_root is None:
            errors.append('STORAGE_LOCAL_ROOT is required for local storage')
        if self.storage_backend == 'oss':
            for field in ('oss_region', 'oss_endpoint', 'oss_media_bucket', 'oss_evidence_bucket', 'oss_access_key_id', 'oss_access_key_secret'):
                if not getattr(self, field).strip():
                    errors.append(field.upper() + ' is required for oss')
            for field in ('oss_region', 'oss_endpoint', 'oss_media_bucket', 'oss_evidence_bucket', 'oss_access_key_id', 'oss_access_key_secret'):
                if is_placeholder_secret(getattr(self, field)):
                    errors.append(field.upper() + ' is missing or a placeholder')
            try:
                endpoint = urlsplit(self.oss_endpoint)
                if endpoint.scheme.lower() != 'https' or not endpoint.hostname:
                    errors.append('OSS_ENDPOINT must be a valid https URL')
            except ValueError:
                errors.append('OSS_ENDPOINT must be a valid https URL')
            if self.oss_media_bucket and self.oss_media_bucket == self.oss_evidence_bucket:
                errors.append('OSS_MEDIA_BUCKET and OSS_EVIDENCE_BUCKET must differ')
        try:
            url = make_url(self.database_url)
            if url.drivername == 'postgresql+asyncpg':
                if not all((url.username, url.password, url.host, url.database)):
                    errors.append('DATABASE_URL requires user, password, host and database')
                elif any(is_placeholder_secret(part) for part in (url.username, url.password, url.host, url.database)):
                    errors.append('DATABASE_URL contains a placeholder')
            elif url.drivername == 'sqlite+aiosqlite':
                if not url.database:
                    errors.append('DATABASE_URL requires an explicit SQLite database')
            else:
                errors.append('DATABASE_URL has unsupported driver')
        except (ArgumentError, ValueError):
            errors.append('DATABASE_URL is not a valid database URL')
        path = env_file or resolve_env_file()
        if (path == PROD_ENV_FILE or path.name == '.env.prod') and self.environment != 'prod':
            errors.append('APP_ENV_FILE selects .env.prod but ENVIRONMENT is not prod')
        if self.environment == 'prod':
            if path != PROD_ENV_FILE:
                errors.append('prod requires APP_ENV_FILE=backend/.env.prod')
            errors.extend(self._production_errors())
        if errors:
            raise ConfigurationError('configuration rejected: ' + '; '.join(errors))

    def _production_errors(self) -> list[str]:
        errors = []
        if self.db_auto_create:
            errors.append('DB_AUTO_CREATE must be false in prod')
        if is_placeholder_secret(self.jwt_secret, min_length=32):
            errors.append('JWT_SECRET is a placeholder or shorter than 32 characters')
        if is_placeholder_secret(self.file_url_secret, min_length=32):
            errors.append('FILE_URL_SECRET is a placeholder or shorter than 32 characters')
        if self.storage_backend != 'oss':
            errors.append('OSS resource configuration is required in prod')
        for field in ('oss_access_key_id', 'oss_access_key_secret'):
            if is_placeholder_secret(getattr(self, field), min_length=8):
                errors.append(field.upper() + ' is missing or a placeholder')
        for field in ('oss_region', 'oss_endpoint', 'oss_media_bucket', 'oss_evidence_bucket'):
            if is_placeholder_secret(getattr(self, field)):
                errors.append(field.upper() + ' is missing or a placeholder')
        if not self.oss_endpoint.lower().startswith('https://'):
            errors.append('OSS_ENDPOINT must use https in prod')
        try:
            if _safe_url_info(self.database_url)[0] != 'postgresql+asyncpg':
                errors.append('DATABASE_URL must use postgresql+asyncpg in prod')
        except ConfigurationError:
            errors.append('DATABASE_URL is not a valid database URL')
        return errors

    def prepare_runtime_paths(self) -> None:
        if self.storage_backend == 'local':
            assert self.storage_local_root is not None
            self.storage_local_root.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith('sqlite'):
            database = make_url(self.database_url).database or ''
            if database and database != ':memory:':
                Path(database).parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = load_settings()
    settings.prepare_runtime_paths()
    return settings


def load_settings(env_file: str | Path | None = None, *, for_acceptance: bool = False) -> Settings:
    path = resolve_env_file(env_file)
    settings = _load_base_settings(Settings, path)
    if for_acceptance and (path != DEFAULT_ENV_FILE.resolve() or settings.environment not in {'dev', 'test'} or settings.mail_backend != 'smtp'):
        raise ConfigurationError('acceptance base configuration requires the default development environment')
    settings.validate_for_runtime(path, skip_smtp=for_acceptance)
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


class MigrationSettings(DotenvOnlySettings):
    environment: Literal['dev', 'test', 'prod']
    database_schema: str
    migration_database_url: str
    migration_owner_role: str
    migration_app_role: str = ''
    database_url: str

    @field_validator('database_schema')
    @classmethod
    def validate_schema(cls, value: str) -> str:
        return validate_schema_identifier(value)

    def validated(self) -> MigrationSettings:
        if not self.migration_database_url.strip() or not self.migration_owner_role.strip():
            raise ConfigurationError('MIGRATION_DATABASE_URL and MIGRATION_OWNER_ROLE are required')
        if not _IDENTIFIER.fullmatch(self.migration_owner_role):
            raise ConfigurationError('MIGRATION_OWNER_ROLE is not a valid role identifier')
        if _safe_url_info(self.migration_database_url)[0] != 'postgresql+asyncpg':
            raise ConfigurationError('MIGRATION_DATABASE_URL must use postgresql+asyncpg')
        return self

    @property
    def app_role(self) -> str:
        try:
            role = self.migration_app_role.strip() or make_url(self.database_url).username or ''
        except (ArgumentError, ValueError):
            role = ''
        if not _IDENTIFIER.fullmatch(role):
            raise ConfigurationError('cannot determine the application database role for migrations')
        return role


def load_migration_settings(env_file: str | Path | None = None) -> MigrationSettings:
    path = resolve_env_file(env_file)
    settings = _load_base_settings(MigrationSettings, path).validated()
    if (settings.environment == 'prod' and path != PROD_ENV_FILE) or (path.name == '.env.prod' and settings.environment != 'prod'):
        raise ConfigurationError('migration environment does not match selected environment file')
    return settings


def validate_migration_context(settings: MigrationSettings) -> None:
    settings.validated()
    try:
        app = make_url(settings.database_url)
        migration = make_url(settings.migration_database_url)
    except (ArgumentError, ValueError):
        raise ConfigurationError('invalid database configuration for migration') from None
    errors = []
    if app.drivername != 'postgresql+asyncpg' or migration.drivername != 'postgresql+asyncpg':
        errors.append('database URLs must use postgresql+asyncpg')
    if not all((app.host, app.database, app.username, app.password, migration.host, migration.database, migration.username, migration.password)):
        errors.append('database URLs require host, database, username and password')
    if any(is_placeholder_secret(part) for part in (app.username, app.password, app.host, app.database,
                                                       migration.username, migration.password, migration.host,
                                                       migration.database, settings.migration_owner_role)):
        errors.append('migration configuration contains a placeholder')
    if (app.host, app.port or 5432, app.database) != (migration.host, migration.port or 5432, migration.database):
        errors.append('DATABASE_URL and MIGRATION_DATABASE_URL must target the same database')
    role = settings.app_role
    if role != app.username:
        errors.append('MIGRATION_APP_ROLE must match the application URL role')
    if len({role, migration.username, settings.migration_owner_role}) != 3:
        errors.append('application, migration and owner roles must differ')
    if errors:
        raise ConfigurationError('migration refused: ' + '; '.join(errors))


def require_test_management_context(settings: Settings, *, command: str) -> None:
    if settings.environment not in {'dev', 'test'} or resolve_env_file() != DEFAULT_ENV_FILE:
        raise ConfigurationError(f'{command} refused: requires the development environment file')

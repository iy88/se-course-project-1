"""Load runtime configuration exclusively from the selected dotenv file."""

from __future__ import annotations

import ipaddress
import math
import os
import re
from email.utils import parseaddr
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from dotenv import dotenv_values
from dotenv.parser import parse_stream
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.private_files import require_private

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


def parse_release_id(text: str) -> str:
    for line in text.splitlines():
        key, _, value = line.partition('=')
        if key.strip() == 'release_id':
            candidate = value.strip()
            if re.fullmatch(r'[0-9a-f]{40}-[0-9]+', candidate):
                return candidate
            return 'invalid'
    return 'invalid'


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
    # Runtime roles share the same business configuration.
    app_role: Literal['api', 'ws', 'worker', 'scheduler'] = 'api'
    api_host: str = Field(default='127.0.0.1', min_length=1)
    api_port: int = Field(default=8000, ge=1, le=65535)
    ws_host: str = Field(default='127.0.0.1', min_length=1)
    ws_port: int = Field(default=8002, ge=1, le=65535)
    api_workers: int = 1
    ws_workers: int = 1
    environment: Literal['dev', 'test', 'prod']
    database_url: str
    db_auto_create: bool
    database_schema: str
    audit_trusted_proxies: str
    redis_url: str = ''
    redis_key_prefix: str = ''

    # SQL pool/timeout budget, expressed per process role. Inherited environment
    # variables never override these values; only the selected dotenv does.
    api_db_pool_size: int = 8
    api_db_max_overflow: int = 0
    ws_db_pool_size: int = 2
    ws_db_max_overflow: int = 0
    jobs_db_pool_size: int = 4
    jobs_db_max_overflow: int = 0
    db_pool_timeout_seconds: float = 1.0
    db_pre_ping: bool = True
    db_recycle_seconds: int = 1800
    db_lock_timeout_ms: int = 500
    db_statement_timeout_ms: int = 2000
    db_idle_in_transaction_timeout_ms: int = 10000
    db_connection_budget: int = 0  # 0 disables the configured-budget check

    # Redis control pool and stream reader are separate budgets. Blocking XREAD
    # must not consume the ticket/verification/counter connections.
    redis_control_max_connections_api: int = 16
    redis_control_max_connections_ws: int = 8
    redis_control_max_connections_jobs: int = 8
    redis_connection_budget: int = 0
    redis_connect_timeout_seconds: float = 1.0
    redis_socket_timeout_seconds: float = 2.0
    # Bounded acquisition for control/publish pools. The dedicated XREAD
    # connection has its own pool and never shares these slots.
    redis_control_pool_timeout_seconds: float = 1.0
    redis_publish_max_connections: int = 2
    redis_publish_pool_timeout_seconds: float = 1.0
    redis_reader_pool_timeout_seconds: float = 1.0
    redis_stream_block_ms: int = 5000
    redis_stream_socket_timeout_seconds: float = 10.0

    # Durable realtime delivery. The Redis stream is an accelerator only; the
    # PostgreSQL event table is the source of truth for replay and compensation.
    realtime_protocol_version: int = 2
    realtime_stream_name: str = 'realtime:v1:events'
    realtime_stream_maxlen: int = 50000
    realtime_payload_max_bytes: int = 16384
    realtime_event_retention_hours: int = 72
    realtime_replay_batch_size: int = 200
    realtime_replay_max_events: int = 5000
    realtime_pending_degraded_threshold: int = 10000
    realtime_admission_enabled: bool = True
    # Soft admission budget. The cache window and in-flight transactions mean
    # this is not an exact global hard cap; keep deployment headroom above it.
    realtime_outbox_max_pending: int = 20000
    realtime_outbox_max_age_seconds: int = 3600
    realtime_outbox_admission_cache_seconds: float = 1.0  # 0 = always query
    realtime_outbox_retry_after_seconds: int = 30
    outbox_batch_size: int = 100
    # The periodic Taskiq sweep and the retry middleware own retry timing.
    # ``next_retry_at`` remains a schema/manual-recovery field and is no longer
    # consulted by claim; this interval is the bounded re-scan backstop.
    outbox_poll_interval_ms: int = 1000
    outbox_lease_seconds: int = 30
    outbox_max_attempts: int = 8
    outbox_max_batches_per_run: int = 5
    outbox_run_time_budget_seconds: float = 10.0
    retention_batch_limit: int = 2000
    idempotency_ttl_hours: int = 24
    idempotency_cleanup_batch_size: int = 1000

    # Background jobs use the official Taskiq RedisStreamBroker. The task
    # stream/group is deliberately separate from the realtime broadcast stream:
    # WS gateways keep independent XREAD cursors, while only task workers join
    # this consumer group.
    taskiq_queue_name: str = 'jobs:v1:taskiq'
    taskiq_consumer_group: str = 'jobs:v1:workers'
    taskiq_retry_prefix: str = 'jobs:v1:retry'
    taskiq_worker_processes: int = 2
    taskiq_max_async_tasks: int = 16
    taskiq_max_prefetch: int = 8
    taskiq_broker_max_connections: int = 4
    taskiq_schedule_max_connections: int = 2
    taskiq_heartbeat_max_connections: int = 1
    taskiq_xread_block_ms: int = 5000
    taskiq_xread_count: int = 8
    taskiq_reclaim_idle_ms: int = 300000
    taskiq_unacknowledged_batch_size: int = 8
    taskiq_unacknowledged_lock_timeout_seconds: float = 30.0
    taskiq_retry_max_retries: int = 3
    taskiq_retry_delay_seconds: float = 2.0
    taskiq_retry_max_delay_seconds: int = 60
    taskiq_retry_jitter: bool = True
    taskiq_retry_exponent: bool = True
    taskiq_shutdown_timeout_seconds: int = 20
    taskiq_task_timeout_seconds: float = 60.0
    taskiq_outbox_interval_seconds: int = 1
    taskiq_retention_interval_seconds: int = 300
    taskiq_idempotency_cleanup_interval_seconds: int = 900
    taskiq_scheduler_update_interval_seconds: int = 5
    taskiq_scheduler_loop_interval_seconds: int = 1
    taskiq_scheduler_send_timeout_seconds: float = 10.0
    taskiq_scheduler_heartbeat_ttl_seconds: int = 30
    taskiq_probe_timeout_seconds: float = 20.0
    taskiq_probe_ttl_seconds: int = 120
    # Test/integration may append modules; production keeps only app.jobs.tasks.
    taskiq_extra_task_modules: str = ''

    ws_ticket_ttl_seconds: int = 30
    allow_query_token: bool = False
    allowed_origins: str = ''
    allow_missing_origin: bool = False
    ws_heartbeat_seconds: int = 20
    ws_heartbeat_timeout_seconds: int = 60
    ws_send_timeout_seconds: float = 5.0
    ws_queue_max_messages: int = 128
    ws_queue_max_bytes: int = 524288
    ws_max_frame_bytes: int = 32768
    ws_max_connections_per_user: int = 5
    ws_max_connections_per_ip: int = 50
    ws_handshake_rate_limit: int = 30
    ws_handshake_rate_window_seconds: int = 60
    ws_reconcile_seconds: int = 1
    graceful_shutdown_seconds: int = 20
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
    def db_pool(self) -> tuple[int, int]:
        if self.app_role == 'scheduler':
            # The scheduler uses Redis only (schedule source + heartbeat); it
            # must not pretend to own a SQL pool it never creates.
            return (0, 0)
        return {
            'api': (self.api_db_pool_size, self.api_db_max_overflow),
            'ws': (self.ws_db_pool_size, self.ws_db_max_overflow),
            'worker': (self.jobs_db_pool_size, self.jobs_db_max_overflow),
        }[self.app_role]

    @property
    def redis_control_limit(self) -> int:
        if self.app_role == 'scheduler':
            return 1  # readiness CLI control probe; zero means unbounded in redis-py
        return {
            'api': self.redis_control_max_connections_api,
            'ws': self.redis_control_max_connections_ws,
            'worker': self.redis_control_max_connections_jobs,
        }[self.app_role]

    @property
    def ws_effective_queue_capacity(self) -> int:
        """Conservative message-slot bound for one AnyIO stream.

        Any legal frame is at most ``WS_MAX_FRAME_BYTES``. Limiting the number
        of buffered frames to ``WS_QUEUE_MAX_BYTES // WS_MAX_FRAME_BYTES``
        therefore guarantees the byte budget without a custom weighted queue.
        The writer may additionally hold one dequeued frame while it awaits the
        socket; that +1 in-flight frame is the documented memory margin.
        """
        by_bytes = self.ws_queue_max_bytes // self.ws_max_frame_bytes
        return max(1, min(self.ws_queue_max_messages, by_bytes))

    @property
    def taskiq_modules(self) -> list[str]:
        modules = ['app.jobs.tasks']
        modules.extend(part.strip() for part in self.taskiq_extra_task_modules.split(',') if part.strip())
        return modules

    @property
    def origin_allowlist(self) -> frozenset[str]:
        return frozenset(part.strip().rstrip('/') for part in self.allowed_origins.split(',') if part.strip())

    @property
    def release_id(self) -> str:
        """Deployment metadata parsed from release.txt, never inherited env."""
        for candidate in (PROJECT_ROOT / 'release.txt', BACKEND_ROOT.parent / 'release.txt'):
            try:
                text = candidate.read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                continue
            return parse_release_id(text)
        return 'dev'

    def sql_connection_budget(self) -> int:
        """Configured steady-state SQL connections for this role/machine."""
        if self.app_role == 'api':
            return (self.api_db_pool_size + self.api_db_max_overflow) * max(self.api_workers, 1)
        if self.app_role == 'ws':
            return (self.ws_db_pool_size + self.ws_db_max_overflow) * max(self.ws_workers, 1)
        if self.app_role == 'worker':
            # Each Taskiq worker process creates its own engine; never share a
            # pool across fork/loop boundaries.
            return (self.jobs_db_pool_size + self.jobs_db_max_overflow) * max(self.taskiq_worker_processes, 1)
        if self.app_role == 'scheduler':
            return 0
        return self.jobs_db_pool_size + self.jobs_db_max_overflow

    def split_sql_budget(self) -> int:
        return ((self.api_db_pool_size + self.api_db_max_overflow) * max(self.api_workers, 1) +
                (self.ws_db_pool_size + self.ws_db_max_overflow) * max(self.ws_workers, 1) +
                (self.jobs_db_pool_size + self.jobs_db_max_overflow) * max(self.taskiq_worker_processes, 1))

    def _worker_redis_budget(self) -> int:
        return max(self.taskiq_worker_processes, 1) * (
            self.redis_control_max_connections_jobs
            + self.redis_publish_max_connections
            + self.taskiq_broker_max_connections
            + self.taskiq_schedule_max_connections
            # Probe outcomes and terminal-failure records each use at most
            # one short-lived connection per concurrently executing task.
            + self.taskiq_max_async_tasks
        )

    def _scheduler_redis_budget(self) -> int:
        return (self.taskiq_broker_max_connections +
                self.taskiq_schedule_max_connections +
                self.taskiq_heartbeat_max_connections + 1)

    def redis_connection_budget_all(self) -> int:
        return (self.redis_control_max_connections_api * max(self.api_workers, 1) +
                (self.redis_control_max_connections_ws + 1) * max(self.ws_workers, 1) +
                self._worker_redis_budget() + self._scheduler_redis_budget())

    def redis_connection_budget_total(self) -> int:
        # Count every process-owned pool, not only the control pool: the
        # dispatcher writer pool, each WS blocking reader, every Taskiq broker
        # and retry-schedule pool and the scheduler heartbeat connection all
        # count against Redis maxclients.
        api = self.redis_control_max_connections_api * max(self.api_workers, 1)
        ws = (self.redis_control_max_connections_ws + 1) * max(self.ws_workers, 1)
        if self.app_role == 'api':
            return api
        if self.app_role == 'ws':
            return ws
        if self.app_role == 'worker':
            return self._worker_redis_budget()
        if self.app_role == 'scheduler':
            return self._scheduler_redis_budget()
        return api + ws + self._worker_redis_budget() + self._scheduler_redis_budget()

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
                     'verification_code_ttl_seconds', 'verification_send_interval_seconds', 'smtp_timeout_seconds',
                     'api_workers', 'ws_workers', 'api_db_pool_size', 'ws_db_pool_size', 'jobs_db_pool_size',
                     'db_recycle_seconds', 'db_lock_timeout_ms', 'db_statement_timeout_ms',
                     'db_idle_in_transaction_timeout_ms',
                     'redis_control_max_connections_api', 'redis_control_max_connections_ws',
                     'redis_control_max_connections_jobs',
                     'redis_publish_max_connections', 'redis_stream_block_ms',
                     'realtime_protocol_version', 'realtime_stream_maxlen', 'realtime_payload_max_bytes',
                     'realtime_event_retention_hours', 'realtime_replay_batch_size', 'realtime_replay_max_events',
                     'realtime_pending_degraded_threshold', 'realtime_outbox_max_pending',
                     'realtime_outbox_max_age_seconds', 'realtime_outbox_retry_after_seconds',
                     'outbox_batch_size', 'outbox_poll_interval_ms', 'outbox_lease_seconds',
                     'outbox_max_attempts', 'outbox_max_batches_per_run',
                     'retention_batch_limit', 'idempotency_ttl_hours', 'idempotency_cleanup_batch_size',
                     'taskiq_worker_processes', 'taskiq_max_async_tasks', 'taskiq_max_prefetch',
                     'taskiq_broker_max_connections', 'taskiq_schedule_max_connections',
                     'taskiq_heartbeat_max_connections', 'taskiq_xread_block_ms', 'taskiq_xread_count',
                     'taskiq_reclaim_idle_ms', 'taskiq_unacknowledged_batch_size',
                     'taskiq_retry_max_retries', 'taskiq_retry_max_delay_seconds',
                     'taskiq_shutdown_timeout_seconds', 'taskiq_outbox_interval_seconds',
                     'taskiq_retention_interval_seconds', 'taskiq_idempotency_cleanup_interval_seconds',
                     'taskiq_scheduler_update_interval_seconds', 'taskiq_scheduler_loop_interval_seconds',
                     'taskiq_scheduler_heartbeat_ttl_seconds', 'taskiq_probe_ttl_seconds',
                     'ws_ticket_ttl_seconds', 'ws_heartbeat_seconds', 'ws_heartbeat_timeout_seconds',
                     'ws_queue_max_messages', 'ws_queue_max_bytes', 'ws_max_frame_bytes',
                     'ws_max_connections_per_user', 'ws_max_connections_per_ip',
                     'ws_handshake_rate_limit', 'ws_handshake_rate_window_seconds',
                     'ws_reconcile_seconds', 'graceful_shutdown_seconds')
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('must be positive')
        return value

    @field_validator('db_pool_timeout_seconds', 'redis_connect_timeout_seconds', 'redis_socket_timeout_seconds',
                     'redis_control_pool_timeout_seconds', 'redis_publish_pool_timeout_seconds',
                     'redis_reader_pool_timeout_seconds', 'redis_stream_socket_timeout_seconds',
                     'ws_send_timeout_seconds', 'outbox_run_time_budget_seconds',
                     'taskiq_unacknowledged_lock_timeout_seconds', 'taskiq_retry_delay_seconds',
                     'taskiq_task_timeout_seconds', 'taskiq_scheduler_send_timeout_seconds',
                     'taskiq_probe_timeout_seconds')
    @classmethod
    def validate_positive_float(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError('must be a finite positive number')
        return value

    @field_validator('api_db_max_overflow', 'ws_db_max_overflow', 'jobs_db_max_overflow',
                     'db_connection_budget', 'redis_connection_budget')
    @classmethod
    def validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError('must be non-negative')
        return value

    @field_validator('realtime_outbox_admission_cache_seconds')
    @classmethod
    def validate_non_negative_float(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError('must be a finite non-negative number')
        return value

    @field_validator('realtime_outbox_max_pending', 'realtime_outbox_max_age_seconds', 'realtime_outbox_retry_after_seconds')
    @classmethod
    def validate_outbox_budget(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('must be positive')
        return value

    @field_validator('allowed_origins')
    @classmethod
    def validate_allowed_origins(cls, value: str) -> str:
        parts = [part.strip().rstrip('/') for part in value.split(',') if part.strip()]
        for part in parts:
            parsed = urlsplit(part)
            if part == '*' or parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.path not in {'', '/'}:
                raise ValueError('ALLOWED_ORIGINS must be explicit http(s) origins')
        return ','.join(parts)

    @field_validator('realtime_stream_name')
    @classmethod
    def validate_stream_name(cls, value: str) -> str:
        if not re.fullmatch(r'[A-Za-z0-9:._-]{1,128}', value):
            raise ValueError('invalid realtime stream name')
        return value

    @field_validator('taskiq_queue_name', 'taskiq_consumer_group', 'taskiq_retry_prefix')
    @classmethod
    def validate_taskiq_names(cls, value: str) -> str:
        if not re.fullmatch(r'[A-Za-z0-9:._-]{1,128}', value):
            raise ValueError('invalid Taskiq Redis namespace')
        return value

    @field_validator('taskiq_extra_task_modules')
    @classmethod
    def validate_taskiq_modules(cls, value: str) -> str:
        modules = [part.strip() for part in value.split(',') if part.strip()]
        for module in modules:
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', module):
                raise ValueError('invalid Taskiq task module')
        return ','.join(modules)


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

    def validate_for_runtime(self, env_file: Path | None = None, *, skip_smtp: bool = False, require_shared_redis: bool = True) -> None:
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
                require_private(capture.parent, directory=True)
                if capture.exists():
                    require_private(capture)
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
                else:
                    # redis-py lets URL query parameters override explicit
                    # budget/timeout/retry kwargs. Reject those conflicts so the
                    # dotenv budget is authoritative; TLS parameters stay usable.
                    forbidden = {
                        'max_connections', 'timeout', 'socket_timeout', 'socket_connect_timeout',
                        'retry', 'retry_on_timeout', 'health_check_interval', 'decode_responses',
                        'connection_pool_class', 'protocol',
                    }
                    conflicts = sorted({key.lower() for key, _ in parse_qsl(redis.query)} & forbidden)
                    if conflicts:
                        errors.append('REDIS_URL query overrides explicit budget parameters: ' + ', '.join(conflicts))
            except ValueError:
                errors.append('REDIS_URL must be a valid Redis URL')
        # Shared state is mandatory whenever more than one process owns
        # realtime delivery. Silently falling back to per-process memory would
        # make tickets, rate limits and connection limits unreliable.
        if (self.is_production or require_shared_redis) and self.kv_backend != 'redis':
            errors.append('shared REDIS_URL/REDIS_KEY_PREFIX is required for production or split roles')
        if self.is_production:
            if not self.origin_allowlist:
                errors.append('ALLOWED_ORIGINS is required in prod')
            if self.allow_query_token:
                errors.append('ALLOW_QUERY_TOKEN must be false in prod')
        if self.db_connection_budget:
            budget = self.split_sql_budget()
            if budget > self.db_connection_budget:
                errors.append(f'SQL connection budget exceeded: {budget} > {self.db_connection_budget}')
        redis_budget = self.redis_connection_budget_all()
        if self.redis_connection_budget and redis_budget > self.redis_connection_budget:
            errors.append(f'Redis connection budget exceeded: {redis_budget} > {self.redis_connection_budget}')
        if self.ws_heartbeat_timeout_seconds <= self.ws_heartbeat_seconds:
            errors.append('WS_HEARTBEAT_TIMEOUT_SECONDS must exceed WS_HEARTBEAT_SECONDS')
        if self.realtime_outbox_max_pending < self.realtime_pending_degraded_threshold:
            errors.append('REALTIME_OUTBOX_MAX_PENDING must be >= REALTIME_PENDING_DEGRADED_THRESHOLD')
        if self.redis_stream_socket_timeout_seconds * 1000 <= self.redis_stream_block_ms:
            errors.append('REDIS_STREAM_SOCKET_TIMEOUT_SECONDS must exceed the XREAD block')
        if self.ws_max_frame_bytes <= self.realtime_payload_max_bytes:
            errors.append('WS_MAX_FRAME_BYTES must exceed REALTIME_PAYLOAD_MAX_BYTES to include the envelope')
        if self.ws_queue_max_bytes < self.ws_max_frame_bytes:
            errors.append('WS_QUEUE_MAX_BYTES must be at least WS_MAX_FRAME_BYTES (one frame slot)')
        if self.outbox_max_attempts < self.taskiq_retry_max_retries + 1:
            errors.append('OUTBOX_MAX_ATTEMPTS must be at least TASKIQ_RETRY_MAX_RETRIES + 1')
        if self.taskiq_retry_max_delay_seconds < self.taskiq_retry_delay_seconds:
            errors.append('TASKIQ_RETRY_MAX_DELAY_SECONDS must be >= TASKIQ_RETRY_DELAY_SECONDS')
        if self.taskiq_scheduler_heartbeat_ttl_seconds <= self.taskiq_scheduler_update_interval_seconds:
            errors.append('TASKIQ_SCHEDULER_HEARTBEAT_TTL_SECONDS must exceed the schedule update interval')
        if self.environment != 'test':
            if self.taskiq_task_timeout_seconds <= self.taskiq_xread_block_ms / 1000.0:
                errors.append('TASKIQ_TASK_TIMEOUT_SECONDS must exceed the broker XREAD block budget')
            if self.taskiq_max_prefetch > self.taskiq_max_async_tasks:
                errors.append('TASKIQ_MAX_PREFETCH must not exceed TASKIQ_MAX_ASYNC_TASKS')
        # XREAD/XAUTOCLAIM deliver whole batches into the pending list before
        # execution slots are available. Do not steal still-running/prefetched
        # tasks merely because their timeout equals the claim idle threshold.
        # Fault-injection tests deliberately use tiny idle thresholds.
        claim_budget_ms = 1000 * self.taskiq_task_timeout_seconds * (
            1 + math.ceil((self.taskiq_xread_count + self.taskiq_unacknowledged_batch_size
                           + self.taskiq_max_prefetch) / self.taskiq_max_async_tasks)
        )
        if self.environment != 'test' and self.taskiq_reclaim_idle_ms <= claim_budget_ms:
            errors.append('TASKIQ_RECLAIM_IDLE_MS must exceed the task timeout and prefetched batch execution budget')
        # Split roles in dev/test still need explicit origins for the WS role;
        # localhost-only defaults are not guessed here.
        if (not self.is_production and self.app_role == 'ws'
                and not self.origin_allowlist and not self.allow_missing_origin):
            errors.append('ALLOWED_ORIGINS or ALLOW_MISSING_ORIGIN is required for the ws role')
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


_ROLE_OVERRIDE: str | None = None


def set_runtime_role(role: str | None) -> None:
    """Select a process role without changing business configuration.

    ``APP_RUNTIME_ROLE`` (or the CLI) is the runtime selector, analogous to
    ``APP_ENV_FILE``: it lets all split systemd units share one dotenv while the
    business values still come only from the selected file.
    """
    global _ROLE_OVERRIDE
    if role is not None and role not in {'api', 'ws', 'worker', 'scheduler'}:
        raise ConfigurationError('invalid runtime role')
    _ROLE_OVERRIDE = role
    get_settings.cache_clear()


def load_settings(env_file: str | Path | None = None, *, for_acceptance: bool = False) -> Settings:
    path = resolve_env_file(env_file)
    settings = _load_base_settings(Settings, path)
    selected_role = _ROLE_OVERRIDE or os.environ.get('APP_RUNTIME_ROLE', '').strip()
    effective_role = selected_role or settings.app_role
    if effective_role not in {'api', 'ws', 'worker', 'scheduler'}:
        raise ConfigurationError('invalid runtime role')
    if effective_role != settings.app_role:
        settings = settings.model_copy(update={'app_role': effective_role})
    if for_acceptance and (path != DEFAULT_ENV_FILE.resolve() or settings.environment not in {'dev', 'test'} or settings.mail_backend != 'smtp'):
        raise ConfigurationError('acceptance base configuration requires the default development environment')
    settings.validate_for_runtime(path, skip_smtp=for_acceptance, require_shared_redis=bool(selected_role))
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

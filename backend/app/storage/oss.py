"""阿里云 OSS 私有双桶实现。

- 使用 OSS Python SDK V2 + HTTPS endpoint + region；
- report → evidence bucket，product/avatar/chat → media bucket，未知 namespace 拒绝；
- 同步 SDK 操作保持同步合约，由路由层放入线程池；
- 每次网络调用有超时和有限重试，明确区分 404/403/连接失败，不静默回退 local；
- 读取流使用上下文管理器及时关闭。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
import traceback
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.config import validate_storage_key_prefix
from app.core.private_files import exclusive_lock, require_private
from app.storage.base import (
    StorageAlreadyExists,
    StorageBackend,
    StorageConfigError,
    StorageError,
    StorageInvalidKey,
    StorageNotFound,
    StoragePermissionDenied,
    StorageUnavailable,
    bucket_role_for_namespace,
    content_type_for_key,
    make_key,
    namespace_for_key,
)

logger = logging.getLogger(__name__)

BucketFactory = Callable[["OssConfig", str], Any]

_RETRYABLE_STATUS = {0, 408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class OssConfig:
    region: str
    endpoint: str
    media_bucket: str
    evidence_bucket: str
    access_key_id: str = field(repr=False)
    access_key_secret: str = field(repr=False)
    timeout_seconds: float = 15.0
    max_retries: int = 2
    download_expire_seconds: int = 3600
    key_prefix: str = ""
    operation_journal: Path | None = None

    def __post_init__(self) -> None:
        try:
            prefix = validate_storage_key_prefix(self.key_prefix)
        except ValueError as exc:
            raise StorageConfigError("配置项格式错误：STORAGE_KEY_PREFIX") from exc
        object.__setattr__(self, "key_prefix", prefix)
        if self.operation_journal is not None:
            if not re.fullmatch(r"acceptance_[A-Za-z0-9_-]+/", prefix):
                raise StorageConfigError("对象日志仅允许独立的 acceptance 前缀")
            object.__setattr__(self, "operation_journal", Path(self.operation_journal))

    @classmethod
    def from_settings(cls, settings: Any) -> OssConfig:
        def required(name: str) -> str:
            value = getattr(settings, name, None)
            if value is None or not str(value).strip():
                raise StorageConfigError(f"缺少配置项：{name.upper()}")
            return str(value).strip()

        endpoint = required("oss_endpoint").rstrip("/")
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise StorageConfigError("OSS_ENDPOINT 必须是 HTTPS 地址")

        region = required("oss_region")
        media_bucket = required("oss_media_bucket")
        evidence_bucket = required("oss_evidence_bucket")
        if media_bucket == evidence_bucket:
            raise StorageConfigError("OSS_MEDIA_BUCKET 与 OSS_EVIDENCE_BUCKET 不能相同")
        for label, bucket_name in (
            ("OSS_MEDIA_BUCKET", media_bucket),
            ("OSS_EVIDENCE_BUCKET", evidence_bucket),
        ):
            if any(ch.isspace() for ch in bucket_name) or "/" in bucket_name:
                raise StorageConfigError(f"配置项格式错误：{label}")

        raw_timeout = getattr(settings, "oss_timeout_seconds", 15.0)
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise StorageConfigError("配置项格式错误：OSS_TIMEOUT_SECONDS") from exc
        if not 0 < timeout <= 300:
            raise StorageConfigError("OSS_TIMEOUT_SECONDS 必须在 0–300 秒之间")

        raw_retries = getattr(settings, "oss_max_retries", 2)
        try:
            retries = int(raw_retries)
        except (TypeError, ValueError) as exc:
            raise StorageConfigError("配置项格式错误：OSS_MAX_RETRIES") from exc
        if not 0 <= retries <= 10:
            raise StorageConfigError("OSS_MAX_RETRIES 必须在 0–10 之间")

        return cls(
            region=region,
            endpoint=endpoint,
            media_bucket=media_bucket,
            evidence_bucket=evidence_bucket,
            access_key_id=required("oss_access_key_id"),
            access_key_secret=required("oss_access_key_secret"),
            timeout_seconds=timeout,
            max_retries=retries,
            key_prefix=getattr(settings, "storage_key_prefix", ""),
            operation_journal=getattr(settings, "storage_operation_journal", None),
            download_expire_seconds=getattr(settings, "file_url_expire_seconds", 3600),
        )


def _close_result(result: Any) -> None:
    """释放 HEAD/PUT/DELETE 等非流式 SDK 响应连接；GET 由上下文管理器关闭。"""
    response = getattr(getattr(result, "resp", None), "response", None)
    close = getattr(response, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


class _V2Bucket:
    """Small bucket-scoped adapter around the official V2 client."""

    def __init__(self, client: Any, name: str) -> None:
        self.client, self.name = client, name

    def put_object(self, key: str, content: bytes, headers: dict[str, str]) -> Any:
        import alibabacloud_oss_v2 as oss
        return self.client.put_object(oss.PutObjectRequest(bucket=self.name, key=key, body=content, content_type=headers["Content-Type"], forbid_overwrite=headers.get("x-oss-forbid-overwrite") == "true"))

    def get_object(self, key: str) -> Any:
        import alibabacloud_oss_v2 as oss
        return self.client.get_object(oss.GetObjectRequest(bucket=self.name, key=key))

    def head_object(self, key: str) -> Any:
        import alibabacloud_oss_v2 as oss
        return self.client.head_object(oss.HeadObjectRequest(bucket=self.name, key=key))

    def delete_object(self, key: str) -> Any:
        import alibabacloud_oss_v2 as oss
        return self.client.delete_object(oss.DeleteObjectRequest(bucket=self.name, key=key))

    def presign_get(self, key: str, expires_seconds: int) -> Any:
        import alibabacloud_oss_v2 as oss
        request = oss.GetObjectRequest(bucket=self.name, key=key,
            response_cache_control=f'private, max-age={min(300, max(0, expires_seconds - 30))}')
        return self.client.presign(request, expires=timedelta(seconds=expires_seconds))

    def presign(self, key: str, content_type: str, size_bytes: int, expires_seconds: int, sha256: str) -> Any:
        import alibabacloud_oss_v2 as oss
        request = oss.PutObjectRequest(bucket=self.name, key=key, content_type=content_type,
                                       content_length=size_bytes, forbid_overwrite=True,
                                       metadata={"sha256": sha256})
        return self.client.presign(request, expires=timedelta(seconds=expires_seconds))


def _create_bucket(config: OssConfig, bucket_name: str) -> Any:
    try:
        import alibabacloud_oss_v2 as oss
        import requests
        from alibabacloud_oss_v2.transport import RequestsHttpClient
        session = requests.Session()
        session.trust_env = False
        transport = RequestsHttpClient(session=session, connect_timeout=config.timeout_seconds,
                                       readwrite_timeout=config.timeout_seconds)
        sdk_config = oss.config.Config(
            region=config.region, endpoint=config.endpoint, signature_version="v4",
            credentials_provider=oss.credentials.StaticCredentialsProvider(config.access_key_id, config.access_key_secret),
            http_client=transport, retry_max_attempts=1,
            connect_timeout=config.timeout_seconds, readwrite_timeout=config.timeout_seconds,
            additional_headers=["content-length"],
        )
        return _V2Bucket(oss.Client(sdk_config), bucket_name)
    except Exception as exc:
        raise StorageConfigError("OSS 客户端初始化失败") from exc


def _unwrap(exc: Exception) -> Exception:
    unwrap = getattr(exc, "unwrap", None)
    if callable(unwrap):
        inner = unwrap()
        if isinstance(inner, Exception):
            return inner
    return exc


def _error_details(exc: Exception) -> dict[str, Any]:
    """Inspect SDK/requests/urllib3 causes without logging messages or request data."""
    pending = [exc]
    seen: set[int] = set()
    chain = []
    details: dict[str, Any] = {}
    while pending and len(chain) < 12:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        entry: dict[str, Any] = {'type': type(current).__name__}
        number = getattr(current, 'errno', None)
        if isinstance(number, int):
            entry['errno'] = number
        frames = traceback.extract_tb(current.__traceback__)
        if frames:
            entry['frames'] = [f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in frames[-5:]]
        chain.append(entry)
        for name in ('status_code', 'status', 'code', 'request_id', 'ec'):
            value = getattr(current, name, None)
            if isinstance(value, int) and name in {'status_code', 'status'}:
                details.setdefault('status', value)
            elif isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value):
                details.setdefault(name, value)
        unwrap = getattr(current, 'unwrap', None)
        nested = [current.__cause__, current.__context__, getattr(current, 'reason', None)]
        if callable(unwrap):
            nested.append(unwrap())
        nested.extend(arg for arg in current.args if isinstance(arg, Exception))
        pending.extend(item for item in nested if isinstance(item, Exception))
    details['causes'] = chain
    return details


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, StorageError):
        return False
    exc = _unwrap(exc)
    status = getattr(exc, "status_code", getattr(exc, "status", None))
    if isinstance(status, int):
        return status in _RETRYABLE_STATUS or status >= 500
    try:
        from alibabacloud_oss_v2.exceptions import RequestError, ResponseError
        if isinstance(exc, (RequestError, ResponseError)):
            return True
    except ImportError:
        pass
    from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout
    return isinstance(exc, (ConnectionError, TimeoutError, RequestsConnectionError, Timeout))


def _translate_error(exc: Exception) -> StorageError:
    """把 SDK 异常转换为稳定的存储错误，不携带 endpoint/bucket/AK。"""
    if isinstance(exc, StorageError):
        return exc

    exc = _unwrap(exc)
    status = getattr(exc, "status_code", getattr(exc, "status", None))
    code = str(getattr(exc, "code", "") or "")

    if "FileAlreadyExists" in code or "ObjectAlreadyExists" in code:
        return StorageAlreadyExists("文件已存在，不能覆盖")
    if "NoSuchBucket" in code:
        return StorageConfigError("文件存储配置异常")
    if "NoSuchKey" in code or "NotFound" in code or status == 404:
        return StorageNotFound("文件不存在")
    if "AccessDenied" in code or "SignatureDoesNotMatch" in code or status == 403:
        return StoragePermissionDenied("文件存储权限配置异常")
    if "InvalidObjectName" in code or "InvalidArgument" in code:
        return StorageInvalidKey("非法文件 key")
    if isinstance(status, int) and status == 0:
        return StorageUnavailable("文件存储连接失败")
    if isinstance(status, int) and (status >= 500 or status in {408, 429}):
        return StorageUnavailable("文件存储暂不可用")
    return StorageUnavailable("文件存储暂不可用")


class OssStorage(StorageBackend):
    def __init__(
        self, config: OssConfig, bucket_factory: BucketFactory | None = None
    ) -> None:
        self.config = config
        self._bucket_factory = bucket_factory or _create_bucket
        self._buckets: dict[str, Any] = {}
        self._download_urls: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def _bucket_for_role(self, role: str) -> Any:
        bucket_name = (
            self.config.media_bucket if role == "media" else self.config.evidence_bucket
        )
        bucket = self._buckets.get(bucket_name)
        if bucket is None:
            try:
                bucket = self._bucket_factory(self.config, bucket_name)
            except StorageError:
                raise
            except Exception as exc:
                raise StorageConfigError("OSS 客户端初始化失败") from exc
            self._buckets[bucket_name] = bucket
        return bucket

    def _bucket_for_key(self, key: str) -> Any:
        namespace = namespace_for_key(key)
        return self._bucket_for_role(bucket_role_for_namespace(namespace))

    def _run(self, operation: str, func: Callable[[], Any], *, missing_ok: bool = False) -> Any:
        attempts = self.config.max_retries + 1
        started = time.monotonic()
        for attempt in range(attempts):
            attempt_started = time.monotonic()
            try:
                result = func()
                if attempt:
                    logger.info('storage_%s_recovered attempts=%s elapsed_ms=%.1f',
                                operation, attempt + 1, (time.monotonic() - started) * 1000)
                return result
            except Exception as exc:  # noqa: BLE001 - SDK 异常统一翻译，日志仅输出白名单元数据
                retryable = _is_retryable(exc)
                retry = attempt + 1 < attempts and retryable
                translated = _translate_error(exc)
                if missing_ok and isinstance(translated, StorageNotFound):
                    raise translated from None
                delay = min(0.05 * (2**attempt), 0.5) if retry else 0
                details = _error_details(exc)
                logger.warning(
                    ('storage_%s_%s attempt=%s/%s attempt_ms=%.1f elapsed_ms=%.1f '
                     'timeout_s=%s retryable=%s next_delay_s=%s status=%s code=%s request_id=%s details=%s'),
                    operation, 'retry' if retry else 'failed', attempt + 1, attempts,
                    (time.monotonic() - attempt_started) * 1000,
                    (time.monotonic() - started) * 1000, self.config.timeout_seconds,
                    retryable, delay, details.get('status'), details.get('code'), details.get('request_id'),
                    json.dumps(details, ensure_ascii=True),
                )
                if retry:
                    time.sleep(delay)
                    continue
                raise translated from None
        raise StorageUnavailable(
            "文件存储暂不可用"
        )  # pragma: no cover - 循环必然返回/抛出

    def save(self, namespace: str, filename: str, content: bytes) -> str:
        key = make_key(namespace, filename)
        self.save_to_key(key, content)
        return key

    def save_to_key(self, key: str, content: bytes) -> None:
        """Atomically create a previously selected key; never overwrite an object."""
        namespace = namespace_for_key(key)
        role = bucket_role_for_namespace(namespace)
        self._journal_write(key, role)
        bucket = self._bucket_for_role(role)

        def _put() -> None:
            result = bucket.put_object(
                self.config.key_prefix + key, content,
                headers={"Content-Type": content_type_for_key(key), "x-oss-forbid-overwrite": "true"},
            )
            _close_result(result)

        self._run("put", _put)

    def sign_upload(self, key: str, *, content_type: str, size_bytes: int,
                    expires_seconds: int, sha256: str) -> dict[str, Any]:
        role = bucket_role_for_namespace(namespace_for_key(key))
        self._journal_write(key, role)
        bucket = self._bucket_for_role(role)
        result = self._run("presign", lambda: bucket.presign(
            self.config.key_prefix + key, content_type, size_bytes, expires_seconds, sha256))
        headers = dict(result.signed_headers or {})
        headers = {k: v for k, v in headers.items() if k.lower() not in {"host", "content-length"}}
        if result.expiration is None:
            raise StorageConfigError("SDK 未返回上传签名到期时间")
        return {"method": result.method, "url": result.url, "headers": headers,
                "expires_at": result.expiration.isoformat()}

    def public_url(self, key: str) -> str:
        """私有桶临时 GET 直链；在有效期内复用 URL，避免资料刷新触发图片重载。"""
        now = time.monotonic()
        cached = self._download_urls.get(key)
        if cached and cached[1] > now:
            self._download_urls.move_to_end(key)
            return cached[0]
        bucket = self._bucket_for_key(key)
        ttl = self.config.download_expire_seconds
        result = self._run('presign_get', lambda: bucket.presign_get(self.config.key_prefix + key, ttl))
        if not result.url or result.expiration is None:
            raise StorageConfigError('SDK 未返回有效的读取签名')
        self._download_urls[key] = (result.url, now + max(0, ttl - min(60, ttl / 2)))
        self._download_urls.move_to_end(key)
        while len(self._download_urls) > 2048:
            self._download_urls.popitem(last=False)
        return result.url

    def stat(self, key: str) -> dict[str, Any]:
        bucket = self._bucket_for_key(key)
        result = self._run("head", lambda: bucket.head_object(self.config.key_prefix + key))
        try:
            return {"size_bytes": result.content_length, "content_type": result.content_type,
                    "metadata": dict(result.metadata or {})}
        finally:
            _close_result(result)

    def open(self, key: str) -> bytes:
        return self.read_with_metadata(key)[0]

    def read_with_metadata(self, key: str) -> tuple[bytes, dict[str, Any]]:
        bucket = self._bucket_for_key(key)

        def _get() -> tuple[bytes, dict[str, Any]]:
            result = bucket.get_object(self.config.key_prefix + key)
            body = result.body
            try:
                info = {"size_bytes": result.content_length, "content_type": result.content_type,
                        "metadata": dict(result.metadata or {})}
                data = bytearray()
                for chunk in body.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 10 * 1024 * 1024:
                        raise StorageUnavailable("文件超过读取大小限制")
                return bytes(data), info
            finally:
                body.close()
        return self._run("get", _get)

    def delete(self, key: str) -> None:
        bucket = self._bucket_for_key(key)

        def _delete() -> None:
            _close_result(bucket.delete_object(self.config.key_prefix + key))

        try:
            self._run("delete", _delete)
        except StorageNotFound:
            # 与 LocalStorage 一致：删除不存在对象保持幂等。
            return

    def exists(self, key: str) -> bool:
        bucket = self._bucket_for_key(key)

        def _head() -> None:
            _close_result(bucket.head_object(self.config.key_prefix + key))

        try:
            self._run("head", _head, missing_ok=True)
        except StorageNotFound:
            return False
        return True

    def _open_journal(self, *, create: bool) -> int:
        path = self.config.operation_journal
        if path is None:
            raise StorageConfigError("未配置对象操作日志")
        flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        if create:
            flags |= os.O_CREAT
        try:
            fd = os.open(path, flags, 0o600)
            try:
                require_private(path, fd=fd)
            except OSError:
                os.close(fd)
                raise
            return fd
        except OSError:
            raise StorageUnavailable("无法访问对象操作日志") from None

    def _journal_write(self, key: str, role: str) -> None:
        if self.config.operation_journal is None:
            return
        record = json.dumps({"logical_key": key, "bucket_role": role,
                             "physical_prefix": self.config.key_prefix},
                            ensure_ascii=True, separators=(",", ":")) + "\n"
        fd = self._open_journal(create=True)
        try:
            with exclusive_lock(fd):
                data = record.encode("utf-8")
                while data:
                    count = os.write(fd, data)
                    if count <= 0:
                        raise OSError("journal write failed")
                    data = data[count:]
                os.fsync(fd)
        except OSError:
            raise StorageUnavailable("无法写入对象操作日志") from None
        finally:
            os.close(fd)

    def cleanup_from_journal(self) -> int:
        """清理当前 acceptance 前缀的写前日志对象，不需要列桶权限。"""
        if not re.fullmatch(r"acceptance_[A-Za-z0-9_-]+/", self.config.key_prefix):
            raise StorageConfigError("清理仅允许独立的 acceptance 前缀")
        fd = self._open_journal(create=False)
        try:
            with exclusive_lock(fd):
                with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as journal:
                    records = []
                    failures = 0
                    for line in journal:
                        try:
                            record = json.loads(line)
                            if not isinstance(record, dict) or set(record) != {"logical_key", "bucket_role", "physical_prefix"}:
                                raise ValueError("invalid journal record")
                            key, role = record["logical_key"], record["bucket_role"]
                            if record["physical_prefix"] != self.config.key_prefix or role != bucket_role_for_namespace(namespace_for_key(key)):
                                raise ValueError("invalid journal ownership")
                            records.append((key, role))
                        except (ValueError, TypeError, KeyError, StorageInvalidKey):
                            failures += 1
                removed = 0
                for key, role in dict.fromkeys(records):
                    try:
                        bucket = self._bucket_for_role(role)
                    except StorageError:
                        failures += 1
                        continue
                    physical_key = self.config.key_prefix + key
                    try:
                        self._run("delete", lambda bucket=bucket, physical_key=physical_key: _close_result(bucket.delete_object(physical_key)))
                    except StorageNotFound:
                        pass
                    except StorageError:
                        failures += 1
                    try:
                        self._run("head", lambda bucket=bucket, physical_key=physical_key: _close_result(bucket.head_object(physical_key)))
                    except StorageNotFound:
                        removed += 1
                    except StorageError:
                        failures += 1
                    else:
                        failures += 1
                if failures:
                    raise StorageUnavailable("验收对象清理未完全成功，请重试同一日志")
                return removed
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, StorageInvalidKey):
            raise StorageConfigError("对象操作日志无效或不可读取") from None
        finally:
            os.close(fd)

    def cleanup_acceptance_prefix(self) -> int:
        """Clean via write-ahead journal without ListBucket permission."""
        return self.cleanup_from_journal()

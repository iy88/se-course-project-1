"""Object storage abstraction, key conventions, and local implementation.

Production uses Alibaba Cloud OSS with private dual buckets (media / report evidence);
development and offline tests use ``LocalStorage``. Both share the synchronous
``StorageBackend`` contract; the routing layer that performs network I/O places calls
in a thread pool to avoid blocking the event loop.
"""

from __future__ import annotations

import re
import stat
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.security import sign_file_key

# The namespace-to-bucket mapping is fixed and unknown namespaces are rejected; callers cannot choose the bucket themselves.
MEDIA_NAMESPACES = frozenset({"product", "avatar", "chat"})
EVIDENCE_NAMESPACES = frozenset({"report"})
ALLOWED_NAMESPACES = MEDIA_NAMESPACES | EVIDENCE_NAMESPACES
ALLOWED_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp"})

EXTENSION_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# Legacy-compatible constant: at least one subpath, with a supported image extension on the last segment.
SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)+\.[A-Za-z0-9]+$")
MAX_KEY_LENGTH = 512


class StorageError(Exception):
    """Base class for storage-layer errors that are safe to show to callers."""


class StorageConfigError(StorageError):
    """Missing configuration, missing dependency, or client initialization failure."""


class StorageInvalidKey(StorageError):
    """The key/namespace violates the convention, or the path attempts to escape the storage root."""


class StorageNotFound(StorageError):
    """The object does not exist."""


class StoragePermissionDenied(StorageError):
    """Object storage denied authorization (server credentials/policy, not end-user permission)."""


class StorageUnavailable(StorageError):
    """Temporary unavailability such as network errors, timeouts, or server 5xx; must not fall back to local storage."""


class StorageAlreadyExists(StorageError):
    """Immutable object key already exists; the upload lease cannot overwrite it."""


def bucket_role_for_namespace(namespace: str) -> str:
    """Return ``media`` or ``evidence``; reject unknown namespaces outright."""
    if namespace in EVIDENCE_NAMESPACES:
        return "evidence"
    if namespace in MEDIA_NAMESPACES:
        return "media"
    raise StorageInvalidKey("非法的文件命名空间")


def namespace_for_key(key: str) -> str:
    validate_key(key)
    return key.split("/", 1)[0]


def validate_key(key: object) -> str:
    """Validate a logical key: only supported namespaces, safe path segments, and image extensions are allowed."""
    if not isinstance(key, str):
        raise StorageInvalidKey("非法文件 key")
    if not key or len(key) > MAX_KEY_LENGTH:
        raise StorageInvalidKey("非法文件 key")
    if key.startswith("/") or "\\" in key or "\x00" in key or "//" in key:
        raise StorageInvalidKey("非法文件 key")
    if key != key.strip():
        raise StorageInvalidKey("非法文件 key")

    parts = key.split("/")
    if len(parts) < 2:
        raise StorageInvalidKey("非法文件 key")
    if parts[0] not in ALLOWED_NAMESPACES:
        raise StorageInvalidKey("非法的文件命名空间")
    for part in parts[:-1]:
        if not _SAFE_SEGMENT_RE.fullmatch(part):
            raise StorageInvalidKey("非法文件 key")

    stem, dot, extension = parts[-1].rpartition(".")
    if not dot or not _SAFE_SEGMENT_RE.fullmatch(stem):
        raise StorageInvalidKey("非法文件 key")
    if extension.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise StorageInvalidKey("非法文件 key")
    return key


def make_key(namespace: str, filename: str) -> str:
    """Generate a logical key of the form ``namespace/YYYYMM/<uuid4hex>.<ext>``."""
    if namespace not in ALLOWED_NAMESPACES:
        raise StorageInvalidKey("非法的文件命名空间")
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise StorageInvalidKey("仅支持 png/jpg/jpeg/gif/webp 图片")
    return (
        f"{namespace}/{datetime.now(UTC).strftime('%Y%m')}/{uuid.uuid4().hex}.{suffix}"
    )


def content_type_for_key(key: str) -> str:
    return EXTENSION_CONTENT_TYPES.get(
        Path(key).suffix.lower(), "application/octet-stream"
    )


class StorageBackend(ABC):
    @abstractmethod
    def save(self, namespace: str, filename: str, content: bytes) -> str:
        """Save content and return the logical key (e.g. product/202610/ab12.png).

        The caller is responsible for registering the reference in a business
        transaction; this layer creates no database records.
        """

    @abstractmethod
    def open(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete an object. The caller must first confirm no business reference and no production evidence; this layer does not query the database."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    def stat(self, key: str) -> dict[str, Any]:
        raise NotImplementedError

    def read_with_metadata(self, key: str) -> tuple[bytes, dict[str, Any]]:
        """Read content and metadata for upload confirmation; remote backends may combine the requests."""
        info = self.stat(key)
        return self.open(key), info

    def sign_upload(self, key: str, *, content_type: str, size_bytes: int,
                    expires_seconds: int, sha256: str) -> dict[str, Any]:
        raise StorageConfigError("The current storage backend does not support OSS presigned uploads")

    def save_to_key(self, key: str, content: bytes) -> None:
        raise StorageConfigError("The current storage backend does not support direct local writes")

    def public_url(self, key: str) -> str:
        """Backend HMAC-signed access URL, read through /api/v1/files/{key}.

        Local storage uses this entry point; the OSS backend overrides it with a
        temporary signed direct GET URL.
        """
        return f"/api/v1/files/{key}?{sign_file_key(key)}"


class LocalStorage(StorageBackend):
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise StorageInvalidKey("非法文件路径") from exc
        return path

    def save(self, namespace: str, filename: str, content: bytes) -> str:
        key = make_key(namespace, filename)
        self.save_to_key(key, content)
        return key

    def save_to_key(self, key: str, content: bytes) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
        except FileExistsError as exc:
            raise StorageAlreadyExists("The file already exists and cannot be overwritten") from exc
        except PermissionError as exc:
            raise StoragePermissionDenied("Insufficient file storage permission") from exc
        except OSError as exc:
            raise StorageUnavailable("File storage is temporarily unavailable") from exc

    def stat(self, key: str) -> dict[str, Any]:
        path = self._path(key)
        try:
            size = path.stat().st_size
            return {"size_bytes": size, "content_type": content_type_for_key(key), "metadata": {}}
        except FileNotFoundError as exc:
            raise StorageNotFound("The file does not exist") from exc
        except PermissionError as exc:
            raise StoragePermissionDenied("Insufficient file storage permission") from exc
        except OSError as exc:
            raise StorageUnavailable("File storage is temporarily unavailable") from exc

    def open(self, key: str) -> bytes:
        path = self._path(key)
        try:
            with path.open("rb") as stream:
                data = stream.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024:
                raise StorageUnavailable("The file exceeds the read size limit")
            return data
        except FileNotFoundError as exc:
            raise StorageNotFound("The file does not exist") from exc
        except PermissionError as exc:
            raise StoragePermissionDenied("Insufficient file storage permission") from exc
        except OSError as exc:
            raise StorageUnavailable("File storage is temporarily unavailable") from exc

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink(missing_ok=True)
        except PermissionError as exc:
            raise StoragePermissionDenied("Insufficient file storage permission") from exc
        except OSError as exc:
            raise StorageUnavailable("File storage is temporarily unavailable") from exc

    def exists(self, key: str) -> bool:
        path = self._path(key)
        try:
            return stat.S_ISREG(path.stat().st_mode)
        except FileNotFoundError:
            return False
        except PermissionError as exc:
            raise StoragePermissionDenied("Insufficient file storage permission") from exc
        except OSError as exc:
            raise StorageUnavailable("File storage is temporarily unavailable") from exc


def build_storage(settings: Any | None = None) -> StorageBackend:
    """Build the backend from configuration; fail explicitly on an unknown backend or missing field instead of silently falling back to local."""
    settings = settings or get_settings()
    backend = str(getattr(settings, "storage_backend", "") or "").strip().lower()
    if not backend:
        raise StorageConfigError("Cannot determine the storage backend from the resource configuration")
    if backend == "local":
        root = getattr(settings, "storage_local_root", None)
        if root is None or not str(root).strip():
            raise StorageConfigError("Missing configuration item: STORAGE_LOCAL_ROOT")
        return LocalStorage(root)
    if backend == "oss":
        from app.storage.oss import OssConfig, OssStorage

        return OssStorage(OssConfig.from_settings(settings))
    raise StorageConfigError("The storage backend selected by the resource configuration is not supported")


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        _storage = build_storage()
    return _storage


def reset_storage() -> None:
    """Clear the process cache (used by tests or when switching configuration)."""
    global _storage
    _storage = None


def __getattr__(name: str) -> Any:
    # Keep ``from app.storage.base import OssStorage`` working while avoiding import failure in environments without the SDK.
    if name in {"OssConfig", "OssStorage"}:
        from app.storage import oss

        return getattr(oss, name)
    raise AttributeError(name)

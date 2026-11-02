"""对象存储抽象、key 约定与本地实现。

生产使用阿里云 OSS 私有双桶（媒体 / 举报证据），开发与离线测试使用
``LocalStorage``。两者共享同步 ``StorageBackend`` 合约；网络 I/O 的路由层
负责放入线程池，避免阻塞事件循环。
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

# namespace 到桶的映射固定，未知 namespace 一律拒绝；不能由调用方自行指定 bucket。
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
# 兼容历史常量：至少一个子路径，最后一段带受支持的图片扩展名。
SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)+\.[A-Za-z0-9]+$")
MAX_KEY_LENGTH = 512


class StorageError(Exception):
    """存储层可安全展示给调用方的错误基类。"""


class StorageConfigError(StorageError):
    """配置缺失、依赖缺失或客户端初始化失败。"""


class StorageInvalidKey(StorageError):
    """key / namespace 不符合约定，或路径试图逃逸存储根。"""


class StorageNotFound(StorageError):
    """对象不存在。"""


class StoragePermissionDenied(StorageError):
    """对象存储拒绝授权（服务端凭据/策略问题，不是终端用户权限）。"""


class StorageUnavailable(StorageError):
    """网络、超时、服务端 5xx 等临时不可用；不得回退到本地。"""


class StorageAlreadyExists(StorageError):
    """Immutable object key already exists; the upload lease cannot overwrite it."""


def bucket_role_for_namespace(namespace: str) -> str:
    """返回 ``media`` 或 ``evidence``；未知 namespace 直接拒绝。"""
    if namespace in EVIDENCE_NAMESPACES:
        return "evidence"
    if namespace in MEDIA_NAMESPACES:
        return "media"
    raise StorageInvalidKey("非法的文件命名空间")


def namespace_for_key(key: str) -> str:
    validate_key(key)
    return key.split("/", 1)[0]


def validate_key(key: object) -> str:
    """校验逻辑 key：只允许受支持 namespace、安全路径段和图片扩展名。"""
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
    """生成 ``namespace/YYYYMM/<uuid4hex>.<ext>`` 形式的逻辑 key。"""
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
        """保存内容并返回逻辑 key（如 product/202610/ab12.png）。

        调用方负责在业务事务中登记引用；本层不创建数据库记录。
        """

    @abstractmethod
    def open(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """删除对象。调用方必须先确认无业务引用、非生产证据，本层不查数据库。"""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    def stat(self, key: str) -> dict[str, Any]:
        raise NotImplementedError

    def read_with_metadata(self, key: str) -> tuple[bytes, dict[str, Any]]:
        """读取用于上传确认的内容与元信息；远端后端可合并请求。"""
        info = self.stat(key)
        return self.open(key), info

    def sign_upload(self, key: str, *, content_type: str, size_bytes: int,
                    expires_seconds: int, sha256: str) -> dict[str, Any]:
        raise StorageConfigError("当前存储后端不支持 OSS 预签名上传")

    def save_to_key(self, key: str, content: bytes) -> None:
        raise StorageConfigError("当前存储后端不支持本地直传写入")

    def public_url(self, key: str) -> str:
        """后端 HMAC 签名访问 URL，通过 /api/v1/files/{key} 读取。

        local 使用此入口；OSS 后端覆盖为临时签名 GET 直链。
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
            raise StorageAlreadyExists("文件已存在，不能覆盖") from exc
        except PermissionError as exc:
            raise StoragePermissionDenied("文件存储权限不足") from exc
        except OSError as exc:
            raise StorageUnavailable("文件存储暂不可用") from exc

    def stat(self, key: str) -> dict[str, Any]:
        path = self._path(key)
        try:
            size = path.stat().st_size
            return {"size_bytes": size, "content_type": content_type_for_key(key), "metadata": {}}
        except FileNotFoundError as exc:
            raise StorageNotFound("文件不存在") from exc
        except PermissionError as exc:
            raise StoragePermissionDenied("文件存储权限不足") from exc
        except OSError as exc:
            raise StorageUnavailable("文件存储暂不可用") from exc

    def open(self, key: str) -> bytes:
        path = self._path(key)
        try:
            with path.open("rb") as stream:
                data = stream.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024:
                raise StorageUnavailable("文件超过读取大小限制")
            return data
        except FileNotFoundError as exc:
            raise StorageNotFound("文件不存在") from exc
        except PermissionError as exc:
            raise StoragePermissionDenied("文件存储权限不足") from exc
        except OSError as exc:
            raise StorageUnavailable("文件存储暂不可用") from exc

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink(missing_ok=True)
        except PermissionError as exc:
            raise StoragePermissionDenied("文件存储权限不足") from exc
        except OSError as exc:
            raise StorageUnavailable("文件存储暂不可用") from exc

    def exists(self, key: str) -> bool:
        path = self._path(key)
        try:
            return stat.S_ISREG(path.stat().st_mode)
        except FileNotFoundError:
            return False
        except PermissionError as exc:
            raise StoragePermissionDenied("文件存储权限不足") from exc
        except OSError as exc:
            raise StorageUnavailable("文件存储暂不可用") from exc


def build_storage(settings: Any | None = None) -> StorageBackend:
    """按配置构建后端；未知后端或缺少字段时显式报错，不静默回退 local。"""
    settings = settings or get_settings()
    backend = str(getattr(settings, "storage_backend", "") or "").strip().lower()
    if not backend:
        raise StorageConfigError("无法从资源配置确定存储后端")
    if backend == "local":
        root = getattr(settings, "storage_local_root", None)
        if root is None or not str(root).strip():
            raise StorageConfigError("缺少配置项：STORAGE_LOCAL_ROOT")
        return LocalStorage(root)
    if backend == "oss":
        from app.storage.oss import OssConfig, OssStorage

        return OssStorage(OssConfig.from_settings(settings))
    raise StorageConfigError("资源配置对应的存储后端不受支持")


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        _storage = build_storage()
    return _storage


def reset_storage() -> None:
    """清空进程缓存（测试或配置切换使用）。"""
    global _storage
    _storage = None


def __getattr__(name: str) -> Any:
    # 兼容 ``from app.storage.base import OssStorage``，同时避免无 SDK 环境导入即失败。
    if name in {"OssConfig", "OssStorage"}:
        from app.storage import oss

        return getattr(oss, name)
    raise AttributeError(name)

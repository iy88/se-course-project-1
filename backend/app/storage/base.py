"""对象存储抽象。

开发阶段使用 LocalStorage（var/storage/，Git 忽略）；阿里云 OSS 仅为接口桩，
生产对接不在本期范围（见 bits/开发阶段技术决策.md）。
"""

import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings
from app.core.security import sign_file_key

SAFE_KEY_RE = re.compile(r"^[a-zA-Z0-9_\-/]+\.[a-zA-Z0-9]+$")


class StorageError(Exception):
    pass


class StorageBackend(ABC):
    @abstractmethod
    def save(self, namespace: str, filename: str, content: bytes) -> str:
        """保存内容，返回存储 key（如 product/202610/ab12.png）。"""

    @abstractmethod
    def open(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    def public_url(self, key: str) -> str:
        """签名访问 URL（HMAC + 过期），通过 /api/v1/files/{key} 读取。"""
        return f"/api/v1/files/{key}?{sign_file_key(key)}"


def make_key(namespace: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in {"png", "jpg", "jpeg", "gif", "webp"}:
        raise StorageError("仅支持 png/jpg/jpeg/gif/webp 图片")
    now = uuid.uuid4().hex[:12]
    from datetime import datetime

    return f"{namespace}/{datetime.now().strftime('%Y%m')}/{now}.{suffix}"


class LocalStorage(StorageBackend):
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not SAFE_KEY_RE.match(key):
            raise StorageError("非法文件 key")
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise StorageError("非法文件路径")
        return path

    def save(self, namespace: str, filename: str, content: bytes) -> str:
        key = make_key(namespace, filename)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    def open(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageError("文件不存在")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class OssStorage(StorageBackend):
    """阿里云 OSS 适配桩。生产对接不在本期开发范围，实例化即报错提示。"""

    def __init__(self) -> None:
        raise NotImplementedError(
            "阿里云 OSS 对接不在本期开发范围；开发阶段请使用 storage_backend=local"
        )

    def save(self, namespace: str, filename: str, content: bytes) -> str:  # pragma: no cover
        raise NotImplementedError

    def open(self, key: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def exists(self, key: str) -> bool:  # pragma: no cover
        raise NotImplementedError


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_backend == "oss":
            _storage = OssStorage()
        else:
            _storage = LocalStorage(settings.storage_local_root)
    return _storage

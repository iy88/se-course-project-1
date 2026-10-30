"""图片校验：限制大小，核对文件头/扩展名，并校验图片结构及解码。"""

from __future__ import annotations

import warnings
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.storage.base import (
    ALLOWED_IMAGE_EXTENSIONS,
    EXTENSION_CONTENT_TYPES,
    StorageError,
)

MAX_IMAGE_BYTES = 10 * 1024 * 1024

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF_MAGICS = (b"GIF87a", b"GIF89a")


class ImageValidationError(StorageError):
    """上传内容不是受支持的真实图片。"""


def detect_image_type(content: bytes) -> str | None:
    """只依据文件头返回 image/*；无法识别时返回 None。"""
    if not content:
        return None
    if content.startswith(_PNG_MAGIC):
        return "image/png"
    if content.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if content.startswith(_GIF_MAGICS):
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(content: bytes, filename: str) -> str:
    """校验大小、magic 与扩展名一致性，返回真实 MIME。"""
    if not content:
        raise ImageValidationError("空文件")
    if len(content) > MAX_IMAGE_BYTES:
        raise ImageValidationError("文件过大（上限 10MB）")

    detected = detect_image_type(content)
    if detected is None:
        raise ImageValidationError("文件内容不是受支持的图片")

    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ImageValidationError("仅支持 png/jpg/jpeg/gif/webp 图片")
    if EXTENSION_CONTENT_TYPES[f".{suffix}"] != detected:
        raise ImageValidationError("文件内容与扩展名不一致")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageValidationError("图片内容损坏或像素尺寸超限") from exc
    return detected

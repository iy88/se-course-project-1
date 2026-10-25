"""文件上传与签名 URL 访问（本地存储实现；OSS 为生产桩）。"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from app.api.deps import CurrentUser, ensure_can_write
from app.core.security import verify_file_signature
from app.storage.base import StorageError, get_storage

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_NAMESPACES = {"product", "report", "avatar", "chat"}
MAX_SIZE = 10 * 1024 * 1024

CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@router.post("/upload")
async def upload(file: UploadFile, namespace: str = "product", user: CurrentUser = None) -> dict:
    ensure_can_write(user)
    if namespace not in ALLOWED_NAMESPACES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "非法的文件命名空间")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件过大（上限 10MB）")
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "空文件")
    storage = get_storage()
    try:
        key = storage.save(namespace, file.filename or "upload.png", content)
    except StorageError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"key": key, "url": storage.public_url(key)}


@router.get("/{key:path}")
async def download(key: str, request: Request) -> Response:
    """签名 URL 访问：配合 BR-22，未登录不可通过直链读取业务文件。"""
    exp = request.query_params.get("exp", "")
    sig = request.query_params.get("sig", "")
    if not verify_file_signature(key, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "文件链接无效或已过期")
    storage = get_storage()
    try:
        content = storage.open(key)
    except StorageError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    suffix = "." + key.rsplit(".", 1)[-1].lower()
    media_type = CONTENT_TYPES.get(suffix, "application/octet-stream")
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})

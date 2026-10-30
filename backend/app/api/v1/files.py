"""Signed direct-upload leases and verified image access.

Declare -> immutable direct PUT -> verify metadata, bytes, SHA-256 and image
decoding -> allow business reference. Reads retain the application HMAC URL;
only a narrowly scoped PUT URL is returned for upload. SDK calls use a threadpool.
"""

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import col, select
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.core.config import get_settings
from app.core.security import verify_file_signature
from app.models.stored_object import StoredObject
from app.models.upload_lease import UploadLease
from app.services import audit as audit_service
from app.services import stored_objects
from app.storage.base import (
    ALLOWED_NAMESPACES,
    StorageAlreadyExists,
    StorageConfigError,
    StorageError,
    StorageInvalidKey,
    StorageNotFound,
    StoragePermissionDenied,
    StorageUnavailable,
    content_type_for_key,
    get_storage,
    make_key,
)
from app.storage.images import (
    MAX_IMAGE_BYTES,
    ImageValidationError,
    detect_image_type,
    validate_image,
)

router = APIRouter(prefix="/files", tags=["files"])

MAX_SIZE = MAX_IMAGE_BYTES


def _storage_for_request():
    try:
        return get_storage()
    except StorageConfigError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "文件存储暂不可用") from exc


def _upload_storage_error(exc: StorageError) -> HTTPException:
    if isinstance(exc, StorageAlreadyExists):
        return HTTPException(status.HTTP_409_CONFLICT, "文件已上传")
    if isinstance(exc, StorageInvalidKey):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, StorageNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    if isinstance(exc, (StorageConfigError, StoragePermissionDenied)):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, "文件存储暂不可用")
    if isinstance(exc, StorageUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储暂不可用")
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储暂不可用")


def _download_storage_error(exc: StorageError) -> HTTPException:
    if isinstance(exc, (StorageInvalidKey, StorageNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    if isinstance(exc, (StorageConfigError, StoragePermissionDenied)):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, "文件存储暂不可用")
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储暂不可用")


class LeaseRequest(BaseModel):
    namespace: str
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0, le=MAX_SIZE)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _expired(lease: UploadLease) -> bool:
    expiry = lease.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return datetime.now(UTC) >= expiry


def _lease_sig(lease_id: str, exp: int) -> str:
    secret = get_settings().file_url_secret.encode()
    return hmac.new(secret, f"upload:{lease_id}:{exp}".encode(), hashlib.sha256).hexdigest()


@router.post("/upload-leases")
async def issue_lease(body: LeaseRequest, user: CurrentUser, db: DbSession) -> dict:
    ensure_can_write(user)
    if body.namespace not in ALLOWED_NAMESPACES:
        raise HTTPException(400, "非法的文件命名空间")
    try:
        key = make_key(body.namespace, body.filename)
        if content_type_for_key(key) != body.content_type:
            raise StorageInvalidKey("文件类型与扩展名不一致")
    except StorageError as exc:
        raise _upload_storage_error(exc) from exc
    settings = get_settings()
    lease_id = uuid.uuid4().hex
    expiry = datetime.now(UTC) + timedelta(seconds=settings.upload_lease_expire_seconds)
    lease = UploadLease(id=lease_id, key=key, owner_id=user.id, namespace=body.namespace,
        filename=body.filename, content_type=body.content_type, size_bytes=body.size_bytes,
        sha256=body.sha256, expires_at=expiry, state="pending")
    storage = _storage_for_request()
    if settings.storage_backend == "local":
        exp = int(expiry.timestamp())
        upload = {"method": "PUT", "url": f"/api/v1/files/upload-leases/{lease_id}/content?exp={exp}&sig={_lease_sig(lease_id, exp)}", "headers": {"Content-Type": body.content_type}}
    else:
        try:
            upload = await run_in_threadpool(storage.sign_upload, key, content_type=body.content_type,
                size_bytes=body.size_bytes, expires_seconds=settings.upload_lease_expire_seconds, sha256=body.sha256)
        except StorageError as exc:
            raise _upload_storage_error(exc) from exc
        expiry = datetime.fromisoformat(upload["expires_at"])
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        lease.expires_at = expiry
    db.add(lease)
    stored_objects.register_upload(db,key=key,owner_id=user.id,content_type=body.content_type,
        size_bytes=body.size_bytes,metadata={"sha256":body.sha256,"upload_state":"pending"})
    await audit_service.record_event(db, "file.lease_issue", target_type="upload_lease", target_id=lease_id, actor_id=user.id)
    await db.commit()
    return {"lease_id": lease_id, "key": key, "expires_at": expiry.isoformat(), "upload": upload}


if get_settings().storage_backend == "local":
    @router.put("/upload-leases/{lease_id}/content")
    async def upload_content(lease_id: str, request: Request, db: DbSession) -> dict:
        try:
            exp = int(request.query_params.get("exp", ""))
        except ValueError:
            raise HTTPException(403, "上传链接无效或已过期") from None
        sig = request.query_params.get("sig", "")
        if exp <= int(time.time()) or not hmac.compare_digest(_lease_sig(lease_id, exp), sig):
            raise HTTPException(403, "上传链接无效或已过期")
        lease = (await db.exec(select(UploadLease).where(col(UploadLease.id) == lease_id).with_for_update())).one_or_none()
        if lease is None or lease.state != "pending" or _expired(lease) or exp != int(lease.expires_at.replace(tzinfo=lease.expires_at.tzinfo or UTC).timestamp()):
            raise HTTPException(403, "上传链接无效或已过期")
        if request.headers.get("content-type") != lease.content_type:
            raise HTTPException(400, "文件类型不一致")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > lease.size_bytes:
                raise HTTPException(413, "文件过大")
        if len(data) != lease.size_bytes:
            raise HTTPException(400, "文件大小不一致")
        try:
            await run_in_threadpool(_storage_for_request().save_to_key, lease.key, bytes(data))
        except StorageError as exc:
            raise _upload_storage_error(exc) from exc
        await audit_service.record_event(db, "file.upload", target_type="upload_lease", target_id=lease_id, actor_id=lease.owner_id, actor_role="user")
        await db.commit()
        return {"uploaded": True}


@router.post("/upload-leases/{lease_id}/complete")
async def complete_lease(lease_id: str, user: CurrentUser, db: DbSession) -> dict:
    ensure_can_write(user)
    lease = (await db.exec(select(UploadLease).where(col(UploadLease.id) == lease_id).with_for_update())).one_or_none()
    if lease is None or lease.owner_id != user.id:
        raise HTTPException(404, "上传租约不存在")
    storage = _storage_for_request()
    if lease.state == "completed":
        obj = (await db.exec(select(StoredObject).where(col(StoredObject.key) == lease.key).with_for_update())).one_or_none()
        if obj is None or obj.state == "deleted":
            raise HTTPException(409, "文件已失效")
        return {"key": lease.key, "url": storage.public_url(lease.key)}
    if lease.state != "pending" or _expired(lease):
        raise HTTPException(403, "上传租约已失效")
    try:
        info = await run_in_threadpool(storage.stat, lease.key)
        if info["size_bytes"] != lease.size_bytes or info["content_type"] != lease.content_type:
            raise ImageValidationError("文件元数据不一致")
        if get_settings().storage_backend == "oss" and info["metadata"].get("sha256") != lease.sha256:
            raise ImageValidationError("文件元数据不一致")
        data = await run_in_threadpool(storage.open, lease.key)
        if len(data) != lease.size_bytes or hashlib.sha256(data).hexdigest() != lease.sha256:
            raise ImageValidationError("文件摘要或大小不一致")
        if validate_image(data, lease.filename) != lease.content_type:
            raise ImageValidationError("文件类型不一致")
    except ImageValidationError as exc:
        lease.state = "failed"
        await db.commit()
        # Keep the immutable object until its signed PUT expires; deleting now
        # would permit a still-valid URL to recreate an untracked object.
        raise HTTPException(400, str(exc)) from exc
    except StorageError as exc:
        raise _upload_storage_error(exc) from exc
    obj=(await db.exec(select(StoredObject).where(col(StoredObject.key)==lease.key).with_for_update())).one()
    if obj.state != "staged":
        raise HTTPException(409,"文件登记状态无效")
    obj.object_metadata={"image_type":lease.content_type,"sha256":lease.sha256,"upload_state":"verified"}
    lease.state = "completed"
    await audit_service.record_event(db, "file.lease_complete", target_type="upload_lease", target_id=lease_id, actor_id=user.id)
    await db.commit()
    return {"key": lease.key, "url": storage.public_url(lease.key)}


@router.get("/{key:path}")
async def download(key: str, request: Request) -> Response:
    """签名 URL 访问：配合 BR-22，未登录不可通过直链读取业务文件。"""
    exp = request.query_params.get("exp", "")
    sig = request.query_params.get("sig", "")
    if not verify_file_signature(key, exp, sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "文件链接无效或已过期")

    storage = _storage_for_request()
    try:
        content = await run_in_threadpool(storage.open, key)
    except StorageError as exc:
        raise _download_storage_error(exc) from exc

    # 上传时已校验真实类型；历史本地对象无法识别时退回扩展名映射。
    media_type = detect_image_type(content) or content_type_for_key(key)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )

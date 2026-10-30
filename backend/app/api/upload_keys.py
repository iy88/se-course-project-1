"""Validate ownership and completion for attachments with upload leases."""

from fastapi import HTTPException, status
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.upload_lease import UploadLease


async def validate_upload_keys(
    db: AsyncSession, keys: list[str], *, owner_id: int, namespace: str
) -> None:
    for key in set(keys):
        lease = (await db.exec(select(UploadLease).where(col(UploadLease.key) == key))).one_or_none()
        # Historical objects predate leases and retain their existing business behavior.
        if lease is None:
            continue
        if lease.owner_id != owner_id or lease.namespace != namespace or lease.state != "completed":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "附件未验证或无权使用，请重新上传")

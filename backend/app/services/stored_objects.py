"""Object registration, business references, and staged reclamation.

Constraints:
- After a successful upload, register the object as ``staged``; if the registration
  commit fails, only the object created by that request may be deleted as compensation.
- When a business transaction references an object, change its registration to
  ``committed``; once referenced, this module must never delete the object physically.
- Reclamation handles only ``staged`` objects and always confirms the absence of
  references with a live query against business tables; evidence has no default TTL
  and no scheduled job, so an operator must invoke cleanup explicitly and it only
  lists by default.
- Cleanup and business ``mark_committed`` take a row lock on the same registration row
  (PostgreSQL ``FOR UPDATE``): lock the row, query references, delete the object, then
  mark ``deleted``. If a business transaction obtains the lock only after cleanup
  commits, it sees ``deleted`` and must fail and roll back rather than reference a
  physically deleted object.
- Evidence objects are protected from physical deletion by this module by default;
  the retention reason is recorded as ``evidence_protected``. This is a conservative
  policy and does not replace the owner's decision on evidence retention periods.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import bindparam, col, select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.governance import Report, ReportSupplement
from app.models.product import ProductImage
from app.models.stored_object import StoredObject
from app.models.upload_lease import UploadLease
from app.storage.base import (
    StorageBackend,
    StorageError,
    StorageInvalidKey,
    StorageNotFound,
    bucket_role_for_namespace,
    namespace_for_key,
    validate_key,
)

_REF_TYPES = frozenset(
    {
        "product",
        "report",
        "report_supplement",
        "avatar",
        "chat",
        "system",
    }
)


class StoredObjectUnavailable(RuntimeError):
    """The registered object has been reclaimed; a business transaction referencing it must roll back and cannot commit."""

    def __init__(self, key: str | None = None) -> None:
        self.key = key
        super().__init__("The object has been reclaimed and can no longer be referenced")


@dataclass
class CleanupResult:
    """Redacted result of one staged reclamation; keys only help locate the object in local reports and are not logged."""

    dry_run: bool
    candidates: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    retained: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def build_staged_object(
    *,
    key: str,
    owner_id: int | None,
    content_type: str,
    size_bytes: int,
    metadata: dict | None = None,
) -> StoredObject:
    """Build an upload registration record; does not commit, since the upload request commits it with the registration."""
    validate_key(key)
    namespace = namespace_for_key(key)
    bucket_role = bucket_role_for_namespace(namespace)
    if size_bytes < 0:
        raise ValueError("Object size cannot be negative")
    if not content_type or len(content_type) > 64:
        raise ValueError("Invalid object content_type")
    return StoredObject(
        key=key,
        namespace=namespace,
        bucket_role=bucket_role,
        owner_id=owner_id,
        content_type=content_type,
        size_bytes=size_bytes,
        object_metadata=dict(metadata or {}),
        state="staged",
    )


def register_upload(
    db: AsyncSession,
    *,
    key: str,
    owner_id: int | None,
    content_type: str,
    size_bytes: int,
    metadata: dict | None = None,
) -> StoredObject:
    """Register a just-uploaded object as staged; the caller is responsible for commit.

    When upload registration fails (this function or the commit raises), the caller may
    only compensate by deleting the key created by this request and must not delete any
    pre-existing object.
    """
    stored = build_staged_object(
        key=key,
        owner_id=owner_id,
        content_type=content_type,
        size_bytes=size_bytes,
        metadata=metadata,
    )
    db.add(stored)
    return stored


async def mark_committed(
    db: AsyncSession,
    keys: Iterable[str],
    *,
    ref_type: str,
    ref_id: object,
) -> int:
    """Turn staged objects into committed within a business transaction; does not commit.

    Historical objects without a registration stay unchanged and do not affect existing
    business; a shared object already committed is not overwritten by a later reference.
    Each registration row is locked with ``SELECT ... FOR UPDATE`` in key order, using the
    same row lock as cleanup: if cleanup already marked it ``deleted``, this function
    raises :class:`StoredObjectUnavailable` and the caller must roll back the whole
    business transaction.

    Callers should invoke this in the same transaction that inserts the business
    reference (product images/report evidence); the row locks are held until that
    transaction commits or rolls back.
    """
    if ref_type not in _REF_TYPES:
        raise ValueError("Invalid object reference type")
    if not isinstance(ref_id, int) or ref_id <= 0:
        raise ValueError("Invalid object reference ID")
    unique: list[str] = []
    for key in keys:
        if not key or key in unique:
            continue
        try:
            validate_key(key)
        except StorageInvalidKey:
            # Historical data may contain non-standard keys; registration is supplementary safety information and must not block business.
            continue
        unique.append(key)
    if not unique:
        return 0
    committed = 0
    # Lock one by one in sorted order to avoid nondeterministic lock order under multi-key concurrency.
    for key in sorted(unique):
        lease = (await db.exec(select(UploadLease).where(col(UploadLease.key) == key))).one_or_none()
        if lease is not None and lease.state != "completed":
            raise StoredObjectUnavailable(key)
        row = (
            await db.exec(
                select(StoredObject)
                .where(col(StoredObject.key) == key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            # A declared upload is never a legacy object before verification.
            lease = (await db.exec(select(UploadLease).where(col(UploadLease.key) == key))).one_or_none()
            if lease is not None:
                raise StoredObjectUnavailable(key)
            continue
        if row.state == "deleted":
            raise StoredObjectUnavailable(key)
        if row.state == "committed":
            continue
        row.state = "committed"
        row.ref_type = ref_type
        row.ref_id = ref_id
        row.committed_at = datetime.now(UTC)
        committed += 1
    if committed:
        # Issue the UPDATE inside the business transaction so constraint/connection errors surface at mark_committed.
        await db.flush()
    return committed


async def referenced_keys(db: AsyncSession, keys: Iterable[str]) -> set[str]:
    """Confirm with business tables which keys are still referenced.

    ``product_images.file_key`` and the report/supplement evidence JSON arrays are the
    current business reference sources. The query does not depend on registration state,
    so a failed registration or an unregistered historical object never causes a live
    reference to be deleted by mistake.
    """
    unique = sorted({key for key in keys if key})
    if not unique:
        return set()

    from app.models import DisposalCase, User
    found: set[str] = set()
    for avatar_column in (User.avatar_key, User.avatar_pending_key, DisposalCase.avatar_key):
        avatars = await db.exec(select(avatar_column).where(col(avatar_column).in_(unique)))
        found.update(str(value) for value in avatars if value)
    rows = await db.exec(select(col(ProductImage.file_key)).where(col(ProductImage.file_key).in_(unique)))
    found.update(str(value) for value in rows if value)

    dialect = db.get_bind().dialect.name
    for table in (Report.__tablename__, ReportSupplement.__tablename__):
        if dialect == "postgresql":
            statement = text(
                (f"SELECT DISTINCT value FROM {table}, "
                 f"jsonb_array_elements_text({table}.evidence_keys) AS value "
                 "WHERE value IN :keys")
            )
        else:
            statement = text(
                (f"SELECT DISTINCT value FROM {table}, json_each({table}.evidence_keys) "
                 "WHERE value IN :keys")
            )
        connection = await db.connection()
        result = await connection.execute(
            statement.bindparams(bindparam("keys", expanding=True)), {"keys": unique}
        )
        found.update(str(row[0]) for row in result.all() if row[0] is not None)
    return found


async def list_unreferenced_staged(
    db: AsyncSession, *, limit: int = 100, for_update: bool = False
) -> list[StoredObject]:
    """List staged objects confirmed to have no business references; no time threshold and no deletion.

    ``for_update`` is used only by the actual deletion path of reclamation: ``SKIP LOCKED``
    locks candidate registration rows not currently held by another transaction; rows
    locked by a business transaction are skipped and not cleaned up. From locking until
    the transaction ends, a later business ``mark_committed`` waits on the same row lock.
    Read-only listing must not pass ``for_update``.
    """
    if limit <= 0:
        raise ValueError("limit must be a positive integer")
    statement = (
        select(StoredObject)
        .where(col(StoredObject.state) == "staged")
        .order_by(col(StoredObject.created_at), col(StoredObject.key))
        .limit(limit)
    )
    if for_update:
        statement = statement.with_for_update(skip_locked=True)
    candidates = (await db.exec(statement)).all()
    if not candidates:
        return []
    referenced = await referenced_keys(db, [item.key for item in candidates])
    return [item for item in candidates if item.key not in referenced]


def delete_new_object(storage: StorageBackend, key: str) -> bool:
    """Delete the object just created as compensation; return whether it is already absent.

    Only an upload request whose registration failed may call this for its own new key.
    Callers must not use it for business objects or pre-existing objects; this function
    does not query the database.
    """
    validate_key(key)
    try:
        storage.delete(key)
        return True
    except StorageNotFound:
        return True
    except StorageError:
        return False


async def _lock_staged(db: AsyncSession, key: str) -> StoredObject | None:
    """Lock a single registration row; return it only while still staged.

    Under PostgreSQL, ``FOR UPDATE`` uses the same row lock as business ``mark_committed``;
    when SQLite does not support row-lock syntax, SQLAlchemy ignores it and SQLite's own
    write transactions serialize.
    """
    row = (
        await db.exec(
            select(StoredObject)
            .where(col(StoredObject.key) == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None or row.state != "staged":
        return None
    return row


async def cleanup_unreferenced_staged(
    db: AsyncSession,
    storage: StorageBackend,
    *,
    dry_run: bool = True,
    limit: int = 100,
    allow_evidence: bool = False,
) -> CleanupResult:
    """Explicitly clean up unreferenced staged objects; lists only by default (dry_run).

    For every candidate, lock the registration row first and re-query business
    references while holding the lock; delete from OSS and mark deleted only when the
    object is still staged and unreferenced. Evidence objects are not physically deleted
    by default (retention reason ``evidence_protected``), and no CLI override is provided.
    There is no scheduled job, so evidence does not expire automatically.

    Cross-system boundary: OSS deletion and database commit cannot commit atomically. If
    OSS deletion succeeds but the commit fails, the registration row rolls back and stays
    staged; the next cleanup treats the missing OSS object as deleted and records
    ``deleted``, but that window cannot be eliminated by the database transaction. Callers
    should treat this function as a standalone cleanup task and must not pile up
    uncommitted business writes in the same Session beforehand.
    """
    # dry-run is read-only listing and must not lock candidate rows and affect business references; only actual deletion locks.
    candidates = await list_unreferenced_staged(
        db, limit=limit, for_update=not dry_run
    )
    keys = [item.key for item in candidates]
    result = CleanupResult(dry_run=dry_run, candidates=keys)
    if dry_run:
        return result
    if not keys:
        # Batch locking may have locked referenced rows later filtered out; release the transaction when there are no candidates.
        await db.rollback()
        return result

    for key in keys:
        row = await _lock_staged(db, key)
        if row is None:
            # Another transaction committed/deleted it after listing; do not continue from the stale snapshot.
            result.retained.append({"key": key, "reason": "state_changed"})
            await db.commit()
            continue
        lease = (await db.exec(select(UploadLease).where(col(UploadLease.key) == key))).one_or_none()
        if lease is not None:
            expiry = lease.expires_at if lease.expires_at.tzinfo else lease.expires_at.replace(tzinfo=UTC)
            if expiry > datetime.now(UTC):
                result.retained.append({"key": key, "reason": "upload_lease_active"})
                await db.commit()
                continue
        if row.bucket_role == "evidence" and not allow_evidence:
            # Evidence has no default TTL; do not physically delete it even when staged and currently unreferenced.
            result.retained.append({"key": key, "reason": "evidence_protected"})
            await db.commit()
            continue
        # Re-confirm references while holding the lock. The business path locks the same
        # registration row inside the transaction inserting the reference, so a new
        # reference committed between the query and deletion cannot be missed here.
        still_referenced = await referenced_keys(db, [key])
        if still_referenced:
            result.retained.append({"key": key, "reason": "referenced"})
            await db.commit()
            continue
        try:
            storage.delete(key)
        except StorageNotFound:
            pass
        except StorageError as exc:
            result.errors.append(f"{key}: {type(exc).__name__}")
            result.retained.append({"key": key, "reason": "delete_failed"})
            await db.commit()
            continue
        row.state = "deleted"
        row.deleted_at = datetime.now(UTC)
        try:
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - cross-system boundary; record only the exception type
            await db.rollback()
            result.errors.append(f"{key}: commit_{type(exc).__name__}")
            result.retained.append({"key": key, "reason": "commit_failed"})
            continue
        result.deleted.append(key)
    return result

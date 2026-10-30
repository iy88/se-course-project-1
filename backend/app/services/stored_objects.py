"""对象登记、业务引用与 staged 回收。

约束：
- 上传成功后先登记为 ``staged``；登记提交失败只允许补偿删除本次刚创建的对象。
- 业务事务引用对象时把对应登记改为 ``committed``；对象被引用后不得由本模块
  自动物理删除。
- 回收只处理 ``staged``，并且每次都用业务表实时查询确认无引用；证据没有默认
  TTL，也没有定时任务，必须由操作者显式调用并默认只列出。
- 清理与业务 ``mark_committed`` 对同一登记行加行锁（PostgreSQL ``FOR UPDATE``），
  先锁行再查引用、再删对象、最后标记 ``deleted``。业务事务若在清理提交后才拿到
  锁，会看到 ``deleted`` 并失败回滚，不能继续引用已物理删除的对象。
- 证据对象默认禁止本模块物理删除；保留原因记为 ``evidence_protected``。这是保守
  策略，不替代负责人的证据保留期限决定。
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
    """登记对象已被回收；引用它的业务事务必须回滚，不能继续提交。"""

    def __init__(self, key: str | None = None) -> None:
        self.key = key
        super().__init__("对象已被回收，不能继续引用")


@dataclass
class CleanupResult:
    """一次 staged 回收的脱敏结果；key 仅供本机报告定位，不写入日志。"""

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
    """构造上传登记记录；不提交，由上传请求与登记一起提交。"""
    validate_key(key)
    namespace = namespace_for_key(key)
    bucket_role = bucket_role_for_namespace(namespace)
    if size_bytes < 0:
        raise ValueError("对象大小不能为负数")
    if not content_type or len(content_type) > 64:
        raise ValueError("对象 content_type 非法")
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
    """把刚上传成功的对象登记为 staged；调用方负责 commit。

    上传登记失败（本函数或 commit 抛错）时，调用方只能补偿删除本请求刚创建
    的那个 key，不得删除任何已存在对象。
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
    ref_id: int,
) -> int:
    """在业务事务内把 staged 对象转为 committed；不 commit。

    不存在登记的历史对象保持原状，不影响既有业务；已 committed 的共享对象不会
    被后来的引用覆盖。对每个登记行按 key 排序后 ``SELECT ... FOR UPDATE``，与
    清理路径使用同一行锁：若清理已标记 ``deleted``，本函数抛出
    :class:`StoredObjectUnavailable`，调用方必须让整个业务事务回滚。

    调用方应在插入业务引用（商品图片/举报证据）的同一事务内调用；行锁一直持有
    到该事务 commit/rollback。
    """
    if ref_type not in _REF_TYPES:
        raise ValueError("非法对象引用类型")
    if not isinstance(ref_id, int) or ref_id <= 0:
        raise ValueError("非法对象引用 ID")
    unique: list[str] = []
    for key in keys:
        if not key or key in unique:
            continue
        try:
            validate_key(key)
        except StorageInvalidKey:
            # 历史数据可能含非标准 key；登记是附加安全信息，不能让它阻断业务。
            continue
        unique.append(key)
    if not unique:
        return 0
    committed = 0
    # 排序后逐个加锁，避免多 key 并发时出现不确定的加锁顺序。
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
        # 在业务事务内发出 UPDATE，让约束/连接错误在 mark_committed 处暴露。
        await db.flush()
    return committed


async def referenced_keys(db: AsyncSession, keys: Iterable[str]) -> set[str]:
    """用业务表实时确认哪些 key 仍被引用。

    ``product_images.file_key`` 与举报/补充证据 JSON 数组是当前业务引用来源。
    查询不依赖登记状态，因此即使登记失败或历史对象没有登记，也不会误删引用。
    """
    unique = sorted({key for key in keys if key})
    if not unique:
        return set()

    found: set[str] = set()
    rows = await db.exec(select(col(ProductImage.file_key)).where(col(ProductImage.file_key).in_(unique)))
    found.update(str(value) for value in rows if value)

    dialect = db.get_bind().dialect.name
    for table in (Report.__tablename__, ReportSupplement.__tablename__):
        if dialect == "postgresql":
            statement = text(
                f"SELECT DISTINCT value FROM {table}, "
                f"jsonb_array_elements_text({table}.evidence_keys) AS value "
                "WHERE value IN :keys"
            )
        else:
            statement = text(
                f"SELECT DISTINCT value FROM {table}, json_each({table}.evidence_keys) "
                "WHERE value IN :keys"
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
    """列出已确认无业务引用的 staged 对象；不设时间阈值、不删除。

    ``for_update`` 仅由回收流程的实际删除路径使用：用 ``SKIP LOCKED`` 锁定当前
    未被其它事务占用的候选登记行；已被业务事务锁定的行会被跳过，不会被清理。
    加锁后到事务结束前，后到的业务 ``mark_committed`` 会等待同一行锁。只读列举
    不应传 ``for_update``。
    """
    if limit <= 0:
        raise ValueError("limit 必须为正数")
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
    """补偿删除本次刚创建的对象；返回是否已不存在。

    只允许上传请求在登记失败时对自己的新 key 调用。调用方不得把它用于业务
    对象或已存在对象；本函数不查数据库。
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
    """锁定单个登记行；只有仍为 staged 才返回。

    PostgreSQL 下 ``FOR UPDATE`` 与业务 ``mark_committed`` 使用同一行锁；SQLite
    不支持行锁语法时由 SQLAlchemy 忽略，SQLite 的写事务本身串行化。
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
    """显式清理无引用 staged 对象；默认只列出（dry_run）。

    每个候选对象都先锁登记行，再在锁内重新查询业务引用；只有仍为 staged 且无
    引用时才删除 OSS 并标记 deleted。证据对象默认不物理删除（保留原因
    ``evidence_protected``），不提供 CLI 放宽入口。没有定时任务，证据不会自动
    过期。

    跨系统边界：OSS 删除与数据库 commit 不能原子提交。若 OSS 已删除而 commit
    失败，登记行会随事务回滚仍为 staged；下次清理把 OSS 不存在视为已删除并补记
    ``deleted``，但该窗口无法由数据库事务消除。调用方应把本函数当作独立清理任务，
    不要在同一个 Session 里预先堆积未提交业务写。
    """
    # dry-run 是只读列举，不能为候选行加锁而影响业务引用；实际删除才加锁。
    candidates = await list_unreferenced_staged(
        db, limit=limit, for_update=not dry_run
    )
    keys = [item.key for item in candidates]
    result = CleanupResult(dry_run=dry_run, candidates=keys)
    if dry_run:
        return result
    if not keys:
        # 批量加锁可能锁住了被引用但最终被过滤掉的行；无候选时释放事务。
        await db.rollback()
        return result

    for key in keys:
        row = await _lock_staged(db, key)
        if row is None:
            # 列出后已被其它事务提交/删除，不能按旧快照继续处理。
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
            # 证据无默认 TTL；即使 staged 且当前无引用也不物理删除。
            result.retained.append({"key": key, "reason": "evidence_protected"})
            await db.commit()
            continue
        # 锁内再次确认引用。业务路径在插入引用的事务里先锁同一登记行，因此不会
        # 出现“查询后、删除前”被新业务引用而未被本事务看到的提交。
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
        except Exception as exc:  # noqa: BLE001 - 跨系统边界，只记录异常类型
            await db.rollback()
            result.errors.append(f"{key}: commit_{type(exc).__name__}")
            result.retained.append({"key": key, "reason": "commit_failed"})
            continue
        result.deleted.append(key)
    return result

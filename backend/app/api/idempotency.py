"""Optional ``Idempotency-Key`` support for connection-reset-prone writes.

Without the header the endpoint keeps its legacy behaviour exactly. With the
header, one (user, operation, key) produces one business result:

* PostgreSQL uses a transaction-scoped advisory lock, then reads/creates the
  record in the *same* transaction as the business write and audit. Concurrent
  requests with the same key block, then replay the committed result.
* SQLite (offline tests only) serializes the same key with a process-local lock
  and the unique constraint. It is not a multi-process production guarantee.

A key reused with a different canonical request body is rejected with 409.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.models.realtime import IdempotencyRecord

_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# SQLite has no cross-process advisory lock. A single process lock serializes
# offline/test idempotency keys without an unbounded per-key dictionary.
_SQLITE_LOCK = asyncio.Lock()


class IdempotencyReplay:
    def __init__(self, status_code: int, response: Any) -> None:
        self.status_code = status_code
        self.response = response


def request_digest(body: Any) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_key(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or not _KEY_RE.fullmatch(candidate):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key 格式无效")
    return candidate


class IdempotencyGuard:
    def __init__(self, db: AsyncSession, *, user_id: int, operation: str, key: str | None, body: Any) -> None:
        self.db = db
        self.user_id = user_id
        self.operation = operation
        self.key = key
        self.digest = request_digest(body) if key is not None else ""
        self.replay: IdempotencyReplay | None = None
        self._lock: asyncio.Lock | None = None
        self._sqlite = db.bind is not None and db.bind.dialect.name == "sqlite"

    @property
    def enabled(self) -> bool:
        return self.key is not None

    async def __aenter__(self) -> Self:
        if not self.enabled:
            return self
        if self._sqlite:
            await _SQLITE_LOCK.acquire()
            self._lock = _SQLITE_LOCK
        else:
            # Transaction-scoped: released automatically by commit/rollback.
            await self.db.exec(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                params={"scope": f"idempotency:{self.user_id}:{self.operation}:{self.key}"},
            )
        try:
            await self._load()
        except BaseException:
            if self._lock is not None:
                self._lock.release()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._lock is not None:
            self._lock.release()

    async def _load(self) -> None:
        now = datetime.now(UTC)
        row = (
            await self.db.exec(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == self.user_id,
                    IdempotencyRecord.operation == self.operation,
                    IdempotencyRecord.key == self.key,
                )
            )
        ).first()
        if row is None:
            return
        if row.expires_at is not None and row.expires_at.tzinfo is None:
            row.expires_at = row.expires_at.replace(tzinfo=UTC)
        if row.expires_at <= now:
            await self.db.delete(row)
            await self.db.flush()
            return
        if row.request_hash != self.digest:
            raise HTTPException(status.HTTP_409_CONFLICT, "同一 Idempotency-Key 使用了不同的请求内容")
        self.replay = IdempotencyReplay(int(row.status_code), row.response)

    async def complete(self, *, status_code: int, response: Any) -> None:
        if not self.enabled:
            return
        settings = get_settings()
        payload = jsonable_encoder(response)
        self.db.add(IdempotencyRecord(
            user_id=self.user_id,
            operation=self.operation,
            key=self.key,
            request_hash=self.digest,
            status_code=int(status_code),
            response=payload,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.idempotency_ttl_hours),
        ))
        await self.db.flush()


def guard(db: AsyncSession, user_id: int, operation: str, key: str | None, body: Any) -> IdempotencyGuard:
    return IdempotencyGuard(db, user_id=user_id, operation=operation, key=key, body=body)


async def cleanup_expired(batch_size: int = 1000, *, max_batches: int = 10) -> int:
    """Delete expired idempotency rows in bounded transactions.

    Called by a Taskiq maintenance task. A finite batch cap keeps one task
    invocation from monopolizing a SQL connection or growing an unbounded
    transaction; the next scheduled run continues the cleanup.
    """
    from app.db.session import get_sessionmaker

    deleted = 0
    for _ in range(max(1, max_batches)):
        async with get_sessionmaker()() as db, db.begin():
            ids = (
                await db.exec(
                    select(IdempotencyRecord.id)
                    .where(IdempotencyRecord.expires_at <= datetime.now(UTC))
                    .limit(max(1, batch_size))
                )
            ).all()
            if not ids:
                break
            await db.exec(delete(IdempotencyRecord).where(IdempotencyRecord.id.in_(ids)))
            deleted += len(ids)
        if len(ids) < max(1, batch_size):
            break
    return deleted

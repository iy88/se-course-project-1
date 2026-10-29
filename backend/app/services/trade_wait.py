"""单方完成确认等待计时（BR-05、TR-14、D-51）。

所有时间按 UTC 解释；SQLite 读出的 datetime 可能不带时区，统一补齐为 UTC 后再比较。
暂停只冻结“有效等待”的累计时间，不改变交易状态、当前确认或有效约定。
"""

from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.models import Trade


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite 可能返回 naive datetime；统一按 UTC 处理，避免 aware/naive 比较异常。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def timeout_seconds() -> int:
    return int(get_settings().trade_confirm_timeout_days) * 24 * 60 * 60


def wait_remaining_seconds(trade: Trade, now: datetime | None = None) -> int | None:
    """当前有效等待的剩余秒数；无等待返回 None，已耗尽返回 0。"""
    timeout = timeout_seconds()
    paused_at = as_utc(trade.confirm_wait_paused_at)
    if paused_at is not None:
        stored = trade.confirm_wait_remaining_seconds
        if stored is not None:
            return max(0, int(stored))
        started = as_utc(trade.confirm_wait_started_at)
        if started is None:
            return None
        return max(0, int(timeout - (paused_at - started).total_seconds()))

    started = as_utc(trade.confirm_wait_started_at)
    if started is None:
        return None
    reference = now or now_utc()
    if trade.frozen:
        # 兼容升级前已冻结、尚无暂停字段的记录：按冻结时刻截断，绝不按自然墙钟累计。
        reference = as_utc(trade.frozen_at) or reference
    return max(0, int(timeout - (reference - started).total_seconds()))


def pause_wait_for_freeze(trade: Trade, now: datetime | None = None) -> int | None:
    """冻结前保存已等待进度与剩余时间；重复冻结保持原暂停起点，不重置。"""
    if trade.confirm_wait_paused_at is not None:
        return trade.confirm_wait_remaining_seconds
    started = as_utc(trade.confirm_wait_started_at)
    if started is None:
        return None
    current = now or now_utc()
    remaining = max(0, int(timeout_seconds() - (current - started).total_seconds()))
    trade.confirm_wait_remaining_seconds = remaining
    trade.confirm_wait_paused_at = current
    return remaining


def resume_wait_after_unfreeze(trade: Trade, *, eligible: bool, now: datetime | None = None) -> int | None:
    """仅当交易仍进行中且保留当前确认时续算剩余时间；否则结束旧轮暂停状态。"""
    paused_at = as_utc(trade.confirm_wait_paused_at)
    stored = trade.confirm_wait_remaining_seconds
    started = as_utc(trade.confirm_wait_started_at)
    if paused_at is None and stored is None:
        return None
    if not eligible:
        clear_wait_state(trade)
        return None

    remaining = stored
    if remaining is None:
        # 旧库升级后可能只有 frozen_at 与 started_at，没有显式剩余值。
        base = as_utc(trade.frozen_at) or paused_at or now_utc()
        if started is None:
            clear_wait_state(trade)
            return None
        remaining = max(0, int(timeout_seconds() - (base - started).total_seconds()))
    remaining = max(0, int(remaining))
    current = now or now_utc()
    trade.confirm_wait_started_at = current - timedelta(seconds=max(0, timeout_seconds() - remaining))
    trade.confirm_wait_paused_at = None
    trade.confirm_wait_remaining_seconds = None
    return remaining


def clear_wait_state(trade: Trade) -> None:
    """结束当前等待轮次（确认被清空、争议、变更生效、结束或管理恢复）。"""
    trade.confirm_wait_started_at = None
    trade.confirm_wait_paused_at = None
    trade.confirm_wait_remaining_seconds = None


def iso_utc(value: datetime | None) -> str | None:
    normalized = as_utc(value)
    return normalized.isoformat() if normalized else None

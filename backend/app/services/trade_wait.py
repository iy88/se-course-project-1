"""Wait timer for unilateral completion confirmation (BR-05, TR-14, D-51).

All times are interpreted as UTC; datetimes read from SQLite may lack a timezone, so
they are normalized to UTC before comparison. Pausing freezes only the accumulated
"effective wait" time and does not change the trade state, current confirmation, or
effective agreement.
"""

from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.models import Trade


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite may return naive datetimes; treat all as UTC to avoid aware/naive comparison errors."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def timeout_seconds() -> int:
    return int(get_settings().trade_confirm_timeout_days) * 24 * 60 * 60


def wait_remaining_seconds(trade: Trade, now: datetime | None = None) -> int | None:
    """Remaining seconds of the current effective wait; None when there is no wait, 0 when exhausted."""
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
        # Records frozen before the upgrade with no pause fields: cut off at the freeze instant and never accrue wall-clock time.
        reference = as_utc(trade.frozen_at) or reference
    return max(0, int(timeout - (reference - started).total_seconds()))


def pause_wait_for_freeze(trade: Trade, now: datetime | None = None) -> int | None:
    """Save elapsed progress and remaining time before freezing; repeated freezes keep the original pause point and do not reset it."""
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
    """Resume the remaining time only when the trade is still in progress and retains its current confirmation; otherwise end the old paused round."""
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
        # After upgrading an old database, only frozen_at and started_at may exist with no explicit remaining value.
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
    """End the current wait round (confirmation cleared, dispute, change effective, completion, or administrative restoration)."""
    trade.confirm_wait_started_at = None
    trade.confirm_wait_paused_at = None
    trade.confirm_wait_remaining_seconds = None


def iso_utc(value: datetime | None) -> str | None:
    normalized = as_utc(value)
    return normalized.isoformat() if normalized else None

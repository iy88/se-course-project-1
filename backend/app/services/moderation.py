"""Administrative disposal actions: ban/lift and their cascades (DT-03, BR-32/33, TR-09/10)."""
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AccountRestriction, CompletionConfirmation, Product, Trade, User
from app.models.enums import (
    AccountStatus,
    DisposalMessageKind,
    DisposalMessageRole,
    ProductStatus,
    RestrictionStatus,
    TradeStatus,
)
from app.services import cases as case_service
from app.services import trades as trade_service
from app.services.notifications import notify
from app.services.trade_wait import (
    as_utc,
    pause_wait_for_freeze,
    resume_wait_after_unfreeze,
)


def now_utc() -> datetime:
    return datetime.now(UTC)


async def freeze_trade(db: AsyncSession, trade: Trade, reason: str, case_id: int | None, admin_id: int | None) -> None:
    """Freeze the entire trade progress (BR-33): suspend both parties' actions and pause an existing unilateral-confirmation wait (D-51).

    Repeated freezes return immediately without resetting the freeze start, pause start, or remaining time.
    """
    locked = await trade_service.lock_product_then_trade(db, trade.id, trade.product_id)
    if locked is None:
        raise HTTPException(404, '交易不存在')
    trade = locked
    if trade.status in (TradeStatus.COMPLETED.value, TradeStatus.TERMINATED.value) or trade.frozen:
        return
    now = now_utc()
    remaining = pause_wait_for_freeze(trade, now)
    trade.frozen = True
    trade.frozen_reason = reason
    trade.frozen_at = now
    trade.frozen_by_id = admin_id
    trade.frozen_case_id = case_id
    pause_note = (
        f"；完成确认等待已暂停，保留当前确认，剩余约 {max(1, remaining // 3600)} 小时"
        if remaining is not None
        else ""
    )
    await trade_service._record_transition(
        db, trade, trade.status, trade.status, "trade_frozen", reason=reason + pause_note
    )
    await notify(
        db, [trade.buyer_id, trade.seller_id], "trade_frozen", f"交易#{trade.id}已被冻结",
        f"原因：{reason}。冻结期间双方交易操作与双方间 IM 暂停，可通过处置沟通与管理员说明。"
        + ("原完成确认等待计时已暂停，解除后按剩余时间续算。" if remaining is not None else ""),
        link_type="trade", link_id=trade.id,
    )


async def _participant_ban_active(db: AsyncSession, trade: Trade) -> bool:
    """Either party still has an active account ban (BR-33: other active restrictions remain in effect)."""
    user_ids = (trade.buyer_id, trade.seller_id)
    restriction = (await db.exec(
        select(col(AccountRestriction.id))
        .where(
            col(AccountRestriction.user_id).in_(user_ids),
            col(AccountRestriction.type) == "ban",
            col(AccountRestriction.status) == RestrictionStatus.ACTIVE.value,
        )
        .limit(1)
    )).first()
    if restriction is not None:
        return True
    banned = (await db.exec(
        select(col(User.id))
        .where(col(User.id).in_(user_ids), col(User.status) == AccountStatus.BANNED.value)
        .limit(1)
    )).first()
    return banned is not None


async def unfreeze_trade(db: AsyncSession, trade: Trade, reason: str, admin_id: int) -> None:
    """Lift a freeze with a basis while other active restrictions remain (BR-33); only an eligible active confirmation resumes its remaining wait (D-51)."""
    locked = await trade_service.lock_product_then_trade(db, trade.id, trade.product_id)
    if locked is None:
        raise HTTPException(404, '交易不存在')
    trade = locked
    if not trade.frozen:
        return
    # D-51/BR-33: do not unfreeze manually while active restrictions such as bans remain, and never let the timer accrue during a ban.
    if await _participant_ban_active(db, trade):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "交易一方仍处于账户封禁，须先依法解除封禁后再解冻",
        )
    from app.models import TradeTransition

    # Records frozen before the upgrade with no pause fields: backfill the freeze instant as the pause point so unfreezing does not incorrectly use wall-clock time.
    if trade.confirm_wait_paused_at is None and trade.confirm_wait_remaining_seconds is None:
        frozen_base = as_utc(trade.frozen_at)
        if frozen_base is not None:
            pause_wait_for_freeze(trade, frozen_base)
    trade.frozen = False
    has_current_confirmation = (await db.exec(
        select(col(CompletionConfirmation.id)).where(
            col(CompletionConfirmation.trade_id) == trade.id,
            col(CompletionConfirmation.is_current).is_(True),
        )
    )).first()
    eligible = trade.status == TradeStatus.IN_PROGRESS.value and has_current_confirmation is not None
    had_pause = trade.confirm_wait_paused_at is not None or trade.confirm_wait_remaining_seconds is not None
    remaining = resume_wait_after_unfreeze(trade, eligible=eligible, now=now_utc())
    resume_note = ""
    if remaining is not None:
        resume_note = f"；原完成确认仍有效，等待计时已续算，剩余约 {max(1, remaining // 3600)} 小时"
    elif had_pause:
        resume_note = "；当前状态或确认不满足续算条件，旧等待不恢复"
    db.add(
        TradeTransition(
            trade_id=trade.id,
            from_status=trade.status,
            to_status=trade.status,
            actor_id=admin_id,
            actor_role="admin",
            trigger="trade_unfrozen",
            reason=reason + resume_note,
        )
    )
    await notify(
        db, [trade.buyer_id, trade.seller_id], "trade_unfrozen", f"交易#{trade.id}冻结已解除",
        f"原因：{reason}。其他有效限制（如有）继续适用。" + resume_note,
        link_type="trade", link_id=trade.id,
    )


async def restrict_product_display(db: AsyncSession, product: Product, reason: str, case_id: int | None) -> None:
    """Revoke public access for a violation (TR-09): display restriction stays separate from lifecycle; close pending-acceptance requests with a reason."""
    if product.display_restricted:
        return
    product.display_restricted = True
    product.display_restricted_reason = reason
    product.display_restricted_at = now_utc()
    product.display_restricted_case_id = case_id
    closed = await trade_service.close_pending_requests_for_product(
        db, product.id, trade_service.DISPLAY_REVOKED_REASON
    )
    for trade in closed:
        await notify(
            db, [trade.buyer_id], "request_closed", "您的购买请求已关闭",
            f"商品「{product.title}」因平台处置停止公开，对应请求已关闭。",
            link_type="trade", link_id=trade.id,
        )


async def ban_user(
    db: AsyncSession,
    user: User,
    *,
    reason: str,
    basis: str | None,
    case_id: int | None,
    admin_id: int,
) -> AccountRestriction:
    """Ban (BR-32/DT-03): block writes while preserving reads; freeze their in-progress trades; stop public display of their products."""
    if user.status == AccountStatus.BANNED.value:
        existing = (await db.exec(
            select(AccountRestriction).where(
                col(AccountRestriction.user_id) == user.id, col(AccountRestriction.status) == RestrictionStatus.ACTIVE.value
            )
        )).first()
        if existing:
            return existing
    restriction = AccountRestriction(
        user_id=user.id,
        type="ban",
        status=RestrictionStatus.ACTIVE.value,
        reason=reason,
        basis=basis,
        case_id=case_id,
        created_by_id=admin_id,
    )
    db.add(restriction)
    user.status = AccountStatus.BANNED.value
    # D-52: before ban side effects, close all pending-acceptance requests where the
    # user is buyer or seller; the reason is fixed as "related account banned", both
    # parties are notified, branches are archived, and accepted trades are not closed as requests.
    closed_pending = await trade_service.close_pending_requests_for_user(
        db, user.id, reason=trade_service.BANNED_PENDING_REASON
    )
    # DT-03: banning either trade party freezes the whole accepted trade progress (pausing the timer when a unilateral confirmation exists)
    result = await db.exec(
        select(Trade).where(
            ((col(Trade.buyer_id) == user.id) | (col(Trade.seller_id) == user.id)),
            col(Trade.status).in_(trade_service.LOCKING_STATUSES),
        )
    )
    for trade in result:
        await freeze_trade(db, trade, f"交易方账户被平台封禁：{reason}", case_id, admin_id)
    # DT-03: the banned account's products stop public display (pending-acceptance requests were already closed with the ban reason in the previous step).
    # Products in a trade may also be publicly accessible and must have display revoked too; lifecycle and lock stay unchanged.
    products = await db.exec(
        select(Product).where(
            col(Product.seller_id) == user.id,
            col(Product.status).in_([ProductStatus.LISTED.value, ProductStatus.IN_TRANSACTION.value]),
        )
    )
    for product in products:
        await restrict_product_display(db, product, f"发布者账户被平台封禁：{reason}", case_id)
    await db.flush()
    if case_id:
        from app.models import DisposalCase

        case = await db.get(DisposalCase, case_id)
        if case:
            await case_service.add_case_message(
                db, case, sender_id=None, role=DisposalMessageRole.SYSTEM,
                kind=DisposalMessageKind.NOTICE,
                content=f"账户已被封禁。原因：{reason}",
            )
    await notify(
        db, [user.id], "disposal", "账户已被平台封禁",
        f"原因：{reason}。封禁期间禁止发布、交易、评论等写操作，可浏览原有公开内容并通过处置沟通提交申辩。"
        + (f"已关闭本人参与的 {len(closed_pending)} 条待接受请求。" if closed_pending else ""),
        link_type="case", link_id=case_id,
    )
    return restriction


async def unban_user(
    db: AsyncSession,
    user: User,
    *,
    lift_reason: str,
    case_id: int | None,
    admin_id: int,
) -> int:
    """Lift a ban (TR-10): restore original permissions and display stopped by the disposal; previously unlisted products do not become listed automatically."""
    result = await db.exec(
        select(AccountRestriction).where(
            col(AccountRestriction.user_id) == user.id, col(AccountRestriction.status) == RestrictionStatus.ACTIVE.value
        )
    )
    restrictions = list(result)
    if not restrictions:
        return 0
    now = now_utc()
    for restriction in restrictions:
        restriction.status = RestrictionStatus.LIFTED.value
        restriction.lifted_at = now
        restriction.lifted_by_id = admin_id
        restriction.lift_reason = lift_reason
    user.status = AccountStatus.NORMAL.value
    lifted_case_ids = {r.case_id for r in restrictions if r.case_id}
    # Restore only products whose display stopped because of the bans lifted now (clear only the restriction flag; do not change lifecycle state)
    products = await db.exec(
        select(Product).where(
            col(Product.seller_id) == user.id,
            col(Product.display_restricted).is_(True),
            col(Product.display_restricted_case_id).in_(lifted_case_ids or {0}),
        )
    )
    for product in products:
        product.display_restricted = False
    # Unfreeze trades frozen because of this account ban
    trades = await db.exec(
        select(Trade).where(
            ((col(Trade.buyer_id) == user.id) | (col(Trade.seller_id) == user.id)),
            col(Trade.frozen).is_(True),
            col(Trade.frozen_case_id).in_(lifted_case_ids or {0}),
        )
    )
    for trade in trades:
        try:
            await unfreeze_trade(db, trade, f"账户封禁解除：{lift_reason}", admin_id)
        except HTTPException:
            # The other trade party is still banned: this ban lift still takes effect,
            # but the trade stays frozen until the other active restriction is lifted and
            # the claiming administrator unfreezes it with a basis (BR-33).
            continue
    if case_id:
        from app.models import DisposalCase

        case = await db.get(DisposalCase, case_id)
        if case:
            await case_service.add_case_message(
                db, case, sender_id=None, role=DisposalMessageRole.SYSTEM,
                kind=DisposalMessageKind.NOTICE,
                content=f"账户封禁已解除。原因：{lift_reason}",
            )
    await notify(
        db, [user.id], "disposal", "账户封禁已解除",
        f"原因：{lift_reason}。原权限已恢复；原非在售商品不自动上架。",
        link_type="case", link_id=case_id,
    )
    await db.flush()
    return len(restrictions)

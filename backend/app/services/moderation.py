"""管理处置动作：封禁/解除及联动（DT-03、BR-32/33、TR-09/10）。"""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services import conversations as conversation_service
from app.services import trades as trade_service
from app.services.notifications import notify
from app.services.trade_wait import as_utc, pause_wait_for_freeze, resume_wait_after_unfreeze


def now_utc() -> datetime:
    return datetime.now(UTC)


async def freeze_trade(db: AsyncSession, trade: Trade, reason: str, case_id: int | None, admin_id: int | None) -> None:
    """冻结整个交易进度（BR-33）：暂停双方操作，已有单方确认时暂停原等待（D-51）。

    重复冻结直接返回，不重置冻结开始、暂停开始或剩余时间。
    """
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
    """交易任一方仍有生效账户封禁（BR-33：其他有效限制继续生效）。"""
    user_ids = (trade.buyer_id, trade.seller_id)
    restriction = await db.scalar(
        select(AccountRestriction.id)
        .where(
            AccountRestriction.user_id.in_(user_ids),
            AccountRestriction.type == "ban",
            AccountRestriction.status == RestrictionStatus.ACTIVE.value,
        )
        .limit(1)
    )
    if restriction is not None:
        return True
    banned = await db.scalar(
        select(User.id)
        .where(User.id.in_(user_ids), User.status == AccountStatus.BANNED.value)
        .limit(1)
    )
    return banned is not None


async def unfreeze_trade(db: AsyncSession, trade: Trade, reason: str, admin_id: int) -> None:
    """有依据解除冻结：其他有效限制保留（BR-33）；仅符合条件的有效确认续算剩余（D-51）。"""
    if not trade.frozen:
        return
    # D-51/BR-33：封禁等有效限制未解除前不得手工解冻，更不能让计时在禁令期间恢复累计。
    if await _participant_ban_active(db, trade):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "交易一方仍处于账户封禁，须先依法解除封禁后再解冻",
        )
    from app.models import TradeTransition

    # 升级前已冻结、尚无暂停字段的记录：以冻结时刻为暂停点补齐，避免解冻时误按自然墙钟。
    if trade.confirm_wait_paused_at is None and trade.confirm_wait_remaining_seconds is None:
        frozen_base = as_utc(trade.frozen_at)
        if frozen_base is not None:
            pause_wait_for_freeze(trade, frozen_base)
    trade.frozen = False
    has_current_confirmation = await db.scalar(
        select(CompletionConfirmation.id).where(
            CompletionConfirmation.trade_id == trade.id,
            CompletionConfirmation.is_current.is_(True),
        )
    )
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
    """违规撤销公开访问（TR-09）：展示限制与生命周期分开；关闭待接受请求并注明原因。"""
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
    """封禁（BR-32/DT-03）：禁写保读；冻结其进行中交易；其商品停止公开展示。"""
    if user.status == AccountStatus.BANNED.value:
        existing = await db.scalar(
            select(AccountRestriction).where(
                AccountRestriction.user_id == user.id, AccountRestriction.status == RestrictionStatus.ACTIVE.value
            )
        )
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
    # D-52：封禁副作用前先关闭其作为买方或卖方参与的全部待接受请求；
    # 原因固定为“相关账户被封禁”，通知双方并归档分支，已接受交易不按请求关闭。
    closed_pending = await trade_service.close_pending_requests_for_user(
        db, user.id, reason=trade_service.BANNED_PENDING_REASON
    )
    # DT-03：封禁任一交易方 → 冻结整个已接受交易进度（已有单方确认时暂停计时）
    result = await db.execute(
        select(Trade).where(
            ((Trade.buyer_id == user.id) | (Trade.seller_id == user.id)),
            Trade.status.in_(trade_service.LOCKING_STATUSES),
        )
    )
    for trade in result.scalars():
        await freeze_trade(db, trade, f"交易方账户被平台封禁：{reason}", case_id, admin_id)
    # DT-03：封禁账户的商品 → 停止公开展示（待接受请求已在上一步按封禁原因关闭）。
    # 交易中商品同样可能被公开访问，必须一并撤销展示；生命周期与锁单保持不变。
    products = await db.execute(
        select(Product).where(
            Product.seller_id == user.id,
            Product.status.in_([ProductStatus.LISTED.value, ProductStatus.IN_TRANSACTION.value]),
        )
    )
    for product in products.scalars():
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
    """解除封禁（TR-10）：恢复原权限及因处置停止的展示；原非在售商品不自动变为在售。"""
    result = await db.execute(
        select(AccountRestriction).where(
            AccountRestriction.user_id == user.id, AccountRestriction.status == RestrictionStatus.ACTIVE.value
        )
    )
    restrictions = list(result.scalars())
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
    # 仅恢复因本次解除的封禁而停止展示的商品（只解除限制标记，不改生命周期状态）
    products = await db.execute(
        select(Product).where(
            Product.seller_id == user.id,
            Product.display_restricted.is_(True),
            Product.display_restricted_case_id.in_(lifted_case_ids or {0}),
        )
    )
    for product in products.scalars():
        product.display_restricted = False
    # 解除因该账户封禁而冻结的交易
    trades = await db.execute(
        select(Trade).where(
            ((Trade.buyer_id == user.id) | (Trade.seller_id == user.id)),
            Trade.frozen.is_(True),
            Trade.frozen_case_id.in_(lifted_case_ids or {0}),
        )
    )
    for trade in trades.scalars():
        try:
            await unfreeze_trade(db, trade, f"账户封禁解除：{lift_reason}", admin_id)
        except HTTPException:
            # 另一交易方封禁仍生效：本次解封照常生效，但该交易继续冻结，
            # 待其他有效限制解除后由认领管理员有依据解冻（BR-33）。
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

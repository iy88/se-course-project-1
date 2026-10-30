"""交易全流程 API（FR-05/06/09；BR-01—09、4.15）：请求、锁单、约定、确认、取消、争议。"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.models import (
    CompletionConfirmation,
    Conversation,
    Product,
    Trade,
    TradeAgreement,
    TradeReview,
    User,
)
from app.models.enums import (
    AgreementStatus,
    CaseType,
    DisposalMessageKind,
    DisposalMessageRole,
    ProductStatus,
    TradeStatus,
)
from app.schemas.trade import (
    AgreementProposeIn,
    CancelIn,
    ConfirmationIn,
    DisputeIn,
    RejectIn,
    RequestCreateIn,
)
from app.services import audit as audit_service
from app.services import cases as case_service
from app.services import conversations as conversation_service
from app.services import trade_ops, trade_wait
from app.services import trades as trade_service
from app.services.notifications import notify
from app.services.permissions import has_active_frozen_trade

router = APIRouter(prefix="/trades", tags=["trades"])

CLOSED_BY_LOCK = trade_service.CLOSED_BY_LOCK


async def _party_trade(db: AsyncSession, trade_id: int, user_id: int) -> Trade:
    trade = await db.get(Trade, trade_id)
    if not trade or user_id not in (trade.buyer_id, trade.seller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    return trade


async def _ensure_not_frozen(trade: Trade) -> None:
    if trade.frozen:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "交易已被冻结，双方操作暂停，可查看历史或通过管理沟通处理")


async def _ensure_user_can_trade(db: AsyncSession, user_id: int) -> None:
    """BR-33：交易冻结暂停该用户全部交易操作，而非仅冻结对。

    IM 的 pair 作用域仍由 im_service.pair_frozen 单独负责；此处只判交易资格。
    """
    if await has_active_frozen_trade(db, user_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "账户存在有效交易冻结，暂停全部交易操作；无关商品合规编辑与无关 IM 不受影响",
        )


async def _ensure_trade_actors_eligible(db: AsyncSession, trade: Trade) -> None:
    """写操作前校验当前买卖双方全局交易资格（R3/BR-33）。"""
    for user_id in (trade.buyer_id, trade.seller_id):
        await _ensure_user_can_trade(db, user_id)


def _effective_agreement(trade: Trade, agreements: list[TradeAgreement]) -> TradeAgreement | None:
    if trade.current_agreement_id:
        for a in agreements:
            if a.id == trade.current_agreement_id and a.status == AgreementStatus.CONFIRMED.value:
                return a
    return None


async def _trade_out(db: AsyncSession, trade: Trade, user: User) -> dict:
    agreements = (
        await db.exec(select(TradeAgreement).where(col(TradeAgreement.trade_id) == trade.id).order_by(col(TradeAgreement.id)))
    ).all()
    confirms = (
        await db.exec(
            select(CompletionConfirmation).where(col(CompletionConfirmation.trade_id) == trade.id).order_by(col(CompletionConfirmation.id))
        )
    ).all()
    product = await db.get(Product, trade.product_id)
    conversation = (await db.exec(
        select(Conversation).where(col(Conversation.trade_id) == trade.id, col(Conversation.type) == "trade")
    )).first()
    my_role = "buyer" if trade.buyer_id == user.id else "seller"
    buyer = await db.get(User, trade.buyer_id)
    seller = await db.get(User, trade.seller_id)
    if buyer is None or seller is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易参与者不存在")
    effective = _effective_agreement(trade, list(agreements))
    pending_agreement = next((a for a in agreements if a.status == AgreementStatus.PROPOSED.value), None)
    my_current_confirm = any(c.confirmer_id == user.id and c.is_current for c in confirms)
    other_party_confirmed = any(
        c.confirmer_id != user.id and c.is_current for c in confirms
    )
    already_reviewed = (await db.exec(
        select(col(TradeReview.id)).where(col(TradeReview.trade_id) == trade.id, col(TradeReview.reviewer_id) == user.id)
    )).first()
    return {
        "id": trade.id,
        "status": trade.status,
        "frozen": trade.frozen,
        "frozen_reason": trade.frozen_reason if trade.frozen else None,
        "my_role": my_role,
        "product_id": trade.product_id,
        "product_title": product.title if product else "",
        "product_snapshot": trade.product_snapshot_json,
        "buyer": {"id": buyer.id, "display_name": buyer.display_name},
        "seller": {"id": seller.id, "display_name": seller.display_name},
        "request_note": trade.request_note,
        "close_reason": trade.close_reason,
        "conversation_id": conversation.id if conversation else None,
        "conversation_archived": conversation.archived if conversation else None,
        "agreement_stage": (
            "awaiting_agreement" if not effective else "awaiting_completion"
        )
        if trade.status == TradeStatus.IN_PROGRESS.value
        else None,
        "effective_agreement": (
            {
                "id": effective.id,
                "delivery_time": effective.delivery_time,
                "delivery_location": effective.delivery_location,
                "delivery_method": effective.delivery_method,
                "amount_cents": effective.amount_cents,
                "payment_method": effective.payment_method,
                "payment_timing": effective.payment_timing,
                "proposed_at": effective.proposed_at.isoformat() if effective.proposed_at else None,
            }
            if effective
            else None
        ),
        "pending_agreement": (
            {
                "id": pending_agreement.id,
                "proposer_id": pending_agreement.proposer_id,
                "round_no": pending_agreement.round_no,
                "delivery_time": pending_agreement.delivery_time,
                "delivery_location": pending_agreement.delivery_location,
                "delivery_method": pending_agreement.delivery_method,
                "amount_cents": pending_agreement.amount_cents,
                "payment_method": pending_agreement.payment_method,
                "payment_timing": pending_agreement.payment_timing,
                "proposed_at": pending_agreement.proposed_at.isoformat() if pending_agreement.proposed_at else None,
            }
            if pending_agreement
            else None
        ),
        "agreement_history": [
            {
                "id": a.id,
                "round_no": a.round_no,
                "proposer_id": a.proposer_id,
                "status": a.status,
                "delivery_time": a.delivery_time,
                "delivery_location": a.delivery_location,
                "delivery_method": a.delivery_method,
                "amount_cents": a.amount_cents,
                "payment_method": a.payment_method,
                "payment_timing": a.payment_timing,
                "proposed_at": a.proposed_at.isoformat() if a.proposed_at else None,
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            }
            for a in agreements
        ],
        "my_confirmed": my_current_confirm,
        "other_party_confirmed": other_party_confirmed,
        "confirm_wait_started_at": trade_wait.iso_utc(trade.confirm_wait_started_at),
        # D-51：暂停时刻与剩余秒数按契约暴露，供前端与管理端展示/刷新
        "confirm_wait_paused_at": trade_wait.iso_utc(trade.confirm_wait_paused_at),
        "confirm_wait_remaining_seconds": trade_wait.wait_remaining_seconds(trade),
        "confirmations": [
            {
                "id": c.id,
                "confirmer_id": c.confirmer_id,
                "note": c.note,
                "is_current": c.is_current,
                "confirmed_at": c.confirmed_at.isoformat() if c.confirmed_at else None,
            }
            for c in confirms
        ],
        "cancel_requested_by": trade.cancel_requested_by_id,
        "resolution_confirmed_by": trade.resolution_confirmed_by_id,
        "my_reviewed": already_reviewed is not None,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "accepted_at": trade.accepted_at.isoformat() if trade.accepted_at else None,
        "finished_at": trade.finished_at.isoformat() if trade.finished_at else None,
    }


@router.post("/requests")
async def create_request(body: RequestCreateIn, user: CurrentUser, db: DbSession) -> dict:
    """发起购买请求（BR-01/02）：不锁单；创建独立交易分支并通知卖方。

    请求虽不产生锁单，但必须先按商品行锁串行化，再读取商品可请求性、买卖双方
    资格与重复 pending。否则请求可在“看到 listed”后等待，等卖方 accept 已把商品
    置为 in_transaction 再插入 pending，破坏“已锁单商品不可再请求”的一致性。
    """
    ensure_can_write(user)
    # 与 accept/admin adjust 相同的第一把锁：商品。锁后读取到的状态才是当前状态。
    product = await trade_service.lock_product_for_update(db, body.product_id)
    if not product or product.status != ProductStatus.LISTED.value or product.display_restricted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或当前不可请求")
    if product.seller_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能购买本人发布的商品")
    # R3/BR-33：买方的全局交易资格与卖方的全局交易资格都须有效。
    await _ensure_user_can_trade(db, user.id)
    await _ensure_user_can_trade(db, product.seller_id)
    existing = await trade_service.find_pending_request(db, product.id, user.id)
    if existing:
        # 重复提交返回已有结果（6.5 重试一致）
        return {"id": existing.id, "detail": "您对该商品已有待接受的购买请求", "existing": True}
    product_id = product.id
    buyer_id = user.id
    try:
        trade = Trade(
            product_id=product_id,
            buyer_id=buyer_id,
            seller_id=product.seller_id,
            status=TradeStatus.PENDING_ACCEPTANCE.value,
            request_note=(body.note or "").strip() or None,
        )
        db.add(trade)
        await db.flush()
        branch = await conversation_service.create_trade_branch(db, trade.id, trade.buyer_id, trade.seller_id)
        await conversation_service.send_system_message(
            db,
            branch.id,
            f"买方发起了对商品「{product.title}」的购买请求，请卖方在交易分支或通知中心处理。",
        )
        await trade_ops.record_transition(db, trade, None, TradeStatus.PENDING_ACCEPTANCE.value, trigger="request_created", actor=user, actor_role="buyer")
        await notify(
            db,
            [trade.seller_id],
            "request_created",
            "收到新的购买请求",
            f"商品「{product.title}」收到来自 {user.display_name} 的购买请求，可进入交易分支沟通。",
            link_type="conversation",
            link_id=branch.id,
            payload={"trade_id": trade.id, "product_id": product_id},
        )
        await audit_service.record_event(
            db,
            audit_service.EVENT_TRADE_REQUEST_CREATE,
            target_type="trade",
            target_id=trade.id,
            after={"status": trade.status, "product_id": product_id},
        )
        await db.commit()
    except IntegrityError as exc:
        # 预检查后并发插入仍由条件唯一索引裁决：整笔回滚后返回已有请求。
        existing_trade = await trade_service.resolve_duplicate_pending_request(
            db, exc, product_id=product_id, buyer_id=buyer_id
        )
        return {"id": existing_trade.id, "detail": "您对该商品已有待接受的购买请求", "existing": True}
    return {"id": trade.id, "detail": "购买请求已发送，等待卖方接受"}


@router.get("/mine")
async def my_trades(user: CurrentUser, db: DbSession, role: str = Query(default="all", pattern="^(all|buyer|seller)$")) -> list[dict]:
    """我的交易：覆盖买卖双方身份全部请求和交易（FR-12）。"""
    query = select(Trade).order_by(col(Trade.id).desc())
    if role == "buyer":
        query = query.where(col(Trade.buyer_id) == user.id)
    elif role == "seller":
        query = query.where(col(Trade.seller_id) == user.id)
    else:
        query = query.where((col(Trade.buyer_id) == user.id) | (col(Trade.seller_id) == user.id))
    result = await db.exec(query)
    trades = list(result)
    return [await _trade_out(db, t, user) for t in trades]


@router.get("/{trade_id}")
async def trade_detail(trade_id: int, user: CurrentUser, db: DbSession) -> dict:
    trade = await _party_trade(db, trade_id, user.id)
    return await _trade_out(db, trade, user)


@router.get("/{trade_id}/transitions")
async def trade_transitions(trade_id: int, user: CurrentUser, db: DbSession) -> list[dict]:
    """状态转移历史：前后状态、主体、时间、触发与原因（BR-08、6.5）。"""
    trade = await _party_trade(db, trade_id, user.id)
    from app.models import TradeTransition

    result = await db.exec(
        select(TradeTransition).where(col(TradeTransition.trade_id) == trade.id).order_by(col(TradeTransition.id))
    )
    actor_ids = {t.actor_id for t in result if t.actor_id}
    names: dict[int, str] = {}
    if actor_ids:
        rows = await db.exec(select(col(User.id), col(User.display_name)).where(col(User.id).in_(actor_ids)))
        names = {uid: n for uid, n in rows.all()}
    result = await db.exec(
        select(TradeTransition).where(col(TradeTransition.trade_id) == trade.id).order_by(col(TradeTransition.id))
    )
    return [
        {
            "id": t.id,
            "from_status": t.from_status,
            "to_status": t.to_status,
            "actor_id": t.actor_id,
            "actor_name": names.get(t.actor_id) if t.actor_id else None,
            "actor_role": t.actor_role,
            "trigger": t.trigger,
            "reason": t.reason,
            "basis_case_id": t.basis_case_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in result
    ]


@router.post("/{trade_id}/accept")
async def accept_request(trade_id: int, user: CurrentUser, db: DbSession) -> dict:
    """卖方接受（TR-11/DT-01）：锁单、商品交易中、关闭其余待接受请求。

    并发约束：任何交易/状态/通知/审计写入之前，必须先按商品行锁串行化，
    再重新读取目标交易并校验状态与现有锁单。不能先改各自的 trade 再关闭
    对方的 pending，否则两笔接受会形成 trade→product 的交叉锁序并死锁。
    """
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.seller_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅卖方可接受请求")
    product_id = trade.product_id
    user_id = user.id
    # 死锁/序列化失败时整事务回滚后重试一次；事务内通知、审计、转移随回滚消失。
    for attempt in range(2):
        try:
            # 1. 统一锁序第一步：先锁商品行，再重新读取交易。并发接受在此排队。
            product = await trade_service.lock_product_for_update(db, product_id)
            if product is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
            # 2. 锁后重新校验目标交易，不能沿用加锁前的过期状态。
            trade = (await db.exec(
                select(Trade)
                .where(col(Trade.id) == trade_id)
                .execution_options(populate_existing=True)
            )).first()
            if trade is None or user_id not in (trade.buyer_id, trade.seller_id):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
            if trade.seller_id != user_id:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "仅卖方可接受请求")
            if trade.status != TradeStatus.PENDING_ACCEPTANCE.value:
                raise HTTPException(status.HTTP_409_CONFLICT, "该请求当前不可接受")
            await _ensure_trade_actors_eligible(db, trade)
            await trade_service.ensure_no_locking_conflict(db, trade, TradeStatus.IN_PROGRESS.value)
            # 3. 通过锁后校验才开始写入；后续关闭其他 pending 时已独占商品锁。
            from_status = trade.status
            trade.status = TradeStatus.IN_PROGRESS.value
            trade.accepted_at = datetime.now(UTC)
            trade.product_snapshot_json = await trade_ops.product_snapshot(db, product)
            product.status = ProductStatus.IN_TRANSACTION.value
            await trade_ops.record_transition(db, trade, from_status, TradeStatus.IN_PROGRESS.value, trigger="request_accepted", actor=user, actor_role="seller")
            # 关闭其余待接受请求并通知（DT-01）
            others = await trade_service.close_pending_requests_for_product(
                db, product.id, CLOSED_BY_LOCK, exclude_trade_ids={trade.id}
            )
            for other in others:
                await notify(
                    db,
                    [other.buyer_id],
                    "request_closed",
                    "您的购买请求已关闭",
                    f"商品「{product.title}」已被其他用户锁单，您的请求已关闭。",
                    link_type="trade",
                    link_id=other.id,
                )
            conversation = (await db.exec(select(Conversation).where(col(Conversation.trade_id) == trade.id, col(Conversation.type) == "trade"))).first()
            if conversation is None:
                # 请求创建时必定生成交易分支（BR-01/18）；缺失属于数据完整性异常。
                raise RuntimeError("交易分支缺失，无法完成接受请求")
            await conversation_service.send_system_message(db, conversation.id, "卖方已接受该购买请求，交易进入进行中。")
            await notify(
                db,
                [trade.buyer_id],
                "request_accepted",
                "您的购买请求已被接受",
                f"商品「{product.title}」的请求已被卖方接受，请进入交易分支沟通并确认交易约定。",
                link_type="conversation",
                link_id=conversation.id,
                payload={"trade_id": trade.id},
            )
            await audit_service.record_event(
                db,
                audit_service.EVENT_TRADE_ACCEPT,
                target_type="trade",
                target_id=trade.id,
                before={"status": from_status},
                after={"status": trade.status, "product_id": product.id},
            )
            await db.commit()
            return {"detail": "已接受，交易进行中"}
        except IntegrityError as exc:
            # D-48：预检后并发接受由唯一索引裁决；409 前回滚全部写入，不残留通知/关闭。
            # 锁序修复后正常并发应在锁后状态校验直接 409，此处是最后防线。
            await trade_service.resolve_lock_integrity_error(db, exc, product_id=product_id)
        except DBAPIError as exc:
            await db.rollback()
            if not trade_service.is_retryable_transaction_error(exc):
                raise
            if attempt == 0:
                # 仅对明确 SQLSTATE 40P01/40001 整事务重试；新事务会重新加锁并校验状态。
                reloaded_user = await db.get(User, user_id)
                if reloaded_user is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账户不存在")
                user = reloaded_user
                continue
            # 明确的事务级并发冲突，整事务已回滚；不把其他数据库错误泛化为 409。
            raise HTTPException(status.HTTP_409_CONFLICT, "并发冲突，请重试") from exc
    raise HTTPException(status.HTTP_409_CONFLICT, "并发冲突，请重试")


@router.post("/{trade_id}/reject")
async def reject_request(trade_id: int, body: RejectIn, user: CurrentUser, db: DbSession) -> dict:
    """卖方拒绝（TR-12）：记已拒绝，归档分支，通知买方。"""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.seller_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅卖方可拒绝请求")
    if trade.status != TradeStatus.PENDING_ACCEPTANCE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该请求当前不可拒绝")
    await _ensure_trade_actors_eligible(db, trade)
    from_status = trade.status
    trade.status = TradeStatus.REJECTED.value
    trade.close_reason = (body.reason or "").strip() or "卖方拒绝"
    await trade_ops.record_transition(db, trade, from_status, TradeStatus.REJECTED.value, trigger="request_rejected", actor=user, actor_role="seller", reason=trade.close_reason)
    await conversation_service.archive_trade_branch(db, trade.id)
    await notify(
        db,
        [trade.buyer_id],
        "request_rejected",
        "您的购买请求被拒绝",
        f"商品请求被卖方拒绝：{trade.close_reason}",
        link_type="trade",
        link_id=trade.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_REJECT,
        target_type="trade",
        target_id=trade.id,
        before={"status": from_status},
        after={"status": trade.status},
    )
    await db.commit()
    return {"detail": "已拒绝"}


@router.post("/{trade_id}/withdraw")
async def withdraw_request(trade_id: int, user: CurrentUser, db: DbSession) -> dict:
    """买方撤回（TR-13）：仅卖方接受前。"""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.buyer_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅请求发起人可撤回")
    if trade.status != TradeStatus.PENDING_ACCEPTANCE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "卖方已处理该请求，无法撤回")
    await _ensure_trade_actors_eligible(db, trade)
    product = await db.get(Product, trade.product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    from_status = trade.status
    trade.status = TradeStatus.WITHDRAWN.value
    trade.close_reason = "买方撤回"
    await trade_ops.record_transition(db, trade, from_status, TradeStatus.WITHDRAWN.value, trigger="request_withdrawn", actor=user, actor_role="buyer")
    await conversation_service.archive_trade_branch(db, trade.id)
    await notify(
        db,
        [trade.seller_id],
        "request_withdrawn",
        "购买请求已撤回",
        f"{user.display_name} 已撤回对商品「{product.title}」的购买请求。",
        link_type="trade",
        link_id=trade.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_WITHDRAW,
        target_type="trade",
        target_id=trade.id,
        before={"status": from_status},
        after={"status": trade.status},
    )
    await db.commit()
    return {"detail": "已撤回"}


# ---------------- 约定（4.15） ----------------


@router.post("/{trade_id}/agreements")
async def propose_agreement(trade_id: int, body: AgreementProposeIn, user: CurrentUser, db: DbSession) -> dict:
    """提出首次约定或变更：另一方明确同意后生效。"""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status != TradeStatus.IN_PROGRESS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能提出约定")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    pending = (await db.exec(
        select(TradeAgreement).where(col(TradeAgreement.trade_id) == trade.id, col(TradeAgreement.status) == AgreementStatus.PROPOSED.value)
    )).first()
    if pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "已有待确认的约定提案，须先由对方同意或拒绝",
        )
    count = (await db.exec(
        select(TradeAgreement).where(col(TradeAgreement.trade_id) == trade.id).order_by(col(TradeAgreement.id).desc()).limit(1)
    )).first()
    round_no = (count.round_no + 1) if count else 1
    agreement = TradeAgreement(
        trade_id=trade.id,
        round_no=round_no,
        proposer_id=user.id,
        delivery_time=body.delivery_time.strip(),
        delivery_location=body.delivery_location.strip(),
        delivery_method=body.delivery_method.strip(),
        amount_cents=body.amount_cents,
        payment_method=body.payment_method.strip(),
        payment_timing=body.payment_timing.strip(),
        status=AgreementStatus.PROPOSED.value,
    )
    db.add(agreement)
    await db.flush()
    other = trade.seller_id if user.id == trade.buyer_id else trade.buyer_id
    await notify(
        db,
        [other],
        "agreement_proposed",
        f"收到新的交易约定提案（第 {round_no} 轮）",
        "对方提出了交付与支付安排，请进入交易查看并确认。",
        link_type="trade",
        link_id=trade.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_AGREEMENT_PROPOSE,
        target_type="trade_agreement",
        target_id=agreement.id,
        after={"trade_id": trade.id, "round_no": round_no, "status": agreement.status},
    )
    await db.commit()
    return {"id": agreement.id, "detail": "提案已发送，等待对方确认"}


async def _decide_agreement(db: AsyncSession, trade: Trade, agreement_id: int, user: User, decision: str) -> dict:
    agreement = await db.get(TradeAgreement, agreement_id)
    if not agreement or agreement.trade_id != trade.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "约定提案不存在")
    if agreement.proposer_id == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "不能处理本人提出的提案")
    if agreement.status != AgreementStatus.PROPOSED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该提案已被处理")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    agreement_status_before = agreement.status
    agreement.decided_at = datetime.now(UTC)
    other = trade.seller_id if user.id == trade.buyer_id else trade.buyer_id
    if decision == "confirm":
        # D-49：有效新约定经另一方同意后，清空双方当前完成确认并结束旧等待；
        # 历史确认、原约定及计时记录保留；交易仍处于已有约定阶段，不恢复首次约定前取消权。
        await trade_ops.clear_current_confirmations(db, trade.id)
        trade_wait.clear_wait_state(trade)
        # 变更生效：原有效安排标记为已替换，历史保留（4.15）
        result = await db.exec(
            select(TradeAgreement).where(
                col(TradeAgreement.trade_id) == trade.id, col(TradeAgreement.status) == AgreementStatus.CONFIRMED.value
            )
        )
        for row in result:
            row.status = AgreementStatus.SUPERSEDED.value
        agreement.status = AgreementStatus.CONFIRMED.value
        trade.current_agreement_id = agreement.id
        await notify(
            db, [other], "agreement_decided", "交易约定已确认生效", "对方已同意约定安排，可分别提交完成确认。",
            link_type="trade", link_id=trade.id,
        )
        detail = "约定已确认生效"
    else:
        # 拒绝只结束提案，交易与锁单保持（4.15）
        agreement.status = AgreementStatus.REJECTED.value
        await notify(
            db, [other], "agreement_decided", "约定提案被拒绝", "对方拒绝了本次约定提案，可重新提出。",
            link_type="trade", link_id=trade.id,
        )
        detail = "已拒绝该提案"
    await audit_service.record_event(
        db,
        (
            audit_service.EVENT_AGREEMENT_CONFIRM
            if decision == "confirm"
            else audit_service.EVENT_AGREEMENT_REJECT
        ),
        target_type="trade_agreement",
        target_id=agreement.id,
        before={"status": agreement_status_before},
        after={"status": agreement.status, "trade_id": trade.id},
    )
    await db.commit()
    return {"detail": detail}


@router.post("/{trade_id}/agreements/{agreement_id}/confirm")
async def confirm_agreement(trade_id: int, agreement_id: int, user: CurrentUser, db: DbSession) -> dict:
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status != TradeStatus.IN_PROGRESS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能确认约定")
    return await _decide_agreement(db, trade, agreement_id, user, "confirm")


@router.post("/{trade_id}/agreements/{agreement_id}/reject")
async def reject_agreement(trade_id: int, agreement_id: int, user: CurrentUser, db: DbSession) -> dict:
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status != TradeStatus.IN_PROGRESS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能处理约定")
    return await _decide_agreement(db, trade, agreement_id, user, "reject")


# ---------------- 完成确认（BR-04/05/28/29） ----------------


@router.post("/{trade_id}/confirmations")
async def submit_confirmation(trade_id: int, body: ConfirmationIn, user: CurrentUser, db: DbSession) -> dict:
    """双方分别一次完成确认（交付+支付统一声明）；单方记进度并开始计时。"""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status != TradeStatus.IN_PROGRESS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅进行中交易可提交完成确认")
    product_id = trade.product_id
    user_id = user.id
    # 完成确认可能触发 finish_trade（trade 结束后下架商品）；先按“商品 → 交易”
    # 统一锁序，不能持 trade 行等待商品，避免与 accept/admin adjust 交叉死锁。
    trade = await trade_service.lock_product_then_trade(db, trade_id, product_id)
    if trade is None or user_id not in (trade.buyer_id, trade.seller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    if trade.status != TradeStatus.IN_PROGRESS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅进行中交易可提交完成确认")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    if not trade.current_agreement_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "须先确认交易约定，才能提交完成确认")
    existing = (await db.exec(
        select(CompletionConfirmation).where(
            col(CompletionConfirmation.trade_id) == trade.id,
            col(CompletionConfirmation.confirmer_id) == user.id,
            col(CompletionConfirmation.is_current).is_(True),
        )
    )).first()
    if existing:
        return {"detail": "您已提交完成确认，等待对方确认", "existing": True}
    confirmation = CompletionConfirmation(trade_id=trade.id, confirmer_id=user.id, note=(body.note or "").strip() or None)
    db.add(confirmation)
    # 新一轮确认从本次提交起完整计时，不继承任何旧暂停。
    trade.confirm_wait_started_at = datetime.now(UTC)
    trade.confirm_wait_paused_at = None
    trade.confirm_wait_remaining_seconds = None
    other = trade.seller_id if user.id == trade.buyer_id else trade.buyer_id
    both = await db.exec(
        select(CompletionConfirmation).where(
            col(CompletionConfirmation.trade_id) == trade.id, col(CompletionConfirmation.is_current).is_(True)
        )
    )
    confirmers = {c.confirmer_id for c in both}
    if {trade.buyer_id, trade.seller_id} <= confirmers:
        await trade_ops.finish_trade(db, trade, to_status=TradeStatus.COMPLETED, trigger="both_confirmed", actor=user, actor_role=("buyer" if user.id == trade.buyer_id else "seller"), title="")
        await db.flush()
        await audit_service.record_event(
            db,
            audit_service.EVENT_TRADE_COMPLETION_CONFIRM,
            target_type="trade",
            target_id=trade.id,
            before={"status": TradeStatus.IN_PROGRESS.value},
            after={"status": trade.status, "confirmation_id": confirmation.id},
        )
        await db.commit()
        return {"detail": "双方均确认完成，交易已完成"}
    await notify(
        db,
        [other],
        "confirm_progress",
        "对方已提交完成确认",
        "对方已确认交付与支付完成，请核实后提交本人确认；7 天未回应将转异常处理。",
        link_type="trade",
        link_id=trade.id,
    )
    await db.flush()
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_COMPLETION_CONFIRM,
        target_type="trade",
        target_id=trade.id,
        before={"status": TradeStatus.IN_PROGRESS.value},
        after={"status": trade.status, "confirmation_id": confirmation.id},
    )
    await db.commit()
    return {"detail": "已记录本人确认，等待对方确认"}


# ---------------- 取消（BR-06、4.15） ----------------


@router.post("/{trade_id}/cancel")
async def propose_cancel(trade_id: int, body: CancelIn, user: CurrentUser, db: DbSession) -> dict:
    """发起取消：约定前买方直接取消；其余情形须对方同意。"""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status not in (TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能取消")
    product_id = trade.product_id
    user_id = user.id
    # 取消可能直接结束交易并下架商品；先商品后交易，避免 trade→product 反向等待。
    trade = await trade_service.lock_product_then_trade(db, trade_id, product_id)
    if trade is None or user_id not in (trade.buyer_id, trade.seller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    if trade.status not in (TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能取消")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    other = trade.seller_id if user.id == trade.buyer_id else trade.buyer_id
    reason = (body.reason or "").strip() or None
    is_buyer = user.id == trade.buyer_id
    has_effective_agreement = trade.current_agreement_id is not None
    before_status = trade.status
    if not has_effective_agreement and is_buyer and trade.status == TradeStatus.IN_PROGRESS.value:
        # 首次约定前买方可直接取消（BR-06）
        await trade_ops.finish_trade(db, trade, to_status=TradeStatus.TERMINATED, trigger="buyer_cancel", actor=user, actor_role="buyer", reason=reason)
        await audit_service.record_event(
            db,
            audit_service.EVENT_TRADE_CANCEL_CONFIRM,
            target_type="trade",
            target_id=trade.id,
            reason_code="buyer_direct_cancel",
            before={"status": before_status},
            after={"status": trade.status},
        )
        await db.commit()
        return {"detail": "交易已终止"}
    if trade.cancel_requested_by_id and trade.cancel_requested_by_id != user.id:
        # 对方已申请，本次操作视为同意取消
        await trade_ops.finish_trade(db, trade, to_status=TradeStatus.TERMINATED, trigger="cancel_agreed", actor=user, actor_role=("buyer" if is_buyer else "seller"), reason=reason)
        await audit_service.record_event(
            db,
            audit_service.EVENT_TRADE_CANCEL_CONFIRM,
            target_type="trade",
            target_id=trade.id,
            reason_code="cancel_agreed",
            before={"status": before_status},
            after={"status": trade.status},
        )
        await db.commit()
        return {"detail": "双方同意，交易已终止"}
    if trade.cancel_requested_by_id == user.id:
        return {"detail": "您已发起取消申请，等待对方同意", "existing": True}
    trade.cancel_requested_by_id = user.id
    trade.cancel_requested_at = datetime.now(UTC)
    await notify(
        db, [other], "cancel_requested", "收到交易取消申请", "对方发起取消申请，请进入交易查看并确认。",
        link_type="trade", link_id=trade.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_CANCEL_REQUEST,
        target_type="trade",
        target_id=trade.id,
        before={"status": before_status},
        after={"status": trade.status, "cancel_requested": True},
    )
    await db.commit()
    return {"detail": "取消申请已发送，等待对方同意"}


@router.post("/{trade_id}/cancel/confirm")
async def confirm_cancel(trade_id: int, body: CancelIn, user: CurrentUser, db: DbSession) -> dict:
    """同意取消申请（未同意不自动终止）。"""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status not in (TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能取消")
    product_id = trade.product_id
    user_id = user.id
    # 确认取消会结束交易并下架商品；与完成确认、accept、admin adjust 统一锁序。
    trade = await trade_service.lock_product_then_trade(db, trade_id, product_id)
    if trade is None or user_id not in (trade.buyer_id, trade.seller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    if trade.status not in (TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能取消")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    if not trade.cancel_requested_by_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前没有待确认的取消申请")
    if trade.cancel_requested_by_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能确认本人发起的取消申请")
    before_status = trade.status
    await trade_ops.finish_trade(db, trade, to_status=TradeStatus.TERMINATED, trigger="cancel_agreed", actor=user, actor_role=("buyer" if user.id == trade.buyer_id else "seller"), reason=(body.reason or "").strip() or None)
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_CANCEL_CONFIRM,
        target_type="trade",
        target_id=trade.id,
        before={"status": before_status},
        after={"status": trade.status},
    )
    await db.commit()
    return {"detail": "双方同意，交易已终止"}


@router.post("/{trade_id}/cancel/withdraw")
async def withdraw_cancel(trade_id: int, user: CurrentUser, db: DbSession) -> dict:
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.cancel_requested_by_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前没有本人发起的取消申请")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    trade.cancel_requested_by_id = None
    trade.cancel_requested_at = None
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_CANCEL_WITHDRAW,
        target_type="trade",
        target_id=trade.id,
        after={"cancel_requested": False},
    )
    await db.commit()
    return {"detail": "已撤回取消申请"}


# ---------------- 争议（BR-07、TR-16/19） ----------------


@router.post("/{trade_id}/disputes")
async def create_dispute(trade_id: int, body: DisputeIn, user: CurrentUser, db: DbSession) -> dict:
    """发起争议并填写说明：统一进入有争议，保持锁单，不自动冻结。"""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status != TradeStatus.IN_PROGRESS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅进行中交易可发起争议")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    await trade_service.ensure_no_locking_conflict(db, trade, TradeStatus.DISPUTED.value)
    from_status = trade.status
    trade.status = TradeStatus.DISPUTED.value
    trade_wait.clear_wait_state(trade)  # 进入争议即有效响应，结束原计时（BR-05）
    await trade_ops.record_transition(db, trade, from_status, TradeStatus.DISPUTED.value, trigger="dispute_created", actor=user, actor_role=("buyer" if user.id == trade.buyer_id else "seller"), reason=body.description.strip())
    case = await case_service.create_case(
        db,
        case_type=CaseType.TRADE_DISPUTE,
        title=f"交易争议：交易#{trade.id}",
        trade_id=trade.id,
    )
    await case_service.add_case_message(
        db, case, sender_id=user.id,
        role=DisposalMessageRole.USER,
        kind=DisposalMessageKind.NOTICE,
        content=f"{'买方' if user.id == trade.buyer_id else '卖方'}发起争议：{body.description.strip()}",
    )
    other = trade.seller_id if user.id == trade.buyer_id else trade.buyer_id
    await notify(
        db, [other], "trade_dispute", "交易进入争议状态", "对方对交易发起争议，交易保持锁单；可通过管理沟通或双方确认解决。",
        link_type="trade", link_id=trade.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_DISPUTE_CREATE,
        target_type="trade",
        target_id=trade.id,
        before={"status": from_status},
        after={"status": trade.status, "case_id": case.id},
    )
    await db.commit()
    return {"detail": "已进入争议状态", "case_id": case.id}


async def _restore_from_dispute(db: AsyncSession, trade: Trade, actor: User | None, actor_role: str, reason: str, basis_case_id: int | None = None) -> None:
    """恢复进行中：清空当前完成确认、保留历史与有效约定；恢复不启动计时（TR-19）。"""
    await trade_ops.clear_current_confirmations(db, trade.id)
    trade.status = TradeStatus.IN_PROGRESS.value
    trade_wait.clear_wait_state(trade)
    trade.resolution_confirmed_by_id = None
    trade.resolution_confirmed_at = None
    await trade_ops.record_transition(
        db, trade, TradeStatus.DISPUTED.value, TradeStatus.IN_PROGRESS.value,
        trigger="dispute_resolved", actor=actor, actor_role=actor_role, reason=reason, basis_case_id=basis_case_id,
    )
    await notify(
        db, [trade.buyer_id, trade.seller_id], "dispute_resolved", "交易争议已解决，恢复进行中",
        "当前完成确认已清空，历史与有效约定保留；如需完成交易，请任一方重新提交完成确认。",
        link_type="trade", link_id=trade.id,
    )


@router.post("/{trade_id}/disputes/resolve")
async def resolve_dispute(trade_id: int, body: CancelIn, user: CurrentUser, db: DbSession) -> dict:
    """双方均确认解决可恢复进行中（BR-07）；管理员解决走管理事项接口。"""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status != TradeStatus.DISPUTED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "交易当前不在争议状态")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    if trade.resolution_confirmed_by_id and trade.resolution_confirmed_by_id != user.id:
        await trade_service.ensure_no_locking_conflict(db, trade, TradeStatus.IN_PROGRESS.value)
        await _restore_from_dispute(db, trade, user, "buyer" if user.id == trade.buyer_id else "seller", (body.reason or "").strip() or "双方确认解决")
        await audit_service.record_event(
            db,
            audit_service.EVENT_TRADE_DISPUTE_RESOLVE,
            target_type="trade",
            target_id=trade.id,
            before={"status": TradeStatus.DISPUTED.value},
            after={"status": trade.status},
        )
        await db.commit()
        return {"detail": "双方确认解决，交易恢复进行中"}
    if trade.resolution_confirmed_by_id == user.id:
        return {"detail": "您已确认解决，等待对方确认", "existing": True}
    trade.resolution_confirmed_by_id = user.id
    trade.resolution_confirmed_at = datetime.now(UTC)
    other = trade.seller_id if user.id == trade.buyer_id else trade.buyer_id
    await notify(
        db, [other], "dispute_resolved", "对方已确认争议解决", "对方确认争议已解决，等待您确认后交易恢复进行中。",
        link_type="trade", link_id=trade.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_DISPUTE_RESOLVE,
        target_type="trade",
        target_id=trade.id,
        after={"status": trade.status, "resolution_confirmed": True},
    )
    await db.commit()
    return {"detail": "已记录本人确认，等待对方确认"}

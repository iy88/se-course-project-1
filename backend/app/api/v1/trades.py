"""End-to-end trade API (FR-05/06/09; BR-01—09, 4.15): requests, locking, agreements, confirmations, cancellation, and disputes."""

from datetime import UTC, datetime
from typing import Annotated

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


async def _party_trade(db: AsyncSession, trade_id: int, user_id: int, *, lock: bool = True) -> Trade:
    trade = await db.get(Trade, trade_id)
    if not trade or user_id not in (trade.buyer_id, trade.seller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    if lock:
        trade = await trade_service.lock_product_then_trade(db, trade_id, trade.product_id)
        if not trade or user_id not in (trade.buyer_id, trade.seller_id):
            raise HTTPException(404, '交易不存在')
    return trade


async def _ensure_not_frozen(trade: Trade) -> None:
    if trade.frozen:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "交易已被冻结，双方操作暂停，可查看历史或通过管理沟通处理")


async def _ensure_user_can_trade(db: AsyncSession, user_id: int) -> None:
    """BR-33: a trade freeze suspends all trade actions for that user, not just the frozen pair.

    The IM pair scope remains the responsibility of im_service.pair_frozen; this check only covers trade eligibility.
    """
    if await has_active_frozen_trade(db, user_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "账户存在有效交易冻结，暂停全部交易操作；无关商品合规编辑与无关 IM 不受影响",
        )


async def _ensure_trade_actors_eligible(db: AsyncSession, trade: Trade) -> None:
    """Validate the current global trade eligibility of both buyer and seller before a write (R3/BR-33)."""
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
        # D-51: expose the pause instant and remaining seconds per contract so the frontend and admin UI can display/refresh them
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
    """Create a purchase request (BR-01/02): no lock; create a dedicated trade branch and notify the seller.

    Although a request takes no lock, it must first serialize on the product row lock,
    then read product requestability, both parties' eligibility, and duplicate pending
    requests. Otherwise a request could wait after seeing "listed", and insert a
    pending row after the seller's accept has already set the product to
    in_transaction, breaking the invariant that a locked product cannot be requested again.
    """
    ensure_can_write(user)
    # Same first lock as accept/admin adjust: the product. Only state read after locking is current.
    product = await trade_service.lock_product_for_update(db, body.product_id)
    if not product or product.status != ProductStatus.LISTED.value or product.display_restricted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或当前不可请求")
    if product.seller_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能购买本人发布的商品")
    # R3/BR-33: both the buyer's and the seller's global trade eligibility must be valid.
    await _ensure_user_can_trade(db, user.id)
    await _ensure_user_can_trade(db, product.seller_id)
    existing = await trade_service.find_pending_request(db, product.id, user.id)
    if existing:
        # Duplicate submission returns the existing result (6.5 retry consistency)
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
            f"买方申请购买「{product.title}」。请点击上方“交易详情”处理请求并商定交易安排。",
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
        # After the precheck, a conditional unique index still arbitrates concurrent inserts: roll back the transaction and return the existing request.
        existing_trade = await trade_service.resolve_duplicate_pending_request(
            db, exc, product_id=product_id, buyer_id=buyer_id
        )
        return {"id": existing_trade.id, "detail": "您对该商品已有待接受的购买请求", "existing": True}
    return {"id": trade.id, "detail": "购买请求已发送，等待卖方接受"}


@router.get("/mine")
async def my_trades(
    user: CurrentUser, db: DbSession,
    role: str = Query(default="all", pattern="^(all|buyer|seller)$"),
    product_id: Annotated[int | None, Query(gt=0)] = None,
) -> list[dict]:
    """My trades: all requests and trades where the user is buyer or seller (FR-12)."""
    query = select(Trade).order_by(col(Trade.id).desc())
    if role == "buyer":
        query = query.where(col(Trade.buyer_id) == user.id)
    elif role == "seller":
        query = query.where(col(Trade.seller_id) == user.id)
    else:
        query = query.where((col(Trade.buyer_id) == user.id) | (col(Trade.seller_id) == user.id))
    if product_id is not None:
        # The product filter is combined with the user's own role scope; changing the product ID must not widen access.
        query = query.where(col(Trade.product_id) == product_id)
    result = await db.exec(query)
    trades = list(result)
    return [await _trade_out(db, t, user) for t in trades]


@router.get("/{trade_id}")
async def trade_detail(trade_id: int, user: CurrentUser, db: DbSession) -> dict:
    trade = await _party_trade(db, trade_id, user.id, lock=False)
    return await _trade_out(db, trade, user)


@router.get("/{trade_id}/transitions")
async def trade_transitions(trade_id: int, user: CurrentUser, db: DbSession) -> list[dict]:
    """State-transition history: from/to status, actor, time, trigger, and reason (BR-08, 6.5)."""
    trade = await _party_trade(db, trade_id, user.id, lock=False)
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
    """Seller accepts (TR-11/DT-01): lock the product, mark it in transaction, close other pending requests.

    Concurrency constraint: before any trade/state/notification/audit write, serialize
    on the product row lock, then re-read the target trade and validate its state and
    existing lock. Do not modify each trade first and then close the counterparty's
    pending rows; two accepts would create a cross lock order (trade→product) and deadlock.
    """
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.seller_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅卖方可接受请求")
    product_id = trade.product_id
    user_id = user.id
    # On deadlock/serialization failure, roll back the whole transaction and retry once; notifications, audits, and transitions vanish with the rollback.
    for attempt in range(2):
        try:
            # 1. First step of the unified lock order: lock the product row, then re-read the trade. Concurrent accepts queue here.
            product = await trade_service.lock_product_for_update(db, product_id)
            if product is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
            # 2. Re-validate the target trade after locking; do not reuse pre-lock stale state.
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
            # 3. Writes start only after post-lock validation; closing other pending rows then holds the product lock exclusively.
            from_status = trade.status
            trade.status = TradeStatus.IN_PROGRESS.value
            trade.accepted_at = datetime.now(UTC)
            trade.product_snapshot_json = await trade_ops.product_snapshot(db, product)
            product.status = ProductStatus.IN_TRANSACTION.value
            await trade_ops.record_transition(db, trade, from_status, TradeStatus.IN_PROGRESS.value, trigger="request_accepted", actor=user, actor_role="seller")
            # Close the remaining pending requests and notify their buyers (DT-01)
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
                # A trade branch is always created with the request (BR-01/18); its absence is a data-integrity error.
                raise RuntimeError("Trade branch is missing; cannot complete the accept request")
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
            # D-48: the unique index arbitrates concurrent accepts after the precheck; roll back all writes before 409 so no notification/closure remains.
            # After the lock-order fix, normal concurrency should hit the post-lock state check and return 409; this is the last line of defense.
            await trade_service.resolve_lock_integrity_error(db, exc, product_id=product_id)
        except DBAPIError as exc:
            await db.rollback()
            if not trade_service.is_retryable_transaction_error(exc):
                raise
            if attempt == 0:
                # Retry the whole transaction only for explicit SQLSTATE 40P01/40001; the new transaction re-locks and re-validates state.
                reloaded_user = await db.get(User, user_id)
                if reloaded_user is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账户不存在")
                user = reloaded_user
                continue
            # Explicit transaction-level concurrency conflict; the whole transaction has rolled back. Do not generalize other database errors to 409.
            raise HTTPException(status.HTTP_409_CONFLICT, "并发冲突，请重试") from exc
    raise HTTPException(status.HTTP_409_CONFLICT, "并发冲突，请重试")


@router.post("/{trade_id}/reject")
async def reject_request(trade_id: int, body: RejectIn, user: CurrentUser, db: DbSession) -> dict:
    """Seller rejects (TR-12): record the rejection, archive the branch, and notify the buyer."""
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
    """Buyer withdraws (TR-13): only before seller acceptance."""
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


# ---------------- Agreements (4.15) ----------------


@router.post("/{trade_id}/agreements")
async def propose_agreement(trade_id: int, body: AgreementProposeIn, user: CurrentUser, db: DbSession) -> dict:
    """Propose the first agreement or a change: it takes effect after the counterparty explicitly agrees."""
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
        # D-49: after the counterparty accepts a new effective agreement, clear both parties' current completion confirmations and end the old wait;
        # historical confirmations, previous agreements, and timing records are retained; the trade stays in the agreed stage and the pre-first-agreement cancellation right does not return.
        await trade_ops.clear_current_confirmations(db, trade.id)
        trade_wait.clear_wait_state(trade)
        # Change takes effect: the previously effective arrangement is marked superseded and history is retained (4.15)
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
        # Rejection only ends the proposal; the trade and product lock remain (4.15)
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


# ---------------- Completion confirmations (BR-04/05/28/29) ----------------


@router.post("/{trade_id}/confirmations")
async def submit_confirmation(trade_id: int, body: ConfirmationIn, user: CurrentUser, db: DbSession) -> dict:
    """Each party confirms completion once (delivery + payment declared together); a unilateral confirmation records progress and starts the timer."""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status != TradeStatus.IN_PROGRESS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅进行中交易可提交完成确认")
    product_id = trade.product_id
    user_id = user.id
    # A completion confirmation may trigger finish_trade (delisting the product after the trade ends); follow the unified "product → trade" lock order
    # and never hold a trade row while waiting for the product, avoiding cross-deadlocks with accept/admin adjust.
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
    # A new confirmation round starts the full timer from this submission and inherits no previous pause.
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


# ---------------- Cancellation (BR-06, 4.15) ----------------


@router.post("/{trade_id}/cancel")
async def propose_cancel(trade_id: int, body: CancelIn, user: CurrentUser, db: DbSession) -> dict:
    """Initiate cancellation: before an agreement the buyer may cancel directly; other cases need counterparty consent."""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status not in (TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能取消")
    product_id = trade.product_id
    user_id = user.id
    # Cancellation may end the trade immediately and delist the product; lock product then trade to avoid reverse trade→product waiting.
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
        # Before the first agreement the buyer may cancel directly (BR-06)
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
        # The counterparty already requested it, so this action counts as consenting to the cancellation
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
    """Approve a cancellation request (no automatic termination without consent)."""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status not in (TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能取消")
    product_id = trade.product_id
    user_id = user.id
    # Confirming cancellation ends the trade and delists the product; use the same lock order as completion confirmation, accept, and admin adjust.
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


@router.post("/{trade_id}/cancel/reject")
async def reject_cancel(trade_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Reject the counterparty's cancellation request: only the request ends; the trade state is unchanged (BR-06, US-05-AC-06)."""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status not in (TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前交易状态不能处理取消申请")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    if not trade.cancel_requested_by_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前没有待确认的取消申请")
    if trade.cancel_requested_by_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能拒绝本人发起的取消申请")
    applicant_id = trade.cancel_requested_by_id
    before_status = trade.status
    trade.cancel_requested_by_id = None
    trade.cancel_requested_at = None
    await notify(
        db, [applicant_id], "cancel_rejected", "取消申请已被拒绝",
        "对方不同意取消，取消申请已结束，交易继续有效。",
        link_type="trade", link_id=trade.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_CANCEL_REJECT,
        target_type="trade",
        target_id=trade.id,
        before={"status": before_status, "cancel_requested": True},
        after={"status": trade.status, "cancel_requested": False},
    )
    await db.commit()
    return {"detail": "已拒绝取消申请，交易继续"}


# ---------------- Disputes (BR-07, TR-16/19) ----------------


@router.post("/{trade_id}/disputes")
async def create_dispute(trade_id: int, body: DisputeIn, user: CurrentUser, db: DbSession) -> dict:
    """Open a dispute with a description: always enter disputed, keep the product lock, and do not freeze automatically."""
    ensure_can_write(user)
    trade = await _party_trade(db, trade_id, user.id)
    if trade.status != TradeStatus.IN_PROGRESS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅进行中交易可发起争议")
    await _ensure_not_frozen(trade)
    await _ensure_trade_actors_eligible(db, trade)
    await trade_service.ensure_no_locking_conflict(db, trade, TradeStatus.DISPUTED.value)
    from_status = trade.status
    trade.status = TradeStatus.DISPUTED.value
    trade_wait.clear_wait_state(trade)  # Entering a dispute is a valid response and ends the original timer (BR-05)
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
    """Resume in progress: clear current completion confirmations while keeping history and the effective agreement; resumption does not start the timer (TR-19)."""
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
    """Resume in progress when both parties confirm resolution (BR-07); administrator resolution goes through the management-case API."""
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

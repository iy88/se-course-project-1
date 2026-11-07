"""Administrator trade handling (BR-08/33): freeze/unfreeze and adjust any status with a basis."""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import col, select

from app.core.text import NonBlank500
from app.api.deps import CurrentAdmin, DbSession
from app.models import (
    AccountRestriction,
    CompletionConfirmation,
    Conversation,
    DisposalCase,
    Message,
    Product,
    Report,
    Trade,
    TradeAgreement,
    TradeReview,
    TradeTransition,
    User,
)
from app.models.enums import (
    CaseType,
    ProductStatus,
    ReportTargetType,
    RestrictionType,
    TradeStatus,
)
from app.services import audit as audit_service
from app.services import moderation, trade_ops, trade_wait
from app.services import trades as trade_service
from app.services.notifications import notify

router = APIRouter(prefix="/admin/trades", tags=["admin-trades"])

ALLOWED_ADJUST_TARGETS = {s.value for s in TradeStatus}
LOCKING_TARGETS = set(trade_service.LOCKING_STATUSES)
ENDED_TARGETS = {TradeStatus.COMPLETED.value, TradeStatus.TERMINATED.value}


async def admin_trade_view(db, trade_id: int) -> dict | None:
    """Administrative trade summary (including agreements/confirmations/transition history)."""
    trade = await db.get(Trade, trade_id)
    if not trade:
        return None
    buyer = await db.get(User, trade.buyer_id)
    seller = await db.get(User, trade.seller_id)
    product = await db.get(Product, trade.product_id)
    agreements = (
        await db.exec(select(TradeAgreement).where(col(TradeAgreement.trade_id) == trade.id).order_by(col(TradeAgreement.id)))
    ).all()
    confirms = (
        await db.exec(
            select(CompletionConfirmation).where(col(CompletionConfirmation.trade_id) == trade.id).order_by(col(CompletionConfirmation.id))
        )
    ).all()
    transitions = (
        await db.exec(select(TradeTransition).where(col(TradeTransition.trade_id) == trade.id).order_by(col(TradeTransition.id)))
    ).all()
    return {
        "id": trade.id,
        "status": trade.status,
        "frozen": trade.frozen,
        "frozen_reason": trade.frozen_reason,
        "buyer": {"id": buyer.id, "display_name": buyer.display_name} if buyer else None,
        "seller": {"id": seller.id, "display_name": seller.display_name} if seller else None,
        "product": {"id": product.id, "title": product.title, "status": product.status} if product else None,
        "product_snapshot": trade.product_snapshot_json,
        "current_agreement_id": trade.current_agreement_id,
        "agreements": [
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
            }
            for a in agreements
        ],
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
        "confirm_wait_started_at": trade_wait.iso_utc(trade.confirm_wait_started_at),
        "confirm_wait_paused_at": trade_wait.iso_utc(trade.confirm_wait_paused_at),
        "confirm_wait_remaining_seconds": trade_wait.wait_remaining_seconds(trade),
        "transitions": [
            {
                "from_status": t.from_status,
                "to_status": t.to_status,
                "actor_id": t.actor_id,
                "actor_role": t.actor_role,
                "trigger": t.trigger,
                "reason": t.reason,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transitions
        ],
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "finished_at": trade.finished_at.isoformat() if trade.finished_at else None,
    }


class FreezeIn(BaseModel):
    reason: NonBlank500
    case_id: int | None = None


class UnfreezeIn(BaseModel):
    reason: NonBlank500
    case_id: int | None = None  # related disposal case (basis)


class AdjustIn(BaseModel):
    to_status: str
    reason: NonBlank500
    case_id: int | None = None  # related disposal case (basis)


async def case_relevant_to_trade(db, case: DisposalCase, trade: Trade) -> bool:
    """A case must relate directly to this trade, not merely share a product or any account.

    A case bound to a specific trade is valid only for that trade; when case.trade_id
    points to another trade, a matching product_id must not bypass that. Ordinary
    product review cases grant no later private-trade access by themselves. Valid
    bases are limited to: a case for this trade, a genuine violation report targeting
    this product, a report targeting this trade's review or this trade branch's
    messages, a restriction record left when report handling actually banned the
    account, and a ban case for the account; disposed/lifted states do not invalidate
    them. Arbitrary subject_user cases, arbitrary user reports, restriction records
    from other cases, ordinary private-chat messages, or a self-claimed case must not
    widen private-trade access.
    """
    if case.trade_id is not None:
        return case.trade_id == trade.id
    if (
        case.case_type == CaseType.ACCOUNT_BAN.value
        and case.subject_user_id in (trade.buyer_id, trade.seller_id)
    ):
        return True
    # Report-handling ban_user records an AccountRestriction under the original report
    # case and does not create a separate ACCOUNT_BAN case; read the actual restriction
    # record instead of inferring from subject_user. Only ban records linked exactly to
    # this case id whose banned account is a party to this trade count; do not filter
    # by active, since a ban later lifted still supports subsequent viewing/adjustment.
    if case.case_type == CaseType.REPORT.value:
        restriction_id = (await db.exec(
            select(col(AccountRestriction.id))
            .where(
                col(AccountRestriction.case_id) == case.id,
                col(AccountRestriction.type) == RestrictionType.BAN.value,
                col(AccountRestriction.user_id).in_((trade.buyer_id, trade.seller_id)),
            )
            .limit(1)
        )).first()
        if restriction_id is not None:
            return True
    if case.report_id:
        report = await db.get(Report, case.report_id)
        if report is not None:
            if (
                report.target_type == ReportTargetType.PRODUCT.value
                and report.target_id == trade.product_id
            ):
                return True
            if report.target_type == ReportTargetType.REVIEW.value:
                review = await db.get(TradeReview, report.target_id)
                if review is not None and review.trade_id == trade.id:
                    return True
            if report.target_type == ReportTargetType.MESSAGE.value:
                # Only messages in a trade branch locate this trade; ordinary private
                # chats have no trade_id, and other trade branches point to a different
                # trade_id, so neither may be used to access this trade.
                message = await db.get(Message, report.target_id)
                if message is not None:
                    conversation = await db.get(Conversation, message.conversation_id)
                    if conversation is not None and conversation.trade_id == trade.id:
                        return True
    return False


async def _resolve_trade_case(
    db, trade: Trade, admin_id: int, case_id: int | None
) -> DisposalCase:
    """BR-27/34: reading a private trade and freezing/unfreezing/adjusting it must be done by the administrator who claimed the related case.

    When case_id is omitted, select automatically only a case claimed by this
    administrator that genuinely relates to this trade; omission never means
    independent maintenance access. A disposed case may still serve as a valid basis
    for later handling.
    """
    if case_id is not None:
        case = await db.get(DisposalCase, case_id)
        if not case:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "关联事项不存在")
        if case.claimed_by_id != admin_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "仅该事项认领管理员可查看或处理该交易")
        if not await case_relevant_to_trade(db, case, trade):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "关联事项与该交易无关")
        return case
    result = await db.exec(
        select(DisposalCase)
        .where(col(DisposalCase.claimed_by_id) == admin_id)
        .order_by(col(DisposalCase.id).desc())
    )
    for case in result:
        if await case_relevant_to_trade(db, case, trade):
            return case
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "管理员须先认领与本交易相关的处置事项，才能查看或处理该私人交易",
    )


async def _notify_adjustment(
    db,
    trade: Trade,
    *,
    from_status: str,
    to_status: str,
    reason: str,
    case_id: int | None,
) -> None:
    notes: list[str] = []
    if to_status == TradeStatus.IN_PROGRESS.value:
        notes.append("当前完成确认已清空，历史与有效约定保留；恢复本身不启动计时，重新提交完成确认后才开始完整等待")
    elif from_status in ENDED_TARGETS:
        notes.append("旧交易当前完成确认已清空、旧计时已结束，历史与有效约定保留；恢复本身不启动计时")
    if trade.frozen:
        notes.append("本笔冻结仍保留，其他有效限制继续适用")
    else:
        notes.append("其他有效限制（如有）继续适用")
    await notify(
        db,
        [trade.buyer_id, trade.seller_id],
        "trade_adjusted",
        "交易状态已由管理员调整",
        f"交易#{trade.id}状态由 {from_status} 调整为 {to_status}。原因：{reason}。"
        + "；".join(notes)
        + "。可从处置沟通了解依据。",
        link_type="trade",
        link_id=trade.id,
        payload={"from_status": from_status, "to_status": to_status, "case_id": case_id},
    )


@router.get("/{trade_id}")
async def get_trade(
    trade_id: int,
    admin: CurrentAdmin,
    db: DbSession,
    case_id: int | None = Query(default=None),
) -> dict:
    """Administrative trade detail (BR-27: access limited to the scope necessary for the case)."""
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    await _resolve_trade_case(db, trade, admin.id, case_id)
    view = await admin_trade_view(db, trade_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    return view


@router.post("/{trade_id}/freeze")
async def freeze(trade_id: int, body: FreezeIn, admin: CurrentAdmin, db: DbSession) -> dict:
    trade = await db.get(Trade, trade_id)
    if trade is not None:
        trade = await trade_service.lock_product_then_trade(db, trade_id, trade.product_id)
    if not trade:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    case = await _resolve_trade_case(db, trade, admin.id, body.case_id)
    was_frozen = trade.frozen
    await moderation.freeze_trade(db, trade, body.reason.strip(), case.id, admin.id)
    if not was_frozen and trade.frozen:
        await audit_service.record_event(
            db,
            audit_service.EVENT_ADMIN_TRADE_FREEZE,
            target_type="trade",
            target_id=trade.id,
            before={"frozen": False},
            after={"frozen": True, "case_id": case.id},
        )
    await db.commit()
    return {"detail": "交易已冻结"}


@router.post("/{trade_id}/unfreeze")
async def unfreeze(trade_id: int, body: UnfreezeIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """Unfreezing a non-ended trade requires an administrator basis (BR-33); when eligible, the remaining wait resumes (D-51)."""
    trade = await db.get(Trade, trade_id)
    if trade is not None:
        trade = await trade_service.lock_product_then_trade(db, trade_id, trade.product_id)
    if not trade:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    if trade.status in (TradeStatus.COMPLETED.value, TradeStatus.TERMINATED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "已结束交易无冻结标记")
    await _resolve_trade_case(db, trade, admin.id, body.case_id)
    was_frozen = trade.frozen
    await moderation.unfreeze_trade(db, trade, body.reason.strip(), admin.id)
    if was_frozen and not trade.frozen:
        await audit_service.record_event(
            db,
            audit_service.EVENT_ADMIN_TRADE_UNFREEZE,
            target_type="trade",
            target_id=trade.id,
            before={"frozen": True},
            after={"frozen": False},
        )
    await db.commit()
    return {"detail": "冻结已解除"}


@router.post("/{trade_id}/adjust")
async def adjust_status(trade_id: int, body: AdjustIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """BR-08: the claiming administrator may adjust any status with a basis (including completing directly) without fabricating both parties' confirmations.

    The lock order is fixed as "product → target trade": first locate/validate the trade
    by case eligibility, then lock the product, lock the trade, and refresh state with
    ``populate_existing``. This shares the same product lock as accept and create_request;
    when restoring a locking status, rerun the D-48 conflict check after locking and do
    not rely on a pre-lock cached object.
    """
    if body.to_status not in ALLOWED_ADJUST_TARGETS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "非法目标状态")
    # Validate administrator case eligibility first; thereafter use only scalar IDs so a rolled-back session never dereferences expired objects.
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    case = await _resolve_trade_case(db, trade, admin.id, body.case_id)
    admin_id = admin.id
    product_id = trade.product_id
    case_id = case.id

    # Explicit retryable transaction errors (40P01/40001) get a limited whole-transaction
    # retry after rollback; notifications, audits, and transitions share that transaction
    # and are not duplicated. Other database errors propagate as-is and are not blindly mapped to 409.
    for attempt in range(2):
        try:
            # Unified lock order: product → target trade. Locking the product waits for
            # peer transactions such as accept/request; refreshing state after locking the
            # trade prevents a stale status in the identity map from overwriting committed state.
            product = await trade_service.lock_product_for_update(db, product_id)
            trade = await trade_service.lock_trade_for_update(db, trade_id)
            if trade is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
            if trade.status == body.to_status:
                raise HTTPException(status.HTTP_409_CONFLICT, "交易已处于目标状态")

            # D-48: after locking, check for another locking trade on the same product; the
            # precheck only rejects early and cannot justify restoration. On conflict, the
            # trade, confirmations, product, branch, and restrictions are all still untouched.
            if body.to_status in LOCKING_TARGETS:
                await trade_service.ensure_no_locking_conflict(db, trade, body.to_status)

            from_status = trade.status
            to_status = TradeStatus(body.to_status)
            reason = body.reason.strip()
            if to_status in (TradeStatus.COMPLETED, TradeStatus.TERMINATED):
                # End cascade: unfreeze this trade, archive the branch, delist the product by default (BR-33/14)
                await trade_ops.finish_trade(
                    db, trade, to_status=to_status, trigger=f"admin_adjust_{body.to_status}",
                    actor=admin, actor_role="admin", reason=reason, basis_case_id=case_id,
                )
                await audit_service.record_event(
                    db,
                    audit_service.EVENT_ADMIN_TRADE_ADJUST,
                    target_type="trade",
                    target_id=trade.id,
                    reason_code=f"to_{body.to_status}",
                    before={"status": from_status},
                    after={"status": trade.status, "case_id": case_id},
                )
                await db.commit()
                return {"detail": f"交易状态已调整为 {body.to_status}，已通知双方并留据"}

            if to_status == TradeStatus.IN_PROGRESS:
                # Resume in progress: clear current confirmations, end the old timer, keep history and the effective agreement; resumption does not start the timer (4.15/D-51)
                await trade_ops.clear_current_confirmations(db, trade.id)
                trade_wait.clear_wait_state(trade)
                trade.resolution_confirmed_by_id = None
                trade.resolution_confirmed_at = None
            elif to_status in (TradeStatus.DISPUTED, TradeStatus.ABNORMAL):
                # Entering disputed/abnormal only ends the existing wait; restoring a previously completed trade also clears current confirmations (D-48)
                if from_status in ENDED_TARGETS:
                    await trade_ops.clear_current_confirmations(db, trade.id)
                trade_wait.clear_wait_state(trade)
            else:
                # Leaving the locking/waiting state: end the old timer so the next stage does not inherit a previous pause
                trade_wait.clear_wait_state(trade)

            trade.status = to_status.value
            # Non-ended targets keep no finish time; restoring an old trade clears the existing finished_at.
            trade.finished_at = None
            if to_status in (TradeStatus.IN_PROGRESS, TradeStatus.DISPUTED, TradeStatus.ABNORMAL) and trade.accepted_at is None:
                trade.accepted_at = trade_ops.now_utc()

            if product is not None:
                if to_status.value in LOCKING_TARGETS:
                    # Locking target: the product enters in-transaction and the previous delist timestamp is cleared.
                    product.status = ProductStatus.IN_TRANSACTION.value
                    product.delisted_at = None
                    # BR-02/DT-01: entering a locking status must not bypass the existing "close other pending requests automatically" rule.
                    others = await trade_service.close_pending_requests_for_product(
                        db, product.id, trade_service.CLOSED_BY_LOCK, exclude_trade_ids={trade.id}
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
                elif (
                    to_status in (TradeStatus.PENDING_ACCEPTANCE, TradeStatus.REJECTED, TradeStatus.WITHDRAWN, TradeStatus.CLOSED)
                    and product.status == ProductStatus.IN_TRANSACTION.value
                    and from_status in LOCKING_TARGETS
                ):
                    # Release visibility only when this trade held the lock, no other lock
                    # exists, and public eligibility was not revoked; adjusting an old completed
                    # trade must not interrupt another lock or turn a restricted product into listed.
                    other_locking = await trade_service.get_locking_trade(db, product_id)
                    if other_locking is None and not product.display_restricted:
                        product.status = ProductStatus.LISTED.value
                        product.delisted_at = None

            trigger = "admin_restore" if to_status == TradeStatus.IN_PROGRESS else f"admin_adjust_{body.to_status}"
            await trade_ops.record_transition(
                db, trade, from_status, to_status.value,
                trigger=trigger, actor=admin, actor_role="admin", reason=reason, basis_case_id=case_id,
            )
            await _notify_adjustment(
                db, trade, from_status=from_status, to_status=to_status.value, reason=reason, case_id=case_id
            )
            await audit_service.record_event(
                db,
                audit_service.EVENT_ADMIN_TRADE_ADJUST,
                target_type="trade",
                target_id=trade.id,
                reason_code=f"to_{body.to_status}",
                before={"status": from_status},
                after={"status": trade.status, "case_id": case_id},
            )
            await db.commit()
            return {"detail": f"交易状态已调整为 {body.to_status}，已通知双方并留据"}
        except IntegrityError as exc:
            # D-48: a legacy writer that ignores the product lock may still race the post-lock check; the unique index is the final arbiter.
            await trade_service.resolve_lock_integrity_error(db, exc, product_id=product_id)
        except DBAPIError as exc:
            await db.rollback()
            if not trade_service.is_retryable_transaction_error(exc):
                raise
            if attempt == 0:
                # Rollback expires current ORM objects; reload before retrying and never read
                # an expired admin.id/role after failure, which would trigger MissingGreenlet.
                reloaded_admin = await db.get(User, admin_id, populate_existing=True)
                if reloaded_admin is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员账户不存在")
                admin = reloaded_admin
                continue
            raise HTTPException(status.HTTP_409_CONFLICT, "并发冲突，请重试") from exc
    raise HTTPException(status.HTTP_409_CONFLICT, "并发冲突，请重试")

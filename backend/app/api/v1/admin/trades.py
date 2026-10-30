"""管理员交易处置（BR-08/33）：冻结/解冻、有依据调整全部状态。"""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import col, select

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
    """管理视角交易概要（含约定/确认/转移历史）。"""
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
    reason: str = Field(min_length=1, max_length=500)
    case_id: int | None = None


class UnfreezeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    case_id: int | None = None  # 关联处置事项（依据）


class AdjustIn(BaseModel):
    to_status: str
    reason: str = Field(min_length=1, max_length=500)
    case_id: int | None = None  # 关联处置事项（依据）


async def _case_relevant_to_trade(db, case: DisposalCase, trade: Trade) -> bool:
    """事项须与本笔交易直接相关，而非仅同商品或任意账户。

    绑定具体交易的事项只对本笔交易有效；case.trade_id 指向其他交易时，
    不得再因 product_id 相同而绕过。日常商品审核事项本身不授予后来任何
    私人交易权限。合法依据限：本笔交易事项、指向本商品的真实违规举报、
    指向本笔交易评价或本交易分支消息的举报、举报处置实际封禁当事账户
    留下的限制记录，以及当事账户的封禁事项；已处置/已解除状态不失效。
    不接受仅凭任意 subject_user 事项、任意用户举报、其他事项的限制记录、
    普通私聊消息或本人认领事项扩大私人交易访问。
    """
    if case.trade_id is not None:
        return case.trade_id == trade.id
    if (
        case.case_type == CaseType.ACCOUNT_BAN.value
        and case.subject_user_id in (trade.buyer_id, trade.seller_id)
    ):
        return True
    # 举报处置的 ban_user 以原举报事项记录 AccountRestriction，并未另建
    # ACCOUNT_BAN 事项；须读取真实限制记录，不能凭 subject_user 推断。
    # 只认与本事项 id 精确关联、且被封禁者确为本交易一方的 ban 记录；
    # 不按 active 过滤，封禁后已 lifted 的历史仍支撑后续查看/调整。
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
                # 仅交易分支消息可定位到本笔交易；普通私聊无 trade_id，
                # 其他交易分支指向别的 trade_id，均不得借此访问本交易。
                message = await db.get(Message, report.target_id)
                if message is not None:
                    conversation = await db.get(Conversation, message.conversation_id)
                    if conversation is not None and conversation.trade_id == trade.id:
                        return True
    return False


async def _resolve_trade_case(
    db, trade: Trade, admin_id: int, case_id: int | None
) -> DisposalCase:
    """BR-27/34：私人交易读取与冻结/解冻/调整须由相关事项认领管理员执行。

    未传 case_id 时只能自动选择本人已认领且确与本交易相关的事项；
    缺省绝不等于独立维护放行。已处置事项仍可作为后续合法处置依据。
    """
    if case_id is not None:
        case = await db.get(DisposalCase, case_id)
        if not case:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "关联事项不存在")
        if case.claimed_by_id != admin_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "仅该事项认领管理员可查看或处理该交易")
        if not await _case_relevant_to_trade(db, case, trade):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "关联事项与该交易无关")
        return case
    result = await db.exec(
        select(DisposalCase)
        .where(col(DisposalCase.claimed_by_id) == admin_id)
        .order_by(col(DisposalCase.id).desc())
    )
    for case in result:
        if await _case_relevant_to_trade(db, case, trade):
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
    """管理视角交易详情（BR-27：按事项必要范围访问）。"""
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
    """非结束状态的解冻须管理员有依据处理（BR-33）；符合条件时续算剩余等待（D-51）。"""
    trade = await db.get(Trade, trade_id)
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
    """BR-08：认领管理员可有依据调整全部状态（包括直接完成），不伪造双方确认。

    锁序固定为“商品 → 目标交易”：先按事项资格定位/校验交易，再锁商品、锁交易并
    ``populate_existing`` 刷新状态。这样与 accept、create_request 共用同一把商品锁；
    恢复锁单时在锁后重新执行 D-48 冲突校验，不能依据加锁前的缓存对象放行。
    """
    if body.to_status not in ALLOWED_ADJUST_TARGETS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "非法目标状态")
    # 先完成管理员相关事项资格校验；此后只使用标量 ID，避免回滚后引用过期对象。
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    case = await _resolve_trade_case(db, trade, admin.id, body.case_id)
    admin_id = admin.id
    product_id = trade.product_id
    case_id = case.id

    # 明确可重试事务错误（40P01/40001）整事务回滚后有限重试；通知、审计、转移
    # 均在同一事务内，回滚后不会重复。其他数据库错误原样抛出，不盲目映射 409。
    for attempt in range(2):
        try:
            # 统一锁序：商品 → 目标交易。锁商品会等待 accept/request 等同类事务；
            # 锁交易后刷新状态，避免 identity map 中的旧 status 覆盖已提交状态。
            product = await trade_service.lock_product_for_update(db, product_id)
            trade = await trade_service.lock_trade_for_update(db, trade_id)
            if trade is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
            if trade.status == body.to_status:
                raise HTTPException(status.HTTP_409_CONFLICT, "交易已处于目标状态")

            # D-48：锁后再检查同商品另一笔锁单；预检查只用于早期拒绝，不能作为
            # 恢复依据。冲突时交易、确认、商品、分支与限制均尚未修改。
            if body.to_status in LOCKING_TARGETS:
                await trade_service.ensure_no_locking_conflict(db, trade, body.to_status)

            from_status = trade.status
            to_status = TradeStatus(body.to_status)
            reason = body.reason.strip()
            if to_status in (TradeStatus.COMPLETED, TradeStatus.TERMINATED):
                # 结束联动：解本笔冻结、归档分支、商品默认下架（BR-33/14）
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
                # 恢复进行中：清当前确认、结束旧计时、保留历史与有效约定；恢复不启动计时（4.15/D-51）
                await trade_ops.clear_current_confirmations(db, trade.id)
                trade_wait.clear_wait_state(trade)
                trade.resolution_confirmed_by_id = None
                trade.resolution_confirmed_at = None
            elif to_status in (TradeStatus.DISPUTED, TradeStatus.ABNORMAL):
                # 进入争议/异常只结束原等待；恢复已完成旧交易时另清当前确认（D-48）
                if from_status in ENDED_TARGETS:
                    await trade_ops.clear_current_confirmations(db, trade.id)
                trade_wait.clear_wait_state(trade)
            else:
                # 离开锁单/等待状态：结束旧计时，避免下一阶段继承旧轮暂停
                trade_wait.clear_wait_state(trade)

            trade.status = to_status.value
            # 非结束目标不保留结束时间；恢复旧交易时清除原有 finished_at。
            trade.finished_at = None
            if to_status in (TradeStatus.IN_PROGRESS, TradeStatus.DISPUTED, TradeStatus.ABNORMAL) and trade.accepted_at is None:
                trade.accepted_at = trade_ops.now_utc()

            if product is not None:
                if to_status.value in LOCKING_TARGETS:
                    # 锁单目标：商品进入交易中，解除此前的下架时间标记。
                    product.status = ProductStatus.IN_TRANSACTION.value
                    product.delisted_at = None
                    # BR-02/DT-01：进入锁单不得绕过“其余待接受请求自动关闭”的既有规则。
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
                    # 仅本笔交易原持有锁单、确无其他锁单且公开资格未被撤销时释放展示；
                    # 不因调整旧已完成交易而擅自打断另一笔锁单或让受限商品变 listed。
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
            # D-48：锁后校验仍可能被不遵守商品锁的旧写入抢跑；唯一索引是最终裁决。
            await trade_service.resolve_lock_integrity_error(db, exc, product_id=product_id)
        except DBAPIError as exc:
            await db.rollback()
            if not trade_service.is_retryable_transaction_error(exc):
                raise
            if attempt == 0:
                # 回滚会 expire 当前 ORM 对象；重试前重新加载，禁止失败后读取
                # expired admin.id/角色触发 MissingGreenlet。
                reloaded_admin = await db.get(User, admin_id, populate_existing=True)
                if reloaded_admin is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员账户不存在")
                admin = reloaded_admin
                continue
            raise HTTPException(status.HTTP_409_CONFLICT, "并发冲突，请重试") from exc
    raise HTTPException(status.HTTP_409_CONFLICT, "并发冲突，请重试")

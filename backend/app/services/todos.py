"""用户待办聚合（D-53、4.17）：每次读取按当前有资格且需处理的既有事项派生。

不新增任务类型、业务记录或权限；通知已读状态不参与待办判定。
管理员待办来自共享处理池，个人待办恒为空。
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CompletionConfirmation,
    DisposalCase,
    DisposalMessage,
    Trade,
    TradeAgreement,
    User,
)
from app.models.enums import (
    AccountStatus,
    AgreementStatus,
    CaseStatus,
    DisposalMessageKind,
    DisposalMessageRole,
    TradeStatus,
    UserRole,
)
from app.services.permissions import frozen_trade_party_ids

# 进入聚合的本人事项类型（稳定 key，不随通知或已读变化）
KIND_REQUEST = "request_pending"
KIND_AGREEMENT = "agreement_pending"
KIND_CANCEL = "cancel_pending"
KIND_COMPLETION = "completion_confirm"
KIND_DISPUTE = "dispute_resolution"
KIND_INQUIRY = "inquiry_pending"

TRADE_TODO_STATUSES = (
    TradeStatus.PENDING_ACCEPTANCE.value,
    TradeStatus.IN_PROGRESS.value,
    TradeStatus.DISPUTED.value,
)


def _item(kind: str, object_id: int, title: str, link_type: str, link_id: int, action: str) -> dict:
    return {
        "key": f"{kind}:{object_id}",
        "kind": kind,
        "title": title,
        "link_type": link_type,
        "link_id": link_id,
        "action": action,
    }


async def build_todos(db: AsyncSession, user: User) -> list[dict]:
    """返回当前用户有动作资格的待办列表；只读，不创建或修改业务记录。"""
    if user.role == UserRole.ADMIN.value:
        return []

    items: list[dict] = []
    banned = user.status == AccountStatus.BANNED.value

    # 交易类待办：封禁或本人/对方存在任一有效交易冻结时动作被禁止，不列出；
    # BR-33 的冻结是用户级交易限制，IM 的双方作用域不在此处混用。
    if not banned:
        frozen_users = await frozen_trade_party_ids(db)
        trades = list(
            (
                await db.execute(
                    select(Trade).where(
                        or_(Trade.buyer_id == user.id, Trade.seller_id == user.id),
                        Trade.status.in_(TRADE_TODO_STATUSES),
                    )
                )
            ).scalars()
        )
        trade_ids = [trade.id for trade in trades]

        pending_agreements: dict[int, TradeAgreement] = {}
        effective_agreement_ids: set[int] = set()
        confirmers: dict[int, set[int]] = {}
        if trade_ids:
            for agreement in (
                await db.execute(
                    select(TradeAgreement).where(
                        TradeAgreement.trade_id.in_(trade_ids),
                        TradeAgreement.status == AgreementStatus.PROPOSED.value,
                    )
                )
            ).scalars():
                pending_agreements[agreement.trade_id] = agreement
            for agreement_id in (
                await db.execute(
                    select(TradeAgreement.id).where(
                        TradeAgreement.trade_id.in_(trade_ids),
                        TradeAgreement.status == AgreementStatus.CONFIRMED.value,
                    )
                )
            ).scalars():
                effective_agreement_ids.add(agreement_id)
            for confirmation in (
                await db.execute(
                    select(CompletionConfirmation).where(
                        CompletionConfirmation.trade_id.in_(trade_ids),
                        CompletionConfirmation.is_current.is_(True),
                    )
                )
            ).scalars():
                confirmers.setdefault(confirmation.trade_id, set()).add(confirmation.confirmer_id)

        for trade in trades:
            other_id = trade.seller_id if trade.buyer_id == user.id else trade.buyer_id
            # 本人或本笔对方被任一有效交易冻结：双方交易写操作均暂停（BR-33）。
            if user.id in frozen_users or other_id in frozen_users:
                continue
            if trade.status == TradeStatus.PENDING_ACCEPTANCE.value:
                if trade.seller_id == user.id:
                    items.append(
                        _item(
                            KIND_REQUEST,
                            trade.id,
                            f"购买请求待接受（交易 #{trade.id}）",
                            "trade",
                            trade.id,
                            "accept_request",
                        )
                    )
                continue

            # 约定确认仅在交易进行中可操作；争议中提案不能作为可执行约定确认。
            if trade.status == TradeStatus.IN_PROGRESS.value:
                agreement = pending_agreements.get(trade.id)
                if agreement and agreement.proposer_id != user.id:
                    items.append(
                        _item(
                            KIND_AGREEMENT,
                            trade.id,
                            f"交易约定待确认（交易 #{trade.id}）",
                            "trade",
                            trade.id,
                            "confirm_agreement",
                        )
                    )
                # 有效约定存在且本人尚未确认即可操作，不要求对方先确认（BR-04/FR-06）。
                if (
                    trade.current_agreement_id
                    and trade.current_agreement_id in effective_agreement_ids
                    and user.id not in confirmers.get(trade.id, set())
                ):
                    items.append(
                        _item(
                            KIND_COMPLETION,
                            trade.id,
                            f"交易完成待确认（交易 #{trade.id}）",
                            "trade",
                            trade.id,
                            "confirm_completion",
                        )
                    )
            if trade.cancel_requested_by_id and trade.cancel_requested_by_id != user.id:
                items.append(
                    _item(
                        KIND_CANCEL,
                        trade.id,
                        f"取消申请待确认（交易 #{trade.id}）",
                        "trade",
                        trade.id,
                        "confirm_cancel",
                    )
                )
            if (
                trade.status == TradeStatus.DISPUTED.value
                and trade.resolution_confirmed_by_id
                and trade.resolution_confirmed_by_id != user.id
            ):
                items.append(
                    _item(
                        KIND_DISPUTE,
                        trade.id,
                        f"争议解决确认待提交（交易 #{trade.id}）",
                        "trade",
                        trade.id,
                        "confirm_dispute_resolution",
                    )
                )

    # 管理沟通：本人作为被询问人的当前未回答问询；封禁/冻结时仍保留
    cases = list(
        (
            await db.execute(
                select(DisposalCase).where(
                    DisposalCase.subject_user_id == user.id,
                    DisposalCase.status != CaseStatus.DISPOSED.value,
                )
            )
        ).scalars()
    )
    for case in cases:
        last_inquiry: DisposalMessage | None = None
        answered = False
        for message in case.messages:
            if message.kind == DisposalMessageKind.INQUIRY.value:
                last_inquiry = message
                answered = False
            elif (
                last_inquiry is not None
                and message.role == DisposalMessageRole.USER.value
                and message.kind == DisposalMessageKind.STATEMENT.value
            ):
                answered = True
        if last_inquiry is not None and not answered:
            items.append(
                _item(
                    KIND_INQUIRY,
                    case.id,
                    f"管理问询待说明：{case.title}",
                    "case",
                    case.id,
                    "submit_statement",
                )
            )

    # 稳定顺序；key 由 kind + 对象 id 组成，同一事项重复读取结果一致
    return sorted(items, key=lambda item: (item["kind"], item["link_id"], item["key"]))

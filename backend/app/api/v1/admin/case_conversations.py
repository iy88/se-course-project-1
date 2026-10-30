"""管理员按认领事项必要范围读取会话（BR-19/27/34；SC-04-07、SC-06-04）。

本模块只提供“明确事项 + 明确会话”的只读入口：不提供会话列表，不把管理员
加入普通会话成员，也不改变任何一方的已读进度。可读取范围严格限于现有规则
能够确定的两种关联：

- 消息举报事项：仅被举报目标消息所在的那一个会话；
- 交易争议／异常交易事项：仅事项直接关联交易的交易分支。

商品审核、账户封禁及商品／评论／评价／用户举报等事项，现行规则没有授予
私聊读取依据，统一拒绝；不因商品相同、审核历史或其他事项扩大访问范围。
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import CurrentAdmin, DbSession
from app.models import Conversation, DisposalCase, Message, Report, Trade
from app.models.enums import CaseType, ConversationType, ReportTargetType
from app.services import audit as audit_service
from app.services.cases import ensure_claimant

router = APIRouter(prefix="/admin/cases", tags=["admin-cases"])

# 稳定审计契约：访问本身留痕，但不写入消息正文或用户资料。
EVENT_ADMIN_CASE_CONVERSATION_READ = "admin.case_conversation_read"

_TRADE_BRANCH_CASE_TYPES = (CaseType.TRADE_DISPUTE.value, CaseType.ABNORMAL_TRADE.value)


async def _message_report_target(db, case: DisposalCase) -> tuple[int, int] | None:
    """消息举报的（目标消息 ID，所属会话 ID）；其他举报没有可读会话。"""
    if case.report_id is None:
        return None
    report = await db.get(Report, case.report_id)
    if report is None or report.target_type != ReportTargetType.MESSAGE.value:
        return None
    message = await db.get(Message, report.target_id)
    if message is None:
        return None
    return report.target_id, message.conversation_id


async def _trade_branch_conversation_id(db, case: DisposalCase) -> int | None:
    """事项直接关联交易的唯一分支；不按商品或用户组合推断其他分支。"""
    if case.trade_id is None:
        return None
    trade = await db.get(Trade, case.trade_id)
    if trade is None:
        return None
    low, high = sorted((trade.buyer_id, trade.seller_id))
    return (await db.exec(
        select(col(Conversation.id)).where(
            col(Conversation.type) == ConversationType.TRADE.value,
            col(Conversation.trade_id) == trade.id,
            col(Conversation.user_low_id) == low,
            col(Conversation.user_high_id) == high,
        )
    )).first()


@router.get("/{case_id}/conversations/{conversation_id}")
async def read_case_conversation(
    case_id: int,
    conversation_id: int,
    admin: CurrentAdmin,
    db: DbSession,
    before_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    """按事项必要范围读取单个会话历史；只读，不推进已读、不发消息、不改成员。"""
    case = await db.get(DisposalCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    # 先校验认领归属：未认领或他人认领的管理员不进入任何关联解析。
    await ensure_claimant(case, admin.id)

    related_message_id: int | None = None
    relation: str = ""
    allowed_conversation_id: int | None = None
    if case.case_type == CaseType.REPORT.value:
        target = await _message_report_target(db, case)
        if target is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "该举报事项没有可读取的消息会话（仅消息举报在必要范围内）",
            )
        related_message_id, allowed_conversation_id = target
        relation = "report_message"
    elif case.case_type in _TRADE_BRANCH_CASE_TYPES:
        allowed_conversation_id = await _trade_branch_conversation_id(db, case)
        if allowed_conversation_id is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "该事项没有直接关联的交易分支",
            )
        relation = "trade_branch"
    else:
        # 商品审核、账户封禁及其他举报类型没有私聊读取依据，明确拒绝。
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "该事项类型不授予会话读取范围",
        )

    if allowed_conversation_id != conversation_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该会话不在本事项必要范围内")

    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    # 二次确认解析结果仍指向当前会话本身；以后新增事项类型也不得跳过该检查。
    if case.case_type in _TRADE_BRANCH_CASE_TYPES and (
        conversation.type != ConversationType.TRADE.value
        or conversation.trade_id != case.trade_id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该会话不在本事项必要范围内")

    query = select(Message).where(col(Message.conversation_id) == conversation.id)
    if before_id is not None:
        query = query.where(col(Message.id) < before_id)
    rows = list(
        await db.exec(query.order_by(col(Message.id).desc()).limit(limit + 1))
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    page.reverse()

    # 访问本身留痕：与本次读取同事务提交；不写消息正文、成员资料或已读值。
    await audit_service.record_event(
        db,
        EVENT_ADMIN_CASE_CONVERSATION_READ,
        target_type="conversation",
        target_id=conversation.id,
        after={
            "case_id": case.id,
            "relation": relation,
            "returned": len(page),
            "limit": limit,
        },
    )
    await db.commit()

    return {
        "scope": {
            "case_id": case.id,
            "case_type": case.case_type,
            "relation": relation,
            "report_id": case.report_id,
            "trade_id": case.trade_id,
            "target_message_id": related_message_id,
        },
        "conversation": {
            "id": conversation.id,
            "type": conversation.type,
            "trade_id": conversation.trade_id,
            "archived": conversation.archived,
        },
        "messages": [
            {
                "id": message.id,
                "sender_id": message.sender_id,
                "kind": message.kind,
                "content": message.content,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            for message in page
        ],
        "has_more": has_more,
        "next_before_id": page[0].id if has_more and page else None,
    }

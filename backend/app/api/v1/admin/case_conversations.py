"""Administrators read conversations only to the extent necessary for a claimed case (BR-19/27/34; SC-04-07, SC-06-04).

This module exposes only a read-only entry point for an "explicit case + explicit
conversation": it provides no conversation list, does not add administrators as
members of regular conversations, and does not change either party's read progress.
Readable scope is strictly limited to the two relations current rules can determine:

- Message report case: only the single conversation containing the reported target message;
- Trade dispute/abnormal trade case: only the trade branch of the trade directly linked to the case.

For product review, account ban, and product/comment/review/user report cases, current
rules grant no private-chat access basis, so all are rejected; a shared product, review
history, or other case never widens the access scope.
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import CurrentAdmin, DbSession
from app.models import Conversation, DisposalCase, Message, Report, Trade
from app.models.enums import CaseType, ConversationType, ReportTargetType
from app.services import audit as audit_service
from app.services.cases import ensure_claimant

router = APIRouter(prefix="/admin/cases", tags=["admin-cases"])

# Stable audit contract: the access itself is recorded, but message bodies and user profiles are not written.
EVENT_ADMIN_CASE_CONVERSATION_READ = "admin.case_conversation_read"

_TRADE_BRANCH_CASE_TYPES = (CaseType.TRADE_DISPUTE.value, CaseType.ABNORMAL_TRADE.value)


async def _message_report_target(db, case: DisposalCase) -> tuple[int, int] | None:
    """(target message ID, containing conversation ID) for a message report; other reports have no readable conversation."""
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
    """The single branch of the trade directly linked to the case; never infer other branches from a product or user combination."""
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
    """Read one conversation's history within the case's necessary scope; read-only, advancing no read state, sending no messages, and changing no members."""
    case = await db.get(DisposalCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    # Validate claim ownership first: a case that is unclaimed or claimed by another administrator never enters any relation resolution.
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
        # Product review, account ban, and other report types have no private-chat access basis and are rejected explicitly.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "该事项类型不授予会话读取范围",
        )

    if allowed_conversation_id != conversation_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "该会话不在本事项必要范围内")

    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    # Confirm again that the resolved result still points to this conversation; future case types must not skip this check.
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

    # Record the access itself in the same transaction as this read; do not write message bodies, member profiles, or read values.
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

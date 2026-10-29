"""第二轮复查回归：R3/R4/R5/R13/R14、D52/DT03。

只使用真实 API + SQLite 持久状态断言；旧测试的合法事项夹具不削弱权限校验。
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.models import (
    AccountRestriction,
    CompletionConfirmation,
    Conversation,
    DisposalCase,
    Notification,
    Product,
    Report,
    Trade,
    TradeReview,
    TradeTransition,
    User,
)
from app.services.trade_timeout import scan_once
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import (
    admin_headers,
    create_listed_product,
    make_admin,
    user_headers,
)

pytestmark = pytest.mark.asyncio

AGREEMENT = {
    "delivery_time": "周六上午十点",
    "delivery_location": "东门快递站旁",
    "delivery_method": "当面交付",
    "amount_cents": 1000,
    "payment_method": "微信转账",
    "payment_timing": "当面付清",
}
CLOSED_BY_LOCK = "商品已被其他用户锁单"


@pytest.fixture
async def setup(client, db):
    await make_admin(db)
    return {
        "admin": await admin_headers(client),
        "seller": await user_headers(client, "seller-r2@t.com", "卖方"),
        "buyer": await user_headers(client, "buyer-r2@t.com", "买方"),
        "other": await user_headers(client, "other-r2@t.com", "其他买方"),
        "seller2": await user_headers(client, "seller2-r2@t.com", "卖方二"),
    }


async def _user_id(db, email: str) -> int:
    db.expunge_all()
    user = await db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user.id


async def _trade(db, trade_id: int) -> Trade:
    db.expunge_all()
    trade = await db.get(Trade, trade_id)
    assert trade is not None
    return trade


async def _product(db, product_id: int) -> Product:
    db.expunge_all()
    product = await db.get(Product, product_id)
    assert product is not None
    return product


async def _conversation(db, trade_id: int) -> Conversation:
    db.expunge_all()
    conversation = await db.scalar(
        select(Conversation).where(Conversation.trade_id == trade_id, Conversation.type == "trade")
    )
    assert conversation is not None
    return conversation


async def _confirmations(db, trade_id: int) -> list[CompletionConfirmation]:
    db.expunge_all()
    return list(
        (
            await db.execute(
                select(CompletionConfirmation)
                .where(CompletionConfirmation.trade_id == trade_id)
                .order_by(CompletionConfirmation.id)
            )
        ).scalars()
    )


async def _transitions(db, trade_id: int) -> list[TradeTransition]:
    db.expunge_all()
    return list(
        (
            await db.execute(
                select(TradeTransition)
                .where(TradeTransition.trade_id == trade_id)
                .order_by(TradeTransition.id)
            )
        ).scalars()
    )


async def _notifications(db, user_id: int) -> list[Notification]:
    db.expunge_all()
    return list(
        (
            await db.execute(
                select(Notification).where(Notification.user_id == user_id).order_by(Notification.id)
            )
        ).scalars()
    )


async def _claimed_case(
    client,
    admin_h,
    db,
    *,
    trade_id: int | None = None,
    product_id: int | None = None,
    subject_user_id: int | None = None,
    report_id: int | None = None,
    case_type: str = "trade_dispute",
) -> int:
    """真实相关事项 + 当前管理员认领，作为管理交易操作的合法上下文。"""
    case = DisposalCase(
        case_type=case_type,
        title=f"R2事项-{trade_id or report_id or product_id or subject_user_id}",
        trade_id=trade_id,
        product_id=product_id,
        subject_user_id=subject_user_id,
        report_id=report_id,
    )
    db.add(case)
    await db.commit()
    resp = await client.post(f"/api/v1/admin/cases/{case.id}/claim", headers=admin_h)
    assert resp.status_code == 200, resp.text
    return case.id


async def _claimed_report_case(
    client,
    admin_h,
    db,
    *,
    target_type: str,
    target_id: int,
    subject_user_id: int | None = None,
) -> int:
    """真实举报 + 认领事项；与 API 创建一致，仅通过 report_id 关联对象。"""
    report = Report(
        reporter_id=await _user_id(db, "buyer-r2@t.com"),
        target_type=target_type,
        target_id=target_id,
        reason="R5真实举报",
    )
    db.add(report)
    await db.commit()
    return await _claimed_case(
        client,
        admin_h,
        db,
        report_id=report.id,
        subject_user_id=subject_user_id,
        case_type="report",
    )


async def _accept_trade(client, admin_h, seller_h, buyer_h, *, title: str) -> tuple[dict, int]:
    product = await create_listed_product(client, admin_h, seller_h, title=title)
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    assert resp.status_code == 200, resp.text
    trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text
    return product, trade_id


async def _confirm_agreement(client, seller_h, buyer_h, trade_id: int) -> int:
    resp = await client.post(f"/api/v1/trades/{trade_id}/agreements", headers=buyer_h, json=AGREEMENT)
    assert resp.status_code == 200, resp.text
    agreement_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/trades/{trade_id}/agreements/{agreement_id}/confirm", headers=seller_h
    )
    assert resp.status_code == 200, resp.text
    return agreement_id


async def _completed_trade(client, admin_h, seller_h, buyer_h, *, title: str) -> tuple[dict, int, int]:
    product, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title=title)
    agreement_id = await _confirm_agreement(client, seller_h, buyer_h, trade_id)
    for headers in (buyer_h, seller_h):
        resp = await client.post(f"/api/v1/trades/{trade_id}/confirmations", headers=headers, json={})
        assert resp.status_code == 200, resp.text
    return product, trade_id, agreement_id


# ---------------- R3：全局交易冻结 ----------------

async def test_r3_frozen_user_blocks_all_trade_actions_but_not_unrelated_im_or_edit(client, db, setup):
    """BR-33/R3：交易冻结暂停双方全局交易资格；无关 IM 与无关商品合规编辑不受影响。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    other_h, seller2_h = setup["other"], setup["seller2"]

    # 冻结前准备：本组冻结交易、卖方无关商品、卖方二无关商品。
    seller_other_product = await create_listed_product(client, admin_h, seller_h, title="R3卖方无关商品")
    seller2_product = await create_listed_product(client, admin_h, seller2_h, title="R3卖方二商品")
    _, frozen_trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="R3冻结源交易")
    frozen_case = await _claimed_case(client, admin_h, db, trade_id=frozen_trade_id)
    assert (
        await client.post(
            f"/api/v1/admin/trades/{frozen_trade_id}/freeze",
            headers=admin_h,
            json={"reason": "违规核查", "case_id": frozen_case},
        )
    ).status_code == 200

    # 冻结后，任何一方发起新请求都被全局资格拦截（不是仅 pair_frozen）。
    resp = await client.post(
        "/api/v1/trades/requests", headers=other_h, json={"product_id": seller_other_product["id"]}
    )
    assert resp.status_code == 403, resp.text  # 卖方有全局冻结
    resp = await client.post(
        "/api/v1/trades/requests", headers=buyer_h, json={"product_id": seller2_product["id"]}
    )
    assert resp.status_code == 403, resp.text  # 买方有全局冻结
    resp = await client.post(
        "/api/v1/trades/requests", headers=seller2_h, json={"product_id": seller_other_product["id"]}
    )
    assert resp.status_code == 403, resp.text  # 卖方（对方）有全局冻结

    # 无关普通 IM 仍可用（IM 的冻结作用域仍是交易对）。
    normal = await client.post(
        "/api/v1/conversations/normal",
        headers=seller_h,
        json={"peer_user_id": await _user_id(db, "other-r2@t.com")},
    )
    assert normal.status_code == 201, normal.text
    resp = await client.post(
        f"/api/v1/conversations/{normal.json()['id']}/messages",
        headers=seller_h,
        json={"content": "无关聊天保持可用"},
    )
    assert resp.status_code == 200, resp.text

    # 无关商品合规编辑保持可用（D-50）。
    resp = await client.patch(
        f"/api/v1/products/{seller_other_product['id']}",
        headers=seller_h,
        json={"description": "无关商品合规微调，九成新"},
    )
    assert resp.status_code == 200, resp.text


async def test_r3_frozen_user_cannot_accept_reject_withdraw_or_progress_other_trades(client, db, setup):
    """R3：撤回、接受/拒绝、约定、完成确认、取消、取消确认/撤回、争议及解决均校验双方全局资格。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    seller2_h = setup["seller2"]

    _, frozen_trade_id = await _accept_trade(
        client, admin_h, seller_h, buyer_h, title="R3全局冻结源"
    )
    frozen_case = await _claimed_case(client, admin_h, db, trade_id=frozen_trade_id)

    # 待接受交易 T2（buyer 买、seller2 卖）。
    pending_product = await create_listed_product(client, admin_h, seller2_h, title="R3待接受无关交易")
    resp = await client.post(
        "/api/v1/trades/requests", headers=buyer_h, json={"product_id": pending_product["id"]}
    )
    pending_trade_id = resp.json()["id"]

    # 进行中交易 T3（已确认约定、尚有取消申请）。
    progress_product, progress_trade_id = await _accept_trade(
        client, admin_h, seller2_h, buyer_h, title="R3进行中无关交易"
    )
    await _confirm_agreement(client, seller2_h, buyer_h, progress_trade_id)
    resp = await client.post(f"/api/v1/trades/{progress_trade_id}/cancel", headers=buyer_h, json={})
    assert "等待对方同意" in resp.json()["detail"]

    # 争议交易 T4（buyer 已单方确认后由 seller2 发起争议）。
    dispute_product, dispute_trade_id = await _accept_trade(
        client, admin_h, seller2_h, buyer_h, title="R3争议无关交易"
    )
    await _confirm_agreement(client, seller2_h, buyer_h, dispute_trade_id)
    resp = await client.post(f"/api/v1/trades/{dispute_trade_id}/confirmations", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/trades/{dispute_trade_id}/disputes", headers=seller2_h, json={"description": "待解决"}
    )
    assert resp.status_code == 200, resp.text

    # 冻结源交易后，buyer 的全局资格应阻止其他交易的全部写操作。
    resp = await client.post(
        f"/api/v1/admin/trades/{frozen_trade_id}/freeze",
        headers=admin_h,
        json={"reason": "核查全局交易限制", "case_id": frozen_case},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(f"/api/v1/trades/{pending_trade_id}/accept", headers=seller2_h)
    assert resp.status_code == 403, resp.text
    resp = await client.post(
        f"/api/v1/trades/{pending_trade_id}/reject", headers=seller2_h, json={"reason": "不卖"}
    )
    assert resp.status_code == 403, resp.text
    resp = await client.post(f"/api/v1/trades/{pending_trade_id}/withdraw", headers=buyer_h)
    assert resp.status_code == 403, resp.text

    resp = await client.post(
        f"/api/v1/trades/{progress_trade_id}/agreements", headers=buyer_h, json=AGREEMENT
    )
    assert resp.status_code == 403, resp.text
    resp = await client.post(
        f"/api/v1/trades/{progress_trade_id}/confirmations", headers=buyer_h, json={}
    )
    assert resp.status_code == 403, resp.text
    resp = await client.post(f"/api/v1/trades/{progress_trade_id}/cancel", headers=buyer_h, json={})
    assert resp.status_code == 403, resp.text
    resp = await client.post(f"/api/v1/trades/{progress_trade_id}/cancel/confirm", headers=seller2_h, json={})
    assert resp.status_code == 403, resp.text
    resp = await client.post(f"/api/v1/trades/{progress_trade_id}/cancel/withdraw", headers=buyer_h)
    assert resp.status_code == 403, resp.text
    resp = await client.post(
        f"/api/v1/trades/{progress_trade_id}/disputes", headers=seller2_h, json={"description": "冻结中"}
    )
    assert resp.status_code == 403, resp.text
    resp = await client.post(f"/api/v1/trades/{dispute_trade_id}/disputes/resolve", headers=buyer_h, json={})
    assert resp.status_code == 403, resp.text

    # 被拒操作不改变其他交易状态。
    assert (await _trade(db, pending_trade_id)).status == "pending_acceptance"
    progress = await _trade(db, progress_trade_id)
    assert progress.status == "in_progress"
    assert progress.cancel_requested_by_id is not None
    assert (await _trade(db, dispute_trade_id)).status == "disputed"
    assert (await _product(db, pending_product["id"])).status == "listed"
    assert (await _product(db, progress_product["id"])).status == "in_transaction"
    assert (await _product(db, dispute_product["id"])).status == "in_transaction"
    assert (await _trade(db, frozen_trade_id)).frozen is True


# ---------------- R4：封禁优先于手工解冻 ----------------

async def test_r4_manual_unfreeze_refused_while_participant_banned_then_unban_resumes(client, db, setup):
    """R4/D-51：封禁期间手工解冻拒绝且计时/确认不变；合法解封后才按剩余时间续算。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    _, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="R4封禁解冻")
    await _confirm_agreement(client, seller_h, buyer_h, trade_id)
    resp = await client.post(f"/api/v1/trades/{trade_id}/confirmations", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=2)
    await db.commit()

    buyer_id = await _user_id(db, "buyer-r2@t.com")
    resp = await client.post(
        f"/api/v1/admin/users/{buyer_id}/ban", headers=admin_h, json={"reason": "违规待复核"}
    )
    assert resp.status_code == 200, resp.text
    ban_case_id = resp.json()["case_id"]

    trade = await _trade(db, trade_id)
    assert trade.frozen is True
    paused_at = trade.confirm_wait_paused_at
    remaining = trade.confirm_wait_remaining_seconds
    current_ids = [c.id for c in await _confirmations(db, trade_id) if c.is_current]
    transition_count = len(await _transitions(db, trade_id))
    assert paused_at is not None and remaining is not None
    assert 4.9 * 86400 <= remaining <= 5.0 * 86400

    # 封禁事项作为合法上下文，但服务必须因其他有效限制仍生效而拒绝解冻。
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "提前解除", "case_id": ban_case_id},
    )
    assert resp.status_code == 403, resp.text
    trade = await _trade(db, trade_id)
    assert trade.frozen is True
    assert trade.status == "in_progress"
    assert trade.confirm_wait_paused_at.isoformat() == paused_at.isoformat()
    assert trade.confirm_wait_remaining_seconds == remaining
    assert [c.id for c in await _confirmations(db, trade_id) if c.is_current] == current_ids
    assert len(await _transitions(db, trade_id)) == transition_count
    assert not any(t.trigger == "trade_unfrozen" for t in await _transitions(db, trade_id))

    # 合法解封：封禁解除后自动解冻并按原剩余 5 天续算，不立即超时。
    resp = await client.post(
        f"/api/v1/admin/users/{buyer_id}/unban", headers=admin_h, json={"lift_reason": "复核解除"}
    )
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress" and trade.frozen is False
    assert trade.confirm_wait_paused_at is None and trade.confirm_wait_remaining_seconds is None
    assert trade.confirm_wait_started_at is not None
    elapsed = (datetime.now(UTC) - trade.confirm_wait_started_at.replace(tzinfo=UTC)).total_seconds()
    assert 2 * 86400 - 120 <= elapsed <= 2 * 86400 + 120
    assert [c.id for c in await _confirmations(db, trade_id) if c.is_current] == current_ids
    assert any(t.trigger == "trade_unfrozen" for t in await _transitions(db, trade_id))
    assert await scan_once(db) == 0


# ---------------- R5：管理员交易上下文 ----------------

async def test_r5_admin_trade_views_and_mutations_require_relevant_claimed_case(client, db, setup):
    """R5/BR-27/34：GET 与 freeze/unfreeze/adjust 均须本人认领且真实相关的事项。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    _, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="R5管理上下文")
    trade = await _trade(db, trade_id)
    product_id = trade.product_id

    relevant_case = await _claimed_case(client, admin_h, db, trade_id=trade_id)
    _, other_trade_id = await _accept_trade(
        client, admin_h, seller_h, buyer_h, title="R5无关事项交易"
    )
    unrelated_case = await _claimed_case(client, admin_h, db, trade_id=other_trade_id)

    # 第二个管理员：无事项、持他人认领事项均拒绝。
    await make_admin(db, email="admin2-r2@test.edu")
    admin2_h = await admin_headers(client, email="admin2-r2@test.edu")
    for headers in (admin2_h,):
        assert (await client.get(f"/api/v1/admin/trades/{trade_id}", headers=headers)).status_code == 403
        assert (
            await client.get(
                f"/api/v1/admin/trades/{trade_id}", headers=headers, params={"case_id": relevant_case}
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/admin/trades/{trade_id}/freeze",
                headers=headers,
                json={"reason": "越权冻结", "case_id": relevant_case},
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/admin/trades/{trade_id}/unfreeze",
                headers=headers,
                json={"reason": "越权解冻", "case_id": relevant_case},
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/admin/trades/{trade_id}/adjust",
                headers=headers,
                json={"to_status": "disputed", "reason": "越权调整", "case_id": relevant_case},
            )
        ).status_code == 403

    # 第一个管理员：传入本人认领但与交易无关的事项同样拒绝，且无副作用。
    transition_count = len(await _transitions(db, trade_id))
    notification_count = len(await _notifications(db, await _user_id(db, "buyer-r2@t.com")))
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress" and trade.frozen is False

    assert (
        await client.get(f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": unrelated_case})
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_id}/freeze",
            headers=admin_h,
            json={"reason": "无关事项", "case_id": unrelated_case},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_id}/adjust",
            headers=admin_h,
            json={"to_status": "disputed", "reason": "无关事项", "case_id": unrelated_case},
        )
    ).status_code == 403
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress" and trade.frozen is False
    assert len(await _transitions(db, trade_id)) == transition_count
    assert len(await _notifications(db, await _user_id(db, "buyer-r2@t.com"))) == notification_count

    # 缺省 case_id 时只能自动选择本人已认领的相关事项，不因持有一个无关事项而放行。
    resp = await client.get(f"/api/v1/admin/trades/{trade_id}", headers=admin_h)
    assert resp.status_code == 200, resp.text

    # 新交易无相关认领事项：即使管理员持有其他认领事项，GET 也拒绝。
    no_case_product, no_case_trade_id = await _accept_trade(
        client, admin_h, seller_h, buyer_h, title="R5无相关事项交易"
    )
    # 真实商品审核事项仍由审核管理员认领且已处置；该身份不能成为
    # 后来同商品私人交易的通行证。
    admin_id = await _user_id(db, "admin@test.edu")
    review_case = await db.scalar(
        select(DisposalCase).where(
            DisposalCase.case_type == "product_review",
            DisposalCase.product_id == no_case_product["id"],
        )
    )
    assert review_case is not None
    assert review_case.claimed_by_id == admin_id
    assert review_case.status == "disposed"

    transition_count = len(await _transitions(db, no_case_trade_id))
    buyer_id = await _user_id(db, "buyer-r2@t.com")
    notification_count = len(await _notifications(db, buyer_id))
    assert (await client.get(f"/api/v1/admin/trades/{no_case_trade_id}", headers=admin_h)).status_code == 403
    assert (
        await client.get(
            f"/api/v1/admin/trades/{no_case_trade_id}",
            headers=admin_h,
            params={"case_id": review_case.id},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{no_case_trade_id}/freeze",
            headers=admin_h,
            json={"reason": "商品审核不等于交易依据"},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{no_case_trade_id}/freeze",
            headers=admin_h,
            json={"reason": "商品审核不等于交易依据", "case_id": review_case.id},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{no_case_trade_id}/unfreeze",
            headers=admin_h,
            json={"reason": "商品审核不等于交易依据", "case_id": review_case.id},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{no_case_trade_id}/adjust",
            headers=admin_h,
            json={"to_status": "disputed", "reason": "商品审核不等于交易依据", "case_id": review_case.id},
        )
    ).status_code == 403
    no_case_trade = await _trade(db, no_case_trade_id)
    assert no_case_trade.status == "in_progress" and no_case_trade.frozen is False
    assert len(await _transitions(db, no_case_trade_id)) == transition_count
    assert len(await _notifications(db, buyer_id)) == notification_count

    # 合法上下文下 freeze/unfreeze/adjust 可执行；UnfreezeIn 接受 case_id。
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "有依据冻结", "case_id": relevant_case},
    )
    assert resp.status_code == 200, resp.text
    assert (await _trade(db, trade_id)).frozen is True
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "有依据解冻", "case_id": relevant_case},
    )
    assert resp.status_code == 200, resp.text
    assert (await _trade(db, trade_id)).frozen is False
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "disputed", "reason": "有依据调整", "case_id": relevant_case},
    )
    assert resp.status_code == 200, resp.text
    assert (await _trade(db, trade_id)).status == "disputed"

    # 指向本商品的真实违规举报（不依赖 product_id 字段/同商品审核）属于合法依据。
    product_case = await _claimed_report_case(
        client, admin_h, db, target_type="product", target_id=product_id
    )
    resp = await client.get(
        f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": product_case}
    )
    assert resp.status_code == 200, resp.text


async def test_r5_relevance_matrix_rejects_same_product_and_arbitrary_subject(client, db, setup):
    """同商品审核/任意 subject_user 不放行；真实商品举报、本交易评价举报、封禁上下文放行。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    product, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="R5关联矩阵")
    product_id = product["id"]
    buyer_id = await _user_id(db, "buyer-r2@t.com")

    # 仅 product_id 相同且带任意 subject_user 的事项不是依据。
    arbitrary_case = await _claimed_case(
        client, admin_h, db, product_id=product_id, subject_user_id=buyer_id
    )
    assert (
        await client.get(f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": arbitrary_case})
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_id}/freeze",
            headers=admin_h,
            json={"reason": "任意同商品事项", "case_id": arbitrary_case},
        )
    ).status_code == 403

    # 真实商品违规举报（report 指向本商品）可作依据，即使事项未冗余 product_id。
    product_report_case = await _claimed_report_case(
        client, admin_h, db, target_type="product", target_id=product_id
    )
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": product_report_case}
        )
    ).status_code == 200

    # 指向本笔交易评价的举报可作依据。
    seller_id = await _user_id(db, "seller-r2@t.com")
    review = TradeReview(
        trade_id=trade_id, reviewer_id=buyer_id, reviewee_id=seller_id, rating=5, content="R5评价"
    )
    db.add(review)
    await db.commit()
    review_report_case = await _claimed_report_case(
        client, admin_h, db, target_type="review", target_id=review.id
    )
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": review_report_case}
        )
    ).status_code == 200

    # 当事账户封禁事项属于必要上下文。
    ban_case = await _claimed_case(
        client, admin_h, db, subject_user_id=buyer_id, case_type="account_ban"
    )
    assert (
        await client.get(f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": ban_case})
    ).status_code == 200

    # 其他商品的举报、对用户的普通举报均不放行本交易。
    other_product, _ = await _accept_trade(client, admin_h, seller_h, buyer_h, title="R5其他商品")
    other_product_report = await _claimed_report_case(
        client, admin_h, db, target_type="product", target_id=other_product["id"]
    )
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": other_product_report}
        )
    ).status_code == 403
    user_report = await _claimed_report_case(
        client, admin_h, db, target_type="user", target_id=buyer_id
    )
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": user_report}
        )
    ).status_code == 403


async def test_r5_message_report_and_report_ban_restriction_paths(client, db, setup):
    """消息举报按精确交易分支关联；举报封禁以真实限制记录保留后续处置。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    seller2_h, other_h = setup["seller2"], setup["other"]
    buyer_id = await _user_id(db, "buyer-r2@t.com")
    seller_id = await _user_id(db, "seller-r2@t.com")
    other_id = await _user_id(db, "other-r2@t.com")

    _, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="R5消息举报交易")
    conversation = await _conversation(db, trade_id)
    resp = await client.post(
        f"/api/v1/conversations/{conversation.id}/messages",
        headers=buyer_h,
        json={"content": "交易分支内的违规消息"},
    )
    assert resp.status_code == 200, resp.text
    message_id = resp.json()["id"]

    # 真实举报 API + 真实处置 freeze：事项只有 report_id，没有 trade_id。
    resp = await client.post(
        "/api/v1/reports",
        headers=seller_h,
        json={"target_type": "message", "target_id": message_id, "reason": "交易分支消息违规"},
    )
    assert resp.status_code == 201, resp.text
    message_case = await db.scalar(
        select(DisposalCase).where(DisposalCase.report_id == resp.json()["id"])
    )
    assert message_case is not None and message_case.trade_id is None
    assert (
        await client.post(f"/api/v1/admin/cases/{message_case.id}/claim", headers=admin_h)
    ).status_code == 200
    # 真实处置先结案，保留已处置事项；reports.py 的 message 分支缺少
    # Message 导入（不在本次可改范围），故冻结改由同一真实事项在交易
    # 管理入口执行，仍覆盖 report_id-only 事项的后续合法处置。
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{message_case.id}/decision",
        headers=admin_h,
        json={"outcome": "unfounded", "reason": "先结案以覆盖已处置事项"},
    )
    assert resp.status_code == 200, resp.text
    await db.refresh(message_case)
    assert message_case.status == "disposed"
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "消息举报事项冻结", "case_id": message_case.id},
    )
    assert resp.status_code == 200, resp.text
    assert (await _trade(db, trade_id)).frozen is True

    # 原举报事项（已处置）可继续查看并解冻本交易。
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": message_case.id}
        )
    ).status_code == 200
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "消息举报事项后续解冻", "case_id": message_case.id},
    )
    assert resp.status_code == 200, resp.text
    assert (await _trade(db, trade_id)).frozen is False

    # 普通私聊消息没有 trade_id，不能推断到任何交易。
    resp = await client.post(
        "/api/v1/conversations/normal", headers=buyer_h, json={"peer_user_id": seller_id}
    )
    assert resp.status_code == 201, resp.text
    normal_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/conversations/{normal_id}/messages",
        headers=seller_h,
        json={"content": "普通私聊消息"},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "message", "target_id": resp.json()["id"], "reason": "普通私聊违规"},
    )
    assert resp.status_code == 201, resp.text
    normal_case = await db.scalar(
        select(DisposalCase).where(DisposalCase.report_id == resp.json()["id"])
    )
    assert normal_case is not None
    assert (
        await client.post(f"/api/v1/admin/cases/{normal_case.id}/claim", headers=admin_h)
    ).status_code == 200
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": normal_case.id}
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_id}/freeze",
            headers=admin_h,
            json={"reason": "普通私聊不关联交易", "case_id": normal_case.id},
        )
    ).status_code == 403
    assert (await _trade(db, trade_id)).frozen is False

    # 其他交易分支的消息举报只关联别的 trade_id。
    _, other_trade_id = await _accept_trade(
        client, admin_h, seller2_h, other_h, title="R5其他交易分支"
    )
    other_conversation = await _conversation(db, other_trade_id)
    resp = await client.post(
        f"/api/v1/conversations/{other_conversation.id}/messages",
        headers=other_h,
        json={"content": "另一交易分支的消息"},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/api/v1/reports",
        headers=seller2_h,
        json={"target_type": "message", "target_id": resp.json()["id"], "reason": "另一交易违规"},
    )
    assert resp.status_code == 201, resp.text
    other_branch_case = await db.scalar(
        select(DisposalCase).where(DisposalCase.report_id == resp.json()["id"])
    )
    assert other_branch_case is not None
    assert (
        await client.post(f"/api/v1/admin/cases/{other_branch_case.id}/claim", headers=admin_h)
    ).status_code == 200
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}",
            headers=admin_h,
            params={"case_id": other_branch_case.id},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_id}/freeze",
            headers=admin_h,
            json={"reason": "其他分支不得跨交易", "case_id": other_branch_case.id},
        )
    ).status_code == 403
    assert (await _trade(db, trade_id)).frozen is False

    # 只有普通用户举报、没有对应 ban 限制记录时仍拒绝。
    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "user", "target_id": seller_id, "reason": "普通用户举报"},
    )
    assert resp.status_code == 201, resp.text
    plain_user_case = await db.scalar(
        select(DisposalCase).where(DisposalCase.report_id == resp.json()["id"])
    )
    assert plain_user_case is not None
    assert (
        await client.post(f"/api/v1/admin/cases/{plain_user_case.id}/claim", headers=admin_h)
    ).status_code == 200
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}",
            headers=admin_h,
            params={"case_id": plain_user_case.id},
        )
    ).status_code == 403

    # 举报处置实际封禁交易一方：AccountRestriction.case_id 指向原举报事项。
    resp = await client.post(
        "/api/v1/reports",
        headers=seller_h,
        json={"target_type": "user", "target_id": buyer_id, "reason": "应封禁的用户"},
    )
    assert resp.status_code == 201, resp.text
    ban_case = await db.scalar(
        select(DisposalCase).where(DisposalCase.report_id == resp.json()["id"])
    )
    assert ban_case is not None
    ban_case_id = ban_case.id
    assert (
        await client.post(f"/api/v1/admin/cases/{ban_case_id}/claim", headers=admin_h)
    ).status_code == 200
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{ban_case_id}/decision",
        headers=admin_h,
        json={
            "outcome": "handled",
            "reason": "封禁交易一方",
            "actions": {"ban_user": True, "ban_reason": "严重违规"},
        },
    )
    assert resp.status_code == 200, resp.text
    restriction = await db.scalar(
        select(AccountRestriction).where(AccountRestriction.case_id == ban_case_id)
    )
    assert restriction is not None
    assert restriction.user_id == buyer_id
    assert restriction.type == "ban"
    assert restriction.status == "active"
    assert (await _trade(db, trade_id)).frozen is True

    # 凭真实限制记录可查看并调整；解除封禁后的 lifted 历史仍保留依据。
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": ban_case_id}
        )
    ).status_code == 200
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "disputed", "reason": "封禁事项后续调整", "case_id": ban_case_id},
    )
    assert resp.status_code == 200, resp.text
    assert (await _trade(db, trade_id)).status == "disputed"

    resp = await client.post(
        f"/api/v1/admin/users/{buyer_id}/unban",
        headers=admin_h,
        json={"lift_reason": "申诉通过"},
    )
    assert resp.status_code == 200, resp.text
    restriction = await db.scalar(
        select(AccountRestriction).where(AccountRestriction.case_id == ban_case_id)
    )
    assert restriction.status == "lifted"
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": ban_case_id}
        )
    ).status_code == 200
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "abnormal", "reason": "解除封禁后仍按原事项跟进", "case_id": ban_case_id},
    )
    assert resp.status_code == 200, resp.text
    assert (await _trade(db, trade_id)).status == "abnormal"

    # 别人（非本交易参与方）的限制记录不能用于本交易。
    resp = await client.post(
        "/api/v1/reports",
        headers=seller2_h,
        json={"target_type": "user", "target_id": other_id, "reason": "应封禁的其他用户"},
    )
    assert resp.status_code == 201, resp.text
    other_ban_case = await db.scalar(
        select(DisposalCase).where(DisposalCase.report_id == resp.json()["id"])
    )
    assert other_ban_case is not None
    other_ban_case_id = other_ban_case.id
    assert (
        await client.post(f"/api/v1/admin/cases/{other_ban_case_id}/claim", headers=admin_h)
    ).status_code == 200
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{other_ban_case_id}/decision",
        headers=admin_h,
        json={
            "outcome": "handled",
            "reason": "封禁非本交易参与方",
            "actions": {"ban_user": True, "ban_reason": "其他违规"},
        },
    )
    assert resp.status_code == 200, resp.text
    other_restriction = await db.scalar(
        select(AccountRestriction).where(AccountRestriction.case_id == other_ban_case_id)
    )
    assert other_restriction is not None and other_restriction.user_id == other_id
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_id}",
            headers=admin_h,
            params={"case_id": other_ban_case_id},
        )
    ).status_code == 403


async def test_r5_case_bound_to_other_trade_same_product_cannot_access(client, db, setup):
    """两笔交易共用商品时，绑定 A 的事项（含已处置）不得操作 B；精确事项仍可用。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    product, trade_a, _ = await _completed_trade(
        client, admin_h, seller_h, buyer_h, title="R5同商品历史交易"
    )
    product_id = product["id"]

    # 历史交易完成后恢复展示，发起第二笔同商品交易。
    row = await _product(db, product_id)
    row.status = "listed"
    row.delisted_at = None
    await db.commit()
    resp = await client.post(
        "/api/v1/trades/requests", headers=buyer_h, json={"product_id": product_id}
    )
    assert resp.status_code == 200, resp.text
    trade_b = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{trade_b}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text

    # A 的精确交易事项：trade_id=A 且 product_id 与 B 相同，已处置。
    case_a = await _claimed_case(
        client, admin_h, db, trade_id=trade_a, product_id=product_id
    )
    case_a_row = await db.get(DisposalCase, case_a)
    case_a_row.status = "disposed"
    case_a_row.disposed_at = datetime.now(UTC)
    await db.commit()

    transition_count = len(await _transitions(db, trade_b))
    notification_count = len(await _notifications(db, await _user_id(db, "buyer-r2@t.com")))
    assert (
        await client.get(f"/api/v1/admin/trades/{trade_b}", headers=admin_h, params={"case_id": case_a})
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_b}/freeze",
            headers=admin_h,
            json={"reason": "借用历史交易事项", "case_id": case_a},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_b}/adjust",
            headers=admin_h,
            json={"to_status": "disputed", "reason": "借用历史交易事项", "case_id": case_a},
        )
    ).status_code == 403
    trade_b_row = await _trade(db, trade_b)
    assert trade_b_row.status == "in_progress" and trade_b_row.frozen is False
    assert len(await _transitions(db, trade_b)) == transition_count
    assert len(await _notifications(db, await _user_id(db, "buyer-r2@t.com"))) == notification_count

    # A 的评价举报只关联 A，不能作为 B 的依据。
    review = TradeReview(
        trade_id=trade_a,
        reviewer_id=await _user_id(db, "buyer-r2@t.com"),
        reviewee_id=await _user_id(db, "seller-r2@t.com"),
        rating=4,
        content="R5历史评价",
    )
    db.add(review)
    await db.commit()
    review_case = await _claimed_report_case(
        client, admin_h, db, target_type="review", target_id=review.id
    )
    assert (
        await client.get(
            f"/api/v1/admin/trades/{trade_b}", headers=admin_h, params={"case_id": review_case}
        )
    ).status_code == 403

    # 已处置的精确交易事项仍可用于 A 的后续更正。
    assert (
        await client.get(f"/api/v1/admin/trades/{trade_a}", headers=admin_h, params={"case_id": case_a})
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_a}/adjust",
            headers=admin_h,
            json={"to_status": "terminated", "reason": "已处置事项后续更正", "case_id": case_a},
        )
    ).status_code == 200
    assert (await _trade(db, trade_a)).status == "terminated"
    # 更正旧交易不得破坏 B 的锁单。
    assert (await _trade(db, trade_b)).status == "in_progress"
    assert (await _product(db, product_id)).status == "in_transaction"

    # B 的精确交易事项即使已处置，仍可用于解冻/调整。
    case_b = await _claimed_case(client, admin_h, db, trade_id=trade_b)
    case_b_row = await db.get(DisposalCase, case_b)
    case_b_row.status = "disposed"
    case_b_row.disposed_at = datetime.now(UTC)
    await db.commit()
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_b}/freeze",
            headers=admin_h,
            json={"reason": "已处置事项冻结", "case_id": case_b},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_b}/unfreeze",
            headers=admin_h,
            json={"reason": "已处置事项解冻", "case_id": case_b},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/admin/trades/{trade_b}/adjust",
            headers=admin_h,
            json={"to_status": "disputed", "reason": "已处置事项调整", "case_id": case_b},
        )
    ).status_code == 200
    assert (await _trade(db, trade_b)).status == "disputed"


# ---------------- R13：唯一约束并发裁决 ----------------

async def test_r13_accept_race_maps_unique_conflict_to_409_and_rolls_back(client, db, setup, monkeypatch):
    """R13/D-48：预检后并发锁单提交，唯一索引裁决须 409 且不残留通知/关闭/转移。"""
    admin_h, seller_h, buyer_h, _ = (
        setup["admin"],
        setup["seller"],
        setup["buyer"],
        setup["other"],
    )
    product = await create_listed_product(client, admin_h, seller_h, title="R13接受竞态")
    resp = await client.post(
        "/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]}
    )
    trade_id = resp.json()["id"]
    seller_id = await _user_id(db, "seller-r2@t.com")
    other_id = await _user_id(db, "other-r2@t.com")
    buyer_id = await _user_id(db, "buyer-r2@t.com")
    transition_count = len(await _transitions(db, trade_id))
    notification_count = len(await _notifications(db, buyer_id))

    from app.services import trades as trade_service

    original = trade_service.ensure_no_locking_conflict
    SessionMaker = async_sessionmaker(db.bind, expire_on_commit=False, class_=AsyncSession)

    async def racing_precheck(db_, trade_, target_status):
        await original(db_, trade_, target_status)
        # 模拟另一事务在预检后、本次写入前抢先提交同商品锁单。
        async with SessionMaker() as competing:
            competing.add(
                Trade(
                    product_id=product["id"],
                    buyer_id=other_id,
                    seller_id=seller_id,
                    status="in_progress",
                )
            )
            await competing.commit()

    monkeypatch.setattr(trade_service, "ensure_no_locking_conflict", racing_precheck)
    resp = await client.post(f"/api/v1/trades/{trade_id}/accept", headers=seller_h)
    assert resp.status_code == 409, resp.text
    assert "锁单" in resp.json()["detail"]

    trade = await _trade(db, trade_id)
    assert trade.status == "pending_acceptance"
    assert (await _product(db, product["id"])).status == "listed"
    assert len(await _transitions(db, trade_id)) == transition_count
    assert len(await _notifications(db, buyer_id)) == notification_count
    # 竞争者锁单是唯一持久结果；失败接受没有留下确认、分支归档或商品变更。
    competitor = await db.scalar(
        select(Trade).where(
            Trade.product_id == product["id"], Trade.status == "in_progress", Trade.id != trade_id
        )
    )
    assert competitor is not None
    assert (await _conversation(db, trade_id)).archived is False


async def test_r13_adjust_race_maps_unique_conflict_to_409_without_side_effects(client, db, setup, monkeypatch):
    """R13/D-48：管理恢复同时被另一事务锁单，仍须 409 并回滚状态/商品/通知。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    product, old_trade_id, _ = await _completed_trade(
        client, admin_h, seller_h, buyer_h, title="R13管理恢复竞态"
    )
    case_id = await _claimed_case(client, admin_h, db, trade_id=old_trade_id)
    old_trade = await _trade(db, old_trade_id)
    finished_at = old_trade.finished_at
    transition_count = len(await _transitions(db, old_trade_id))
    buyer_id = await _user_id(db, "buyer-r2@t.com")
    notification_count = len(await _notifications(db, buyer_id))
    seller_id = await _user_id(db, "seller-r2@t.com")
    other_id = await _user_id(db, "other-r2@t.com")

    from app.services import trades as trade_service

    original = trade_service.ensure_no_locking_conflict
    SessionMaker = async_sessionmaker(db.bind, expire_on_commit=False, class_=AsyncSession)

    async def racing_precheck(db_, trade_, target_status):
        await original(db_, trade_, target_status)
        async with SessionMaker() as competing:
            competing.add(
                Trade(
                    product_id=product["id"],
                    buyer_id=other_id,
                    seller_id=seller_id,
                    status="in_progress",
                )
            )
            await competing.commit()

    monkeypatch.setattr(trade_service, "ensure_no_locking_conflict", racing_precheck)
    resp = await client.post(
        f"/api/v1/admin/trades/{old_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "in_progress", "reason": "误标恢复", "case_id": case_id},
    )
    assert resp.status_code == 409, resp.text

    old_trade = await _trade(db, old_trade_id)
    assert old_trade.status == "completed"
    assert old_trade.finished_at.isoformat() == finished_at.isoformat()
    assert (await _product(db, product["id"])).status == "delisted"
    assert len(await _transitions(db, old_trade_id)) == transition_count
    assert len(await _notifications(db, buyer_id)) == notification_count


# ---------------- R14：保护他单锁单与商品资格 ----------------

async def test_r14_terminating_old_completed_trade_does_not_delist_other_lock(client, db, setup):
    """R14：completed A -> B 锁单 -> 管理调整 A terminated，不得下架 B 的商品或归档 B 分支。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    product, old_trade_id, _ = await _completed_trade(
        client, admin_h, seller_h, buyer_h, title="R14旧完成交易"
    )
    resp = await client.post(f"/api/v1/products/{product['id']}/relist", headers=seller_h)
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    later_trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{later_trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text
    later_case = await _claimed_case(client, admin_h, db, trade_id=later_trade_id)

    # 先合法终止 B，再重新形成 B 锁单场景：直接恢复 B 到 in_progress。
    resp = await client.post(
        f"/api/v1/admin/trades/{later_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "terminated", "reason": "临时终止", "case_id": later_case},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/trades/{later_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "in_progress", "reason": "恢复锁单", "case_id": later_case},
    )
    assert resp.status_code == 200, resp.text

    later_conversation_before = (await _conversation(db, later_trade_id)).archived
    old_case = await _claimed_case(client, admin_h, db, trade_id=old_trade_id)
    resp = await client.post(
        f"/api/v1/admin/trades/{old_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "terminated", "reason": "旧交易改判终止", "case_id": old_case},
    )
    assert resp.status_code == 200, resp.text

    old_trade = await _trade(db, old_trade_id)
    later_trade = await _trade(db, later_trade_id)
    product_row = await _product(db, product["id"])
    assert old_trade.status == "terminated"
    assert later_trade.status == "in_progress" and later_trade.finished_at is None
    assert product_row.status == "in_transaction"
    # 结束旧交易只归档旧分支，不改变另一笔交易分支的归档状态（恢复不额外重开）。
    assert (await _conversation(db, later_trade_id)).archived is later_conversation_before


async def test_r14_locking_adjust_closes_other_pending_and_nonlocking_keeps_states(client, db, setup):
    """R14/BR-02：管理进入锁单自动关闭其余待接受；非锁单调整不擅自 listed 或打断他单。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    other_h = setup["other"]

    # BR-02：管理把一条待接受请求调整为锁单状态，其余请求按既有规则关闭。
    product = await create_listed_product(client, admin_h, seller_h, title="R14管理锁单")
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    first_trade_id = resp.json()["id"]
    resp = await client.post("/api/v1/trades/requests", headers=other_h, json={"product_id": product["id"]})
    second_trade_id = resp.json()["id"]
    first_case = await _claimed_case(client, admin_h, db, trade_id=first_trade_id)
    resp = await client.post(
        f"/api/v1/admin/trades/{first_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "in_progress", "reason": "有依据进入锁单", "case_id": first_case},
    )
    assert resp.status_code == 200, resp.text
    second_trade = await _trade(db, second_trade_id)
    assert second_trade.status == "closed" and second_trade.close_reason == CLOSED_BY_LOCK
    assert (await _conversation(db, second_trade_id)).archived is True
    assert (await _product(db, product["id"])).status == "in_transaction"
    other_id = await _user_id(db, "other-r2@t.com")
    assert any(
        n.type == "request_closed" and n.link_id == second_trade_id
        for n in await _notifications(db, other_id)
    )

    # 非锁单调整旧已完成交易不得把应下架商品变 listed，也不得打断当前他单锁单。
    old_product, old_trade_id, _ = await _completed_trade(
        client, admin_h, seller_h, buyer_h, title="R14应下架旧交易"
    )
    old_case = await _claimed_case(client, admin_h, db, trade_id=old_trade_id)
    resp = await client.post(
        f"/api/v1/admin/trades/{old_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "rejected", "reason": "改判拒绝", "case_id": old_case},
    )
    assert resp.status_code == 200, resp.text
    assert (await _product(db, old_product["id"])).status == "delisted"

    resp = await client.post(f"/api/v1/products/{old_product['id']}/relist", headers=seller_h)
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/api/v1/trades/requests", headers=buyer_h, json={"product_id": old_product["id"]}
    )
    later_trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{later_trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text
    later_case = await _claimed_case(client, admin_h, db, trade_id=later_trade_id)
    await client.post(
        f"/api/v1/admin/trades/{later_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "terminated", "reason": "临时终止", "case_id": later_case},
    )
    await client.post(
        f"/api/v1/admin/trades/{later_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "in_progress", "reason": "恢复锁单", "case_id": later_case},
    )

    resp = await client.post(
        f"/api/v1/admin/trades/{old_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "pending_acceptance", "reason": "非锁单调整", "case_id": old_case},
    )
    assert resp.status_code == 200, resp.text
    assert (await _trade(db, later_trade_id)).status == "in_progress"
    assert (await _product(db, old_product["id"])).status == "in_transaction"


# ---------------- D52 / DT-03 ----------------

async def test_d52_ban_seller_revokes_in_transaction_product_display_and_keeps_history(client, db, setup):
    """D52/DT-03：封禁卖方时 in_transaction 商品也撤销公开；保留生命周期、锁单与私人历史。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    other_h = setup["other"]
    product, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="D52交易中封禁")
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=other_h)
    assert resp.status_code == 200, resp.text  # 交易中详情按既有规则可公开

    seller_id = await _user_id(db, "seller-r2@t.com")
    resp = await client.post(
        f"/api/v1/admin/users/{seller_id}/ban", headers=admin_h, json={"reason": "交易违规"}
    )
    assert resp.status_code == 200, resp.text
    product_row = await _product(db, product["id"])
    assert product_row.display_restricted is True
    assert product_row.status == "in_transaction"  # 生命周期不被展示限制改写
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress" and trade.frozen is True  # 锁单与交易保留
    assert (await client.get(f"/api/v1/products/{product['id']}", headers=other_h)).status_code == 404
    assert (await client.get(f"/api/v1/trades/{trade_id}", headers=buyer_h)).status_code == 200
    assert (await client.get(f"/api/v1/trades/{trade_id}", headers=seller_h)).status_code == 200

    resp = await client.post(
        f"/api/v1/admin/users/{seller_id}/unban", headers=admin_h, json={"lift_reason": "复核解除"}
    )
    assert resp.status_code == 200, resp.text
    product_row = await _product(db, product["id"])
    assert product_row.display_restricted is False
    assert product_row.status == "in_transaction"  # 恢复展示资格不等于改动生命周期
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress" and trade.frozen is False
    assert (await client.get(f"/api/v1/products/{product['id']}", headers=other_h)).status_code == 200


async def test_d52_report_display_revocation_closes_pending_with_unified_reason(client, db, setup):
    """BR-02/D52：仅撤销公开访问时，待接受请求原因统一为“商品公开访问已撤销”。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    product = await create_listed_product(client, admin_h, seller_h, title="D52举报撤展示")
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    trade_id = resp.json()["id"]

    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "违规展示"},
    )
    assert resp.status_code == 201, resp.text
    report_id = resp.json()["id"]
    report_list = (await client.get("/api/v1/admin/reports", headers=admin_h)).json()
    case_id = next(item["case_id"] for item in report_list if item["id"] == report_id)
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin_h)
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{case_id}/decision",
        headers=admin_h,
        json={
            "outcome": "handled",
            "reason": "认定展示违规",
            "actions": {"remove_content": False, "restrict_display": True, "freeze_trade": False, "ban_user": False},
        },
    )
    assert resp.status_code == 200, resp.text

    trade = await _trade(db, trade_id)
    assert trade.status == "closed"
    assert trade.close_reason == "商品公开访问已撤销"
    assert (await _conversation(db, trade_id)).archived is True
    product_row = await _product(db, product["id"])
    assert product_row.display_restricted is True
    assert product_row.status == "listed"  # 仅撤销公开访问，不改生命周期

"""D-48/D-49/D-51/D-52 回归测试：真实 API + SQLite 持久状态断言。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    CompletionConfirmation,
    Conversation,
    DisposalCase,
    Notification,
    Product,
    Trade,
    TradeAgreement,
    TradeTransition,
    User,
)
from app.services.trade_timeout import scan_once
from tests.conftest import admin_headers, create_listed_product, login, make_admin, user_headers

pytestmark = pytest.mark.asyncio

AGREEMENT = {
    "delivery_time": "周六上午十点",
    "delivery_location": "东门快递站旁",
    "delivery_method": "当面交付",
    "amount_cents": 1000,
    "payment_method": "微信转账",
    "payment_timing": "当面付清",
}


@pytest.fixture
async def setup(client, db):
    await make_admin(db)
    return {
        "admin": await admin_headers(client),
        "seller": await user_headers(client, "seller-docs@t.com", "卖方"),
        "buyer": await user_headers(client, "buyer-docs@t.com", "买方"),
        "other": await user_headers(client, "other-docs@t.com", "其他买方"),
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


async def _claimed_case(
    client,
    admin_h,
    db,
    *,
    trade_id: int | None = None,
    product_id: int | None = None,
    subject_user_id: int | None = None,
    case_type: str = "trade_dispute",
) -> int:
    """R5 合法测试夹具：建立与该交易/商品/账户直接相关的事项并由当前管理员认领。"""
    case = DisposalCase(
        case_type=case_type,
        title=f"回归事项-{trade_id or product_id or subject_user_id}",
        trade_id=trade_id,
        product_id=product_id,
        subject_user_id=subject_user_id,
    )
    db.add(case)
    await db.commit()
    resp = await client.post(f"/api/v1/admin/cases/{case.id}/claim", headers=admin_h)
    assert resp.status_code == 200, resp.text
    return case.id


async def _notifications(db, user_id: int, link_id: int | None = None) -> list[Notification]:
    db.expunge_all()
    query = select(Notification).where(Notification.user_id == user_id)
    if link_id is not None:
        query = query.where(Notification.link_id == link_id)
    return list((await db.execute(query.order_by(Notification.id))).scalars())


async def _accept_trade(client, admin_h, seller_h, buyer_h, *, title: str) -> tuple[dict, int]:
    product = await create_listed_product(client, admin_h, seller_h, title=title)
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    assert resp.status_code == 200, resp.text
    trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text
    return product, trade_id


async def _confirm_agreement(client, seller_h, buyer_h, trade_id: int, *, amount_cents: int = 1000) -> int:
    resp = await client.post(
        f"/api/v1/trades/{trade_id}/agreements",
        headers=buyer_h,
        json={**AGREEMENT, "amount_cents": amount_cents},
    )
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


# ---------------- D-49 ----------------


async def test_d49_change_clears_confirmations_and_wait_only_when_agreed(client, db, setup):
    """变更提案/拒绝保留旧轮；另一方同意生效才清双方当前确认并结束旧等待。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    _, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="D49变更商品")
    old_agreement_id = await _confirm_agreement(client, seller_h, buyer_h, trade_id)

    resp = await client.post(f"/api/v1/trades/{trade_id}/confirmations", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=2)
    await db.commit()

    # 提案变更本身不清旧确认/旧计时。
    resp = await client.post(
        f"/api/v1/trades/{trade_id}/agreements", headers=seller_h, json={**AGREEMENT, "amount_cents": 1200}
    )
    assert resp.status_code == 200, resp.text
    first_change_id = resp.json()["id"]
    trade = await _trade(db, trade_id)
    assert trade.current_agreement_id == old_agreement_id
    assert trade.confirm_wait_started_at is not None
    current = list(
        (
            await db.execute(
                select(CompletionConfirmation).where(
                    CompletionConfirmation.trade_id == trade_id, CompletionConfirmation.is_current.is_(True)
                )
            )
        ).scalars()
    )
    assert len(current) == 1 and current[0].confirmer_id != await _user_id(db, "seller-docs@t.com")

    # 拒绝变更仍保留旧确认与旧计时。
    resp = await client.post(
        f"/api/v1/trades/{trade_id}/agreements/{first_change_id}/reject", headers=buyer_h
    )
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    assert trade.current_agreement_id == old_agreement_id
    assert trade.confirm_wait_started_at is not None
    assert trade.confirm_wait_paused_at is None
    assert len(
        list(
            (
                await db.execute(
                    select(CompletionConfirmation).where(
                        CompletionConfirmation.trade_id == trade_id,
                        CompletionConfirmation.is_current.is_(True),
                    )
                )
            ).scalars()
        )
    ) == 1

    # 再次提案并由另一方同意：清双方当前确认、结束旧计时，历史和旧约定保留。
    resp = await client.post(
        f"/api/v1/trades/{trade_id}/agreements", headers=seller_h, json={**AGREEMENT, "amount_cents": 1500}
    )
    assert resp.status_code == 200, resp.text
    new_agreement_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/trades/{trade_id}/agreements/{new_agreement_id}/confirm", headers=buyer_h
    )
    assert resp.status_code == 200, resp.text

    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress"
    assert trade.current_agreement_id == new_agreement_id
    assert trade.confirm_wait_started_at is None
    assert trade.confirm_wait_paused_at is None
    assert trade.confirm_wait_remaining_seconds is None
    confirmations = list(
        (
            await db.execute(
                select(CompletionConfirmation)
                .where(CompletionConfirmation.trade_id == trade_id)
                .order_by(CompletionConfirmation.id)
            )
        ).scalars()
    )
    assert len(confirmations) == 1  # 历史保留
    assert all(not c.is_current for c in confirmations)
    old_agreement = await db.get(TradeAgreement, old_agreement_id)
    assert old_agreement is not None and old_agreement.status == "superseded"

    detail = (await client.get(f"/api/v1/trades/{trade_id}", headers=buyer_h)).json()
    assert detail["my_confirmed"] is False and detail["other_party_confirmed"] is False
    assert detail["confirm_wait_started_at"] is None
    assert detail["confirm_wait_paused_at"] is None
    assert detail["confirm_wait_remaining_seconds"] is None

    # 变更生效仍在“已有约定”阶段，不恢复首次约定前买方直接取消权。
    resp = await client.post(f"/api/v1/trades/{trade_id}/cancel", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    assert "等待对方同意" in resp.json()["detail"]
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress"
    assert trade.cancel_requested_by_id == await _user_id(db, "buyer-docs@t.com")


# ---------------- D-48 ----------------


@pytest.mark.parametrize("target_status", ["in_progress", "disputed", "abnormal"])
async def test_d48_restore_rejects_any_locking_conflict_without_mutation(client, db, setup, target_status):
    """恢复已完成旧交易到任一锁单状态前，另一笔锁单存在则 409 且所有对象不变。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    product, old_trade_id, old_agreement_id = await _completed_trade(
        client, admin_h, seller_h, buyer_h, title=f"D48冲突-{target_status}"
    )
    old_trade = await _trade(db, old_trade_id)
    old_finished_at = old_trade.finished_at
    old_transition_count = len(
        list((await db.execute(select(TradeTransition).where(TradeTransition.trade_id == old_trade_id))).scalars())
    )
    old_notification_count = len(await _notifications(db, await _user_id(db, "buyer-docs@t.com"), old_trade_id))

    # 商品重新上架后产生后续交易 B 并锁单。
    resp = await client.post(f"/api/v1/products/{product['id']}/relist", headers=seller_h)
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    assert resp.status_code == 200, resp.text
    later_trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{later_trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text
    later_trade = await _trade(db, later_trade_id)
    later_transition_count = len(
        list((await db.execute(select(TradeTransition).where(TradeTransition.trade_id == later_trade_id))).scalars())
    )

    case_id = await _claimed_case(client, admin_h, db, trade_id=old_trade_id)
    resp = await client.post(
        f"/api/v1/admin/trades/{old_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": target_status, "reason": "恢复误标完成交易", "case_id": case_id},
    )
    assert resp.status_code == 409, resp.text

    old_trade = await _trade(db, old_trade_id)
    later_trade = await _trade(db, later_trade_id)
    product_row = await _product(db, product["id"])
    conversation = await _conversation(db, old_trade_id)
    confirmations = list(
        (
            await db.execute(
                select(CompletionConfirmation).where(
                    CompletionConfirmation.trade_id == old_trade_id,
                    CompletionConfirmation.is_current.is_(True),
                )
            )
        ).scalars()
    )
    assert old_trade.status == "completed"
    assert old_trade.finished_at.isoformat() == old_finished_at.isoformat()
    assert old_trade.current_agreement_id == old_agreement_id
    assert len(confirmations) == 2  # 当前确认未被清空
    assert later_trade.status == "in_progress" and later_trade.finished_at is None
    assert product_row.status == "in_transaction"
    assert conversation.archived is True
    assert len(
        list((await db.execute(select(TradeTransition).where(TradeTransition.trade_id == old_trade_id))).scalars())
    ) == old_transition_count
    assert len(
        list((await db.execute(select(TradeTransition).where(TradeTransition.trade_id == later_trade_id))).scalars())
    ) == later_transition_count
    assert len(await _notifications(db, await _user_id(db, "buyer-docs@t.com"), old_trade_id)) == old_notification_count


async def test_d48_restore_completed_trade_updates_lock_finished_at_and_notifies(client, db, setup):
    """无冲突时恢复已完成旧交易：清当前确认、结束计时、保留约定/历史/归档、商品重新锁单。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    product, old_trade_id, old_agreement_id = await _completed_trade(
        client, admin_h, seller_h, buyer_h, title="D48恢复商品"
    )

    resp = await client.post(f"/api/v1/products/{product['id']}/relist", headers=seller_h)
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    later_trade_id = resp.json()["id"]
    await client.post(f"/api/v1/trades/{later_trade_id}/accept", headers=seller_h)
    # 先按 B 的适用规则终止 B，再重新校验 A 恢复资格。
    later_case_id = await _claimed_case(client, admin_h, db, trade_id=later_trade_id)
    resp = await client.post(
        f"/api/v1/admin/trades/{later_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "terminated", "reason": "先处理后续交易", "case_id": later_case_id},
    )
    assert resp.status_code == 200, resp.text

    old_case_id = await _claimed_case(client, admin_h, db, trade_id=old_trade_id)
    resp = await client.post(
        f"/api/v1/admin/trades/{old_trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "in_progress", "reason": "误标完成，恢复进行中", "case_id": old_case_id},
    )
    assert resp.status_code == 200, resp.text

    old_trade = await _trade(db, old_trade_id)
    later_trade = await _trade(db, later_trade_id)
    product_row = await _product(db, product["id"])
    conversation = await _conversation(db, old_trade_id)
    confirmations = list(
        (
            await db.execute(
                select(CompletionConfirmation)
                .where(CompletionConfirmation.trade_id == old_trade_id)
                .order_by(CompletionConfirmation.id)
            )
        ).scalars()
    )
    assert old_trade.status == "in_progress"
    assert old_trade.finished_at is None
    assert old_trade.current_agreement_id == old_agreement_id
    assert old_trade.confirm_wait_started_at is None
    assert old_trade.confirm_wait_paused_at is None
    assert old_trade.confirm_wait_remaining_seconds is None
    assert len(confirmations) == 2  # 历史保留
    assert all(not c.is_current for c in confirmations)
    assert product_row.status == "in_transaction"
    assert conversation.archived is True  # 不额外重开归档分支
    assert later_trade.status == "terminated"  # 不自动处理其他交易
    transition = await db.scalar(
        select(TradeTransition)
        .where(TradeTransition.trade_id == old_trade_id)
        .order_by(TradeTransition.id.desc())
        .limit(1)
    )
    assert transition is not None
    assert transition.trigger == "admin_restore"
    assert transition.from_status == "completed" and transition.to_status == "in_progress"
    for email in ("buyer-docs@t.com", "seller-docs@t.com"):
        notes = await _notifications(db, await _user_id(db, email), old_trade_id)
        assert any(n.type == "trade_adjusted" and old_trade_id == n.link_id for n in notes)

    # 恢复本身不启动计时；重新单方确认后才从该次确认起完整计时。
    resp = await client.post(f"/api/v1/trades/{old_trade_id}/confirmations", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    old_trade = await _trade(db, old_trade_id)
    assert old_trade.confirm_wait_started_at is not None
    assert old_trade.confirm_wait_paused_at is None
    detail = (await client.get(f"/api/v1/trades/{old_trade_id}", headers=buyer_h)).json()
    assert detail["confirm_wait_remaining_seconds"] is not None
    assert detail["confirm_wait_remaining_seconds"] > 6 * 24 * 60 * 60


# ---------------- D-51 ----------------


async def test_d51_freeze_pauses_and_unfreeze_resumes_remaining_without_wall_clock(client, db, setup):
    """冻结保留当前确认并暂停；重复冻结幂等；冻结期间扫描不累计；解冻续算剩余。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    _, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="D51计时商品")
    await _confirm_agreement(client, seller_h, buyer_h, trade_id)
    resp = await client.post(f"/api/v1/trades/{trade_id}/confirmations", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=2)
    await db.commit()
    case_id = await _claimed_case(client, admin_h, db, trade_id=trade_id)

    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "违规处置核查", "case_id": case_id},
    )
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    assert trade.frozen is True
    assert trade.confirm_wait_paused_at is not None
    assert trade.confirm_wait_remaining_seconds is not None
    assert 4.9 * 86400 <= trade.confirm_wait_remaining_seconds <= 5.0 * 86400
    assert len(
        list(
            (
                await db.execute(
                    select(CompletionConfirmation).where(
                        CompletionConfirmation.trade_id == trade_id,
                        CompletionConfirmation.is_current.is_(True),
                    )
                )
            ).scalars()
        )
    ) == 1
    paused_at = trade.confirm_wait_paused_at
    frozen_at = trade.frozen_at
    remaining = trade.confirm_wait_remaining_seconds
    detail = (await client.get(f"/api/v1/trades/{trade_id}", headers=seller_h)).json()
    assert detail["confirm_wait_paused_at"] is not None
    assert detail["confirm_wait_remaining_seconds"] == remaining
    admin_detail = (
        await client.get(f"/api/v1/admin/trades/{trade_id}", headers=admin_h, params={"case_id": case_id})
    ).json()
    assert admin_detail["confirm_wait_paused_at"] == detail["confirm_wait_paused_at"]
    assert admin_detail["confirm_wait_remaining_seconds"] == remaining
    freeze_transition = await db.scalar(
        select(TradeTransition)
        .where(TradeTransition.trade_id == trade_id, TradeTransition.trigger == "trade_frozen")
        .order_by(TradeTransition.id.desc())
        .limit(1)
    )
    assert freeze_transition is not None and "暂停" in (freeze_transition.reason or "")
    freeze_notes = await _notifications(db, await _user_id(db, "buyer-docs@t.com"), trade_id)
    assert any(n.type == "trade_frozen" and "暂停" in n.content for n in freeze_notes)

    # 重复冻结不重置冻结起点/暂停起点/剩余时间。
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "重复冻结", "case_id": case_id},
    )
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    assert trade.frozen_at.isoformat() == frozen_at.isoformat()
    assert trade.confirm_wait_paused_at.isoformat() == paused_at.isoformat()
    assert trade.confirm_wait_remaining_seconds == remaining

    # 自然墙钟已超过 7 天也不能在冻结中累计触发。
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=8)
    await db.commit()
    assert await scan_once(db) == 0
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress" and trade.frozen is True

    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "核查完成，解除冻结", "case_id": case_id},
    )
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    assert trade.frozen is False
    assert trade.confirm_wait_paused_at is None
    assert trade.confirm_wait_remaining_seconds is None
    assert trade.confirm_wait_started_at is not None
    remaining_after = (datetime.now(UTC) - trade.confirm_wait_started_at.replace(tzinfo=UTC)).total_seconds()
    assert 2 * 86400 - 120 <= remaining_after <= 2 * 86400 + 120  # 已等待约 2 天，未重置
    unfreeze_transition = await db.scalar(
        select(TradeTransition)
        .where(TradeTransition.trade_id == trade_id, TradeTransition.trigger == "trade_unfrozen")
        .order_by(TradeTransition.id.desc())
        .limit(1)
    )
    assert unfreeze_transition is not None and "续算" in (unfreeze_transition.reason or "")
    assert len(
        list(
            (
                await db.execute(
                    select(CompletionConfirmation).where(
                        CompletionConfirmation.trade_id == trade_id,
                        CompletionConfirmation.is_current.is_(True),
                    )
                )
            ).scalars()
        )
    ) == 1
    assert await scan_once(db) == 0

    # 解冻后已等待约 2 天，再走完剩余约 5 天（累计 7 天）才转异常。
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=7, seconds=5)
    await db.commit()
    assert await scan_once(db) == 1
    trade = await _trade(db, trade_id)
    assert trade.status == "abnormal" and trade.frozen is True


async def test_d51_cleared_confirmation_round_does_not_inherit_old_pause(client, db, setup):
    """管理恢复清空当前确认后，旧轮暂停无效；仅解冻不续算，也不会误触发超时。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    _, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="D51旧轮商品")
    await _confirm_agreement(client, seller_h, buyer_h, trade_id)
    await client.post(f"/api/v1/trades/{trade_id}/confirmations", headers=buyer_h, json={})
    trade = await _trade(db, trade_id)
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=2)
    await db.commit()
    case_id = await _claimed_case(client, admin_h, db, trade_id=trade_id)
    await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "冻结待查", "case_id": case_id},
    )

    # 管理恢复进行中：清当前确认与旧计时，且不自动解冻。
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "abnormal", "reason": "先转异常核查", "case_id": case_id},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/adjust",
        headers=admin_h,
        json={"to_status": "in_progress", "reason": "恢复进行中", "case_id": case_id},
    )
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress" and trade.frozen is True
    assert trade.confirm_wait_started_at is None
    assert trade.confirm_wait_paused_at is None
    assert trade.confirm_wait_remaining_seconds is None
    current = list(
        (
            await db.execute(
                select(CompletionConfirmation).where(
                    CompletionConfirmation.trade_id == trade_id,
                    CompletionConfirmation.is_current.is_(True),
                )
            )
        ).scalars()
    )
    assert current == []

    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "解除冻结", "case_id": case_id},
    )
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    assert trade.frozen is False
    assert trade.confirm_wait_started_at is None
    assert trade.confirm_wait_paused_at is None
    assert trade.confirm_wait_remaining_seconds is None

    # 即使旧起点被留成 8 天前，没有当前确认也不能触发异常（旧轮无效）。
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=8)
    await db.commit()
    assert await scan_once(db) == 0
    trade = await _trade(db, trade_id)
    assert trade.status == "in_progress"


async def test_d51_report_disposal_freezes_and_pauses_wait(client, db, setup):
    """举报处置的冻结入口同样暂停已有单方确认的等待计时（D-51）。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    product, trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="D51举报冻结商品")
    await _confirm_agreement(client, seller_h, buyer_h, trade_id)
    await client.post(f"/api/v1/trades/{trade_id}/confirmations", headers=buyer_h, json={})
    trade = await _trade(db, trade_id)
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=2)
    await db.commit()

    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "交易相关内容违规"},
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
            "reason": "认定交易内容违规",
            "actions": {"freeze_trade": True},
        },
    )
    assert resp.status_code == 200, resp.text
    trade = await _trade(db, trade_id)
    assert trade.frozen is True
    assert trade.status == "in_progress"
    assert trade.confirm_wait_paused_at is not None
    assert trade.confirm_wait_remaining_seconds is not None
    assert len(
        list(
            (
                await db.execute(
                    select(CompletionConfirmation).where(
                        CompletionConfirmation.trade_id == trade_id,
                        CompletionConfirmation.is_current.is_(True),
                    )
                )
            ).scalars()
        )
    ) == 1


# ---------------- D-52 ----------------


async def test_d52_ban_buyer_closes_pending_requests_and_freezes_accepted_trade(client, db, setup):
    """封禁买方：作为买方的待接受请求关闭并通知双方；已接受交易冻结不记失败。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    # 已接受交易（已有单方确认）。
    _, accepted_trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="D52已接受交易")
    await _confirm_agreement(client, seller_h, buyer_h, accepted_trade_id)
    await client.post(f"/api/v1/trades/{accepted_trade_id}/confirmations", headers=buyer_h, json={})
    trade = await _trade(db, accepted_trade_id)
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=2)
    await db.commit()

    # 同一买方另有一笔待接受请求。
    pending_product = await create_listed_product(client, admin_h, seller_h, title="D52待接受商品")
    resp = await client.post(
        "/api/v1/trades/requests", headers=buyer_h, json={"product_id": pending_product["id"]}
    )
    assert resp.status_code == 200, resp.text
    pending_trade_id = resp.json()["id"]
    buyer_id = await _user_id(db, "buyer-docs@t.com")
    seller_id = await _user_id(db, "seller-docs@t.com")

    resp = await client.post(
        f"/api/v1/admin/users/{buyer_id}/ban", headers=admin_h, json={"reason": "多次违规"}
    )
    assert resp.status_code == 200, resp.text

    pending_trade = await _trade(db, pending_trade_id)
    assert pending_trade.status == "closed"
    assert pending_trade.close_reason == "相关账户被封禁"
    conversation = await _conversation(db, pending_trade_id)
    assert conversation.archived is True
    transition = await db.scalar(
        select(TradeTransition)
        .where(TradeTransition.trade_id == pending_trade_id)
        .order_by(TradeTransition.id.desc())
        .limit(1)
    )
    assert transition is not None
    assert transition.trigger == "account_banned" and transition.reason == "相关账户被封禁"
    for user_id in (buyer_id, seller_id):
        notes = await _notifications(db, user_id, pending_trade_id)
        assert any(
            n.type == "request_closed" and "相关账户被封禁" in n.content for n in notes
        )

    accepted_trade = await _trade(db, accepted_trade_id)
    assert accepted_trade.status == "in_progress"  # 已接受交易不按待接受请求关闭/不记失败
    assert accepted_trade.frozen is True
    assert accepted_trade.confirm_wait_paused_at is not None
    assert len(
        list(
            (
                await db.execute(
                    select(CompletionConfirmation).where(
                        CompletionConfirmation.trade_id == accepted_trade_id,
                        CompletionConfirmation.is_current.is_(True),
                    )
                )
            ).scalars()
        )
    ) == 1

    # 解除封禁不重开旧请求；已接受交易按剩余时间续算。
    resp = await client.post(
        f"/api/v1/admin/users/{buyer_id}/unban", headers=admin_h, json={"lift_reason": "复核解除"}
    )
    assert resp.status_code == 200, resp.text
    pending_trade = await _trade(db, pending_trade_id)
    assert pending_trade.status == "closed" and pending_trade.close_reason == "相关账户被封禁"
    accepted_trade = await _trade(db, accepted_trade_id)
    assert accepted_trade.status == "in_progress"
    assert accepted_trade.frozen is False
    assert accepted_trade.confirm_wait_paused_at is None
    assert accepted_trade.confirm_wait_started_at is not None
    assert len(
        list(
            (
                await db.execute(
                    select(CompletionConfirmation).where(
                        CompletionConfirmation.trade_id == accepted_trade_id,
                        CompletionConfirmation.is_current.is_(True),
                    )
                )
            ).scalars()
        )
    ) == 1


async def test_d52_ban_seller_closes_pending_before_product_restriction(client, db, setup):
    """封禁卖方：其作为卖方的待接受请求按封禁原因关闭，之后再限制商品展示。"""
    admin_h, seller_h, buyer_h = setup["admin"], setup["seller"], setup["buyer"]
    _, accepted_trade_id = await _accept_trade(client, admin_h, seller_h, buyer_h, title="D52卖方已接受")
    pending_product = await create_listed_product(client, admin_h, seller_h, title="D52卖方待接受")
    resp = await client.post(
        "/api/v1/trades/requests", headers=buyer_h, json={"product_id": pending_product["id"]}
    )
    assert resp.status_code == 200, resp.text
    pending_trade_id = resp.json()["id"]
    seller_id = await _user_id(db, "seller-docs@t.com")
    buyer_id = await _user_id(db, "buyer-docs@t.com")

    resp = await client.post(
        f"/api/v1/admin/users/{seller_id}/ban", headers=admin_h, json={"reason": "发布违规商品"}
    )
    assert resp.status_code == 200, resp.text
    pending_trade = await _trade(db, pending_trade_id)
    assert pending_trade.status == "closed"
    assert pending_trade.close_reason == "相关账户被封禁"  # 未被商品展示限制原因覆盖
    product_row = await _product(db, pending_product["id"])
    assert product_row.display_restricted is True
    accepted_trade = await _trade(db, accepted_trade_id)
    assert accepted_trade.status == "in_progress" and accepted_trade.frozen is True
    for user_id in (buyer_id, seller_id):
        notes = await _notifications(db, user_id, pending_trade_id)
        assert any(n.type == "request_closed" and "相关账户被封禁" in n.content for n in notes)

    resp = await client.post(
        f"/api/v1/admin/users/{seller_id}/unban", headers=admin_h, json={"lift_reason": "复核解除"}
    )
    assert resp.status_code == 200, resp.text
    pending_trade = await _trade(db, pending_trade_id)
    assert pending_trade.status == "closed"
    product_row = await _product(db, pending_product["id"])
    assert product_row.display_restricted is False
    accepted_trade = await _trade(db, accepted_trade_id)
    assert accepted_trade.frozen is False

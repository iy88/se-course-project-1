"""治理审计回归：举报终态/目标有效性、匿名公开结果、异常/争议双方沟通资格。"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from tests.conftest import (
    admin_headers,
    create_listed_product,
    make_admin,
    publish_product,
    user_headers,
)

pytestmark = pytest.mark.asyncio


async def _me(client, headers: dict) -> dict:
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
async def world(client, db):
    await make_admin(db)
    admin_h = await admin_headers(client)
    seller_h = await user_headers(client, "seller-r@test.edu", "卖方")
    buyer_h = await user_headers(client, "buyer-r@test.edu", "买方")
    third_h = await user_headers(client, "third-r@test.edu", "第三方")
    product = await create_listed_product(client, admin_h, seller_h, title="治理基础商品")
    trade = (
        await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    ).json()
    accept = await client.post(f"/api/v1/trades/{trade['id']}/accept", headers=seller_h)
    assert accept.status_code == 200, accept.text
    return {
        "admin_h": admin_h,
        "seller_h": seller_h,
        "buyer_h": buyer_h,
        "third_h": third_h,
        "seller": await _me(client, seller_h),
        "buyer": await _me(client, buyer_h),
        "third": await _me(client, third_h),
        "product": product,
        "trade_id": trade["id"],
    }


async def _create_case(db, **kwargs):
    from app.models import DisposalCase

    case = DisposalCase(**kwargs)
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


async def _claim(client, admin_h: dict, case_id: int) -> None:
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin_h)
    assert resp.status_code == 200, resp.text


async def _case_id_for_report(db, report_id: int) -> int:
    from app.models import DisposalCase

    case_id = await db.scalar(
        select(DisposalCase.id).where(DisposalCase.report_id == report_id).order_by(DisposalCase.id.desc())
    )
    assert case_id is not None
    return case_id


async def _notification_user_ids(db, case_id: int, type_: str) -> list[int]:
    from app.models import Notification

    rows = (
        await db.execute(
            select(Notification.user_id)
            .where(
                Notification.link_type == "case",
                Notification.link_id == case_id,
                Notification.type == type_,
            )
            .order_by(Notification.id)
        )
    ).scalars().all()
    return list(rows)


async def _counts(db) -> tuple[int, int]:
    from app.models import DisposalCase, Report

    reports = await db.scalar(select(func.count()).select_from(Report))
    cases = await db.scalar(select(func.count()).select_from(DisposalCase))
    return reports, cases


async def _side_effect_counts(db) -> dict[str, int]:
    """输入校验失败时不得新增举报、事项、补充、沟通消息或通知。"""
    from app.models import DisposalCase, DisposalMessage, Notification, Report, ReportSupplement

    return {
        "reports": await db.scalar(select(func.count()).select_from(Report)),
        "cases": await db.scalar(select(func.count()).select_from(DisposalCase)),
        "supplements": await db.scalar(select(func.count()).select_from(ReportSupplement)),
        "messages": await db.scalar(select(func.count()).select_from(DisposalMessage)),
        "notifications": await db.scalar(select(func.count()).select_from(Notification)),
    }


@pytest.mark.parametrize("case_type", ["abnormal_trade", "trade_dispute"])
async def test_abnormal_trade_both_parties_statement_and_appeal(client, db, world, case_type):
    """异常交易/交易争议旧事项 subject=None：双方均可问询后说明、处置后申辩（BR-26/33）。"""
    admin_h = world["admin_h"]
    seller_h, buyer_h, third_h = world["seller_h"], world["buyer_h"], world["third_h"]
    seller_id, buyer_id = world["seller"]["id"], world["buyer"]["id"]
    case = await _create_case(
        db,
        case_type=case_type,
        title=f"{case_type} 双方沟通",
        trade_id=world["trade_id"],
        subject_user_id=None,
    )
    await _claim(client, admin_h, case.id)

    # 问询前：有资格但不可说明；第三方不可访问。
    detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=buyer_h)).json()
    assert detail["can_submit_statement"] is False
    assert detail["can_submit_appeal"] is False
    resp = await client.post(
        f"/api/v1/me/cases/{case.id}/statement", headers=buyer_h, json={"content": "提前说明"}
    )
    assert resp.status_code == 409
    resp = await client.get(f"/api/v1/me/cases/{case.id}", headers=third_h)
    assert resp.status_code == 403

    # 管理员问询：买卖双方均收到通知，且各一条。
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/inquiry", headers=admin_h, json={"content": "请双方说明交付情况"}
    )
    assert resp.status_code == 200, resp.text
    inquiry_recipients = await _notification_user_ids(db, case.id, "inquiry")
    assert sorted(inquiry_recipients) == sorted([buyer_id, seller_id])

    for headers in (buyer_h, seller_h):
        detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=headers)).json()
        assert detail["status"] == "processing"
        assert detail["has_inquiry"] is True
        assert detail["can_submit_statement"] is True
        assert detail["can_submit_appeal"] is False
        resp = await client.post(
            f"/api/v1/me/cases/{case.id}/statement", headers=headers, json={"content": "情况说明"}
        )
        assert resp.status_code == 200, resp.text

    # 消息 mine 仅本人消息为真，管理员消息不冒充“我”。
    detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=buyer_h)).json()
    admin_messages = [m for m in detail["messages"] if m["role"] == "admin"]
    assert admin_messages and all(m["mine"] is False and m["sender_id"] is None for m in admin_messages)
    own_messages = [m for m in detail["messages"] if m["mine"]]
    assert own_messages and {m["sender_id"] for m in own_messages} == {buyer_id}
    assert all(m["sender_id"] is None for m in detail["messages"] if not m["mine"])

    # 管理员回复：双方各一条，不重复。
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/messages", headers=admin_h, json={"content": "已收到双方说明"}
    )
    assert resp.status_code == 200, resp.text
    reply_recipients = await _notification_user_ids(db, case.id, "appeal_result")
    assert sorted(reply_recipients) == sorted([buyer_id, seller_id])

    # 另一管理员不能读、问询或处置该事项。
    await make_admin(db, email="admin2-r@test.edu")
    admin2_h = await admin_headers(client, email="admin2-r@test.edu")
    assert (await client.get(f"/api/v1/admin/cases/{case.id}", headers=admin2_h)).status_code == 403
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/inquiry", headers=admin2_h, json={"content": "越权问询"}
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/dispose", headers=admin2_h, json={"conclusion": "越权处置"}
    )
    assert resp.status_code == 403

    # 处置后不可重新问询；双方可申辩，说明入口关闭。
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/dispose",
        headers=admin_h,
        json={"conclusion": "异常交易处理完毕", "reason": "双方均已说明"},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/inquiry", headers=admin_h, json={"content": "再次问询"}
    )
    assert resp.status_code == 409

    for headers in (buyer_h, seller_h):
        detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=headers)).json()
        assert detail["status"] == "disposed"
        assert detail["can_submit_statement"] is False
        assert detail["can_submit_appeal"] is True
        resp = await client.post(
            f"/api/v1/me/cases/{case.id}/statement", headers=headers, json={"content": "处置后说明"}
        )
        assert resp.status_code == 409
        resp = await client.post(
            f"/api/v1/me/cases/{case.id}/appeal", headers=headers, json={"content": "申请复核"}
        )
        assert resp.status_code == 200, resp.text

    # 第三方仍无资格。
    resp = await client.post(
        f"/api/v1/me/cases/{case.id}/appeal", headers=third_h, json={"content": "第三方申辩"}
    )
    assert resp.status_code == 403


async def test_report_case_trade_link_does_not_expand_access(client, db, world):
    """普通举报即使关联 trade_id，也不向交易双方扩权，仅 subject_user 可沟通。"""
    admin_h = world["admin_h"]
    seller_h, buyer_h = world["seller_h"], world["buyer_h"]
    seller_id, buyer_id = world["seller"]["id"], world["buyer"]["id"]
    case = await _create_case(
        db,
        case_type="report",
        title="普通举报关联交易",
        trade_id=world["trade_id"],
        subject_user_id=seller_id,
    )
    await _claim(client, admin_h, case.id)
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/inquiry", headers=admin_h, json={"content": "请被举报方说明"}
    )
    assert resp.status_code == 200, resp.text
    recipients = await _notification_user_ids(db, case.id, "inquiry")
    assert recipients == [seller_id]
    assert buyer_id not in recipients

    # 交易参与方买方不是该举报事项主体，不能借 trade_id 扩权。
    assert (await client.get(f"/api/v1/me/cases/{case.id}", headers=buyer_h)).status_code == 403
    assert (
        await client.post(
            f"/api/v1/me/cases/{case.id}/statement", headers=buyer_h, json={"content": "越权说明"}
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/me/cases/{case.id}/appeal", headers=buyer_h, json={"content": "越权申辩"}
        )
    ).status_code == 403

    # 本人事项列表也不向非主体交易方展示该举报事项。
    buyer_cases = (await client.get("/api/v1/me/cases", headers=buyer_h)).json()
    assert all(c["id"] != case.id for c in buyer_cases)
    seller_cases = (await client.get("/api/v1/me/cases", headers=seller_h)).json()
    assert any(c["id"] == case.id for c in seller_cases)

    detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=seller_h)).json()
    assert detail["can_submit_statement"] is True
    assert detail["can_submit_appeal"] is False
    resp = await client.post(
        f"/api/v1/me/cases/{case.id}/statement", headers=seller_h, json={"content": "本人说明"}
    )
    assert resp.status_code == 200


async def test_closed_report_repeat_rejected_for_both_outcomes(client, db, world):
    """同一举报人+对象已有终态记录：两种结论均 409 且不新增 Report/Case。"""
    admin_h, buyer_h, seller_h = world["admin_h"], world["buyer_h"], world["seller_h"]

    product_a = await create_listed_product(client, admin_h, seller_h, title="终态举报商品甲")
    first = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product_a["id"], "reason": "疑似违规甲"},
    )
    assert first.status_code == 201, first.text
    report_a = first.json()["id"]
    case_a = await _case_id_for_report(db, report_a)
    await _claim(client, admin_h, case_a)
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{case_a}/decision",
        headers=admin_h,
        json={"outcome": "unfounded", "reason": "证据不足", "public_summary": "经核查依据不足"},
    )
    assert resp.status_code == 200, resp.text
    counts_after_unfounded = await _counts(db)
    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product_a["id"], "reason": "重新举报甲"},
    )
    assert resp.status_code == 409
    assert await _counts(db) == counts_after_unfounded

    product_b = await create_listed_product(client, admin_h, seller_h, title="终态举报商品乙")
    second = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product_b["id"], "reason": "疑似违规乙"},
    )
    assert second.status_code == 201, second.text
    report_b = second.json()["id"]
    case_b = await _case_id_for_report(db, report_b)
    await _claim(client, admin_h, case_b)
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{case_b}/decision",
        headers=admin_h,
        json={"outcome": "handled", "reason": "认定违规", "public_summary": "经核查认定违规并处理"},
    )
    assert resp.status_code == 200, resp.text
    counts_after_handled = await _counts(db)
    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product_b["id"], "reason": "重新举报乙"},
    )
    assert resp.status_code == 409
    assert await _counts(db) == counts_after_handled


async def test_open_report_reuses_record_and_other_user_can_report(client, db, world):
    """未结举报仍返回原记录；其他用户对有效对象可正常新增举报。"""
    admin_h, buyer_h, seller_h, third_h = (
        world["admin_h"],
        world["buyer_h"],
        world["seller_h"],
        world["third_h"],
    )
    product = await create_listed_product(client, admin_h, seller_h, title="未结举报商品")
    before = await _counts(db)
    first = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "未结原因一"},
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "未结原因二"},
    )
    assert second.status_code == 201  # 保持原路由状态码，仅返回原记录
    assert second.json().get("existing_report_id") == first.json()["id"]
    assert await _counts(db) == (before[0] + 1, before[1] + 1)

    other = await client.post(
        "/api/v1/reports",
        headers=third_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "他人有效举报"},
    )
    assert other.status_code == 201, other.text
    assert await _counts(db) == (before[0] + 2, before[1] + 2)


async def test_deleted_comment_and_review_cannot_be_new_targets(client, db, world):
    """逻辑删除的评论/评价拒绝新举报；既有举报仍可读。"""
    from app.models import Comment, Report, TradeReview

    admin_h, buyer_h, seller_h, third_h = (
        world["admin_h"],
        world["buyer_h"],
        world["seller_h"],
        world["third_h"],
    )
    third_id = world["third"]["id"]
    product = await create_listed_product(client, admin_h, seller_h, title="被评论商品")
    comment = Comment(product_id=product["id"], author_id=third_id, content="待移除的评论")
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "comment", "target_id": comment.id, "reason": "违规评论"},
    )
    assert resp.status_code == 201, resp.text
    comment_report = resp.json()["id"]
    case_id = await _case_id_for_report(db, comment_report)
    await _claim(client, admin_h, case_id)
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{case_id}/decision",
        headers=admin_h,
        json={
            "outcome": "handled",
            "reason": "评论违规",
            "public_summary": "违规评论已移除",
            "actions": {"remove_content": True},
        },
    )
    assert resp.status_code == 200, resp.text
    await db.refresh(comment)
    assert comment.deleted_at is not None

    mine = (await client.get("/api/v1/reports/mine", headers=buyer_h)).json()
    assert any(r["id"] == comment_report and r["status"] == "handled" for r in mine)
    counts_before = await _counts(db)
    resp = await client.post(
        "/api/v1/reports",
        headers=seller_h,
        json={"target_type": "comment", "target_id": comment.id, "reason": "再举报已删评论"},
    )
    assert resp.status_code == 400
    assert await _counts(db) == counts_before

    review = TradeReview(
        trade_id=world["trade_id"],
        reviewer_id=world["buyer"]["id"],
        reviewee_id=world["seller"]["id"],
        rating=5,
        content="待移除的评价",
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    resp = await client.post(
        "/api/v1/reports",
        headers=seller_h,
        json={"target_type": "review", "target_id": review.id, "reason": "违规评价"},
    )
    assert resp.status_code == 201, resp.text
    review_report = resp.json()["id"]
    review_case = await _case_id_for_report(db, review_report)
    await _claim(client, admin_h, review_case)
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{review_case}/decision",
        headers=admin_h,
        json={
            "outcome": "handled",
            "reason": "评价违规",
            "public_summary": "违规评价已移除",
            "actions": {"remove_content": True},
        },
    )
    assert resp.status_code == 200, resp.text
    await db.refresh(review)
    assert review.deleted_at is not None

    mine = (await client.get("/api/v1/reports/mine", headers=seller_h)).json()
    assert any(r["id"] == review_report and r["status"] == "handled" for r in mine)
    counts_before = await _counts(db)
    resp = await client.post(
        "/api/v1/reports",
        headers=third_h,
        json={"target_type": "review", "target_id": review.id, "reason": "再举报已删评价"},
    )
    assert resp.status_code == 400
    assert await _counts(db) == counts_before
    # 既有举报记录未被删除。
    assert await db.scalar(select(func.count()).select_from(Report).where(Report.id.in_([comment_report, review_report]))) == 2


async def test_public_report_results_whitelist_order_and_pagination(client, db, world):
    """匿名公开结果：仅确认终态、显式白名单、登录可读、分页与排序（BR-25）。"""
    from app.models import Report, User

    admin_h, buyer_h, seller_h, third_h = (
        world["admin_h"],
        world["buyer_h"],
        world["seller_h"],
        world["third_h"],
    )
    buyer_id = world["buyer"]["id"]

    product_a = await create_listed_product(client, admin_h, seller_h, title="公开结果商品甲")
    report_a = (
        await client.post(
            "/api/v1/reports",
            headers=buyer_h,
            json={
                "target_type": "product",
                "target_id": product_a["id"],
                "reason": "私有原因甲SENTINEL",
                "detail": "私有细节甲SENTINEL",
                "evidence_keys": ["private-evidence-SENTINEL"],
            },
        )
    ).json()["id"]
    case_a = await _case_id_for_report(db, report_a)
    await _claim(client, admin_h, case_a)
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{case_a}/decision",
        headers=admin_h,
        json={
            "outcome": "unfounded",
            "reason": "私有内部理由甲SENTINEL",
            "public_summary": "公开结论甲",
        },
    )
    assert resp.status_code == 200, resp.text

    product_b = await create_listed_product(client, admin_h, seller_h, title="公开结果商品乙")
    report_b = (
        await client.post(
            "/api/v1/reports",
            headers=third_h,
            json={"target_type": "product", "target_id": product_b["id"], "reason": "私有原因乙SENTINEL"},
        )
    ).json()["id"]
    case_b = await _case_id_for_report(db, report_b)
    await _claim(client, admin_h, case_b)
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{case_b}/decision",
        headers=admin_h,
        json={
            "outcome": "handled",
            "reason": "私有内部理由乙SENTINEL",
            "public_summary": "公开结论乙",
        },
    )
    assert resp.status_code == 200, resp.text

    # 未结/未确认记录不得出现在公开列表。
    product_c = await create_listed_product(client, admin_h, seller_h, title="公开结果商品丙")
    pending_report = (
        await client.post(
            "/api/v1/reports",
            headers=buyer_h,
            json={"target_type": "product", "target_id": product_c["id"], "reason": "未结举报"},
        )
    ).json()["id"]
    dirty = Report(
        reporter_id=buyer_id,
        target_type="product",
        target_id=product_c["id"],
        reason="脏数据未确认",
        status="handled",
        result_confirmed=False,
        public_result="不应公开SENTINEL",
        closed_at=datetime.now(UTC),
    )
    db.add(dirty)
    await db.commit()
    await db.refresh(dirty)

    # 匿名拒绝。
    assert (await client.get("/api/v1/reports/public")).status_code == 401

    resp = await client.get("/api/v1/reports/public", headers=third_h, params={"limit": 50, "offset": 0})
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    public_ids = [row["id"] for row in rows]
    assert report_a in public_ids and report_b in public_ids
    assert pending_report not in public_ids
    assert dirty.id not in public_ids
    for row in rows:
        assert set(row) == {"id", "target_type", "status", "public_result", "closed_at"}
    by_id = {row["id"]: row for row in rows}
    assert by_id[report_a]["public_result"] == "公开结论甲"
    assert by_id[report_b]["public_result"] == "公开结论乙"
    body = resp.text
    assert "SENTINEL" not in body
    assert "私有" not in body

    # 排序：closed_at desc, id desc。
    db.expire_all()
    expected_ids = list(
        (
            await db.scalars(
                select(Report.id)
                .where(
                    Report.result_confirmed.is_(True),
                    Report.status.in_(["handled", "unfounded"]),
                )
                .order_by(Report.closed_at.desc(), Report.id.desc())
                .limit(50)
            )
        ).all()
    )
    assert public_ids == expected_ids

    # 分页切片与参数校验。
    page1 = (
        await client.get("/api/v1/reports/public", headers=third_h, params={"limit": 1, "offset": 0})
    ).json()
    page2 = (
        await client.get("/api/v1/reports/public", headers=third_h, params={"limit": 1, "offset": 1})
    ).json()
    assert [row["id"] for row in page1] == expected_ids[:1]
    assert [row["id"] for row in page2] == expected_ids[1:2]
    assert (await client.get("/api/v1/reports/public", headers=third_h, params={"limit": 0})).status_code == 422
    assert (await client.get("/api/v1/reports/public", headers=third_h, params={"limit": 51})).status_code == 422
    assert (await client.get("/api/v1/reports/public", headers=third_h, params={"offset": -1})).status_code == 422

    # 封禁用户仍可公共只读；管理员也可读。
    banned = await db.get(User, buyer_id)
    banned.status = "banned"
    await db.commit()
    assert (await client.get("/api/v1/reports/public", headers=buyer_h)).status_code == 200
    assert (await client.get("/api/v1/reports/public", headers=admin_h)).status_code == 200


async def test_admin_product_search_remains_public_listed_only(client, db, world):
    """管理端复用公开商品搜索：不因管理身份返回待审/驳回/限制/下架商品。"""
    from app.models import Product

    admin_h, seller_h = world["admin_h"], world["seller_h"]
    listed = await create_listed_product(client, admin_h, seller_h, title="审计搜索在售商品")
    pending = await publish_product(client, seller_h, title="审计搜索待审商品")
    rejected = await publish_product(client, seller_h, title="审计搜索驳回商品")
    restricted = await create_listed_product(client, admin_h, seller_h, title="审计搜索限制商品")
    delisted = await create_listed_product(client, admin_h, seller_h, title="审计搜索下架商品")

    rejected_row = await db.get(Product, rejected["id"])
    rejected_row.status = "rejected"
    restricted_row = await db.get(Product, restricted["id"])
    restricted_row.display_restricted = True
    delisted_row = await db.get(Product, delisted["id"])
    delisted_row.status = "delisted"
    await db.commit()

    resp = await client.get(
        "/api/v1/products/search",
        headers=admin_h,
        params={"keyword": "审计搜索", "page": 1, "page_size": 50},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = {item["id"] for item in data["items"]}
    assert listed["id"] in ids
    assert ids.isdisjoint({pending["id"], rejected["id"], restricted["id"], delisted["id"]})
    assert data["total"] == 1


async def test_archived_report_wins_after_target_invalidated(client, db, world):
    """原举报已 handled 且对象后被撤展/删除：原举报人仍 409，其他人 400，原记录可查。"""
    from app.models import Comment, Product, TradeReview

    admin_h, buyer_h, seller_h, third_h = (
        world["admin_h"],
        world["buyer_h"],
        world["seller_h"],
        world["third_h"],
    )
    buyer_id, seller_id, third_id = world["buyer"]["id"], world["seller"]["id"], world["third"]["id"]

    async def close_handled(report_id: int, actions: dict) -> None:
        case_id = await _case_id_for_report(db, report_id)
        await _claim(client, admin_h, case_id)
        resp = await client.post(
            f"/api/v1/admin/reports/cases/{case_id}/decision",
            headers=admin_h,
            json={
                "outcome": "handled",
                "reason": "认定违规并处置",
                "public_summary": "已核查处理",
                "actions": actions,
            },
        )
        assert resp.status_code == 200, resp.text

    async def assert_archived_wins(
        owner_h: dict, other_h: dict, target_type: str, target_id: int, report_id: int
    ) -> None:
        before = await _counts(db)
        resp = await client.post(
            "/api/v1/reports",
            headers=owner_h,
            json={"target_type": target_type, "target_id": target_id, "reason": "原举报人重报"},
        )
        assert resp.status_code == 409, resp.text
        assert "existing_report_id" not in resp.json()
        assert await _counts(db) == before
        # 其他人面对已失效对象仍是 400，不能因历史归档记录被误当成可报目标。
        resp = await client.post(
            "/api/v1/reports",
            headers=other_h,
            json={"target_type": target_type, "target_id": target_id, "reason": "他人举报失效对象"},
        )
        assert resp.status_code == 400, resp.text
        assert await _counts(db) == before
        # 原记录保持只读可查。
        mine = (await client.get("/api/v1/reports/mine", headers=owner_h)).json()
        original = next(r for r in mine if r["id"] == report_id)
        assert original["status"] == "handled"
        assert original["result_confirmed"] is True
        assert original["public_result"] == "已核查处理"

    # 1) handled + 商品被 display_restricted，对象已不能作为新目标。
    product = await create_listed_product(client, admin_h, seller_h, title="已撤展的举报商品")
    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "违规商品"},
    )
    assert resp.status_code == 201, resp.text
    product_report = resp.json()["id"]
    await close_handled(product_report, {"restrict_display": True})
    product_row = await db.get(Product, product["id"])
    assert product_row is not None and product_row.display_restricted is True
    await assert_archived_wins(buyer_h, third_h, "product", product["id"], product_report)

    # 2) handled + 评论被逻辑删除。
    comment = Comment(product_id=product["id"], author_id=third_id, content="待移除的举报评论")
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "comment", "target_id": comment.id, "reason": "违规评论"},
    )
    assert resp.status_code == 201, resp.text
    comment_report = resp.json()["id"]
    await close_handled(comment_report, {"remove_content": True})
    await db.refresh(comment)
    assert comment.deleted_at is not None
    await assert_archived_wins(buyer_h, seller_h, "comment", comment.id, comment_report)

    # 3) handled + 评价被逻辑删除。
    review = TradeReview(
        trade_id=world["trade_id"],
        reviewer_id=buyer_id,
        reviewee_id=seller_id,
        rating=5,
        content="待移除的举报评价",
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    resp = await client.post(
        "/api/v1/reports",
        headers=seller_h,
        json={"target_type": "review", "target_id": review.id, "reason": "违规评价"},
    )
    assert resp.status_code == 201, resp.text
    review_report = resp.json()["id"]
    await close_handled(review_report, {"remove_content": True})
    await db.refresh(review)
    assert review.deleted_at is not None
    await assert_archived_wins(seller_h, third_h, "review", review.id, review_report)


async def test_archived_history_precedes_open_duplicate(client, db, world):
    """同对象同时存在未结和终态历史记录时，先命中归档记录 409，不返回未结原 id。"""
    from app.models import Report

    admin_h, seller_h, buyer_h, third_h = (
        world["admin_h"],
        world["seller_h"],
        world["buyer_h"],
        world["third_h"],
    )
    product = await create_listed_product(client, admin_h, seller_h, title="历史优先级商品")
    terminal = Report(
        reporter_id=world["buyer"]["id"],
        target_type="product",
        target_id=product["id"],
        reason="历史终态",
        status="handled",
        result_confirmed=True,
        public_result="历史处理结果",
        closed_at=datetime.now(UTC),
    )
    open_record = Report(
        reporter_id=world["buyer"]["id"],
        target_type="product",
        target_id=product["id"],
        reason="历史未结",
        status="pending",
    )
    db.add_all([terminal, open_record])
    await db.commit()
    await db.refresh(terminal)
    await db.refresh(open_record)

    before = await _counts(db)
    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "再次举报"},
    )
    assert resp.status_code == 409, resp.text
    assert "existing_report_id" not in resp.json()
    assert await _counts(db) == before

    await db.refresh(terminal)
    await db.refresh(open_record)
    assert terminal.status == "handled"
    assert open_record.status == "pending"

    # 归档判断只针对同一举报人；其他用户对仍有效对象仍可正常新增。
    resp = await client.post(
        "/api/v1/reports",
        headers=third_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "他人有效举报"},
    )
    assert resp.status_code == 201, resp.text
    assert await _counts(db) == (before[0] + 1, before[1] + 1)


async def test_blank_text_inputs_422_without_side_effects(client, db, world):
    """五类沟通/举报文本先去空白再校验：全空白 422，且不产生消息、通知或举报。"""
    admin_h, seller_h, buyer_h = world["admin_h"], world["seller_h"], world["buyer_h"]

    product = await create_listed_product(client, admin_h, seller_h, title="输入校验商品")

    # ReportCreateIn.reason：500 上限保持；空白/超长均不创建 Report/Case。
    before = await _side_effect_counts(db)
    for blank in ("   ", "\t\n "):
        resp = await client.post(
            "/api/v1/reports",
            headers=buyer_h,
            json={"target_type": "product", "target_id": product["id"], "reason": blank},
        )
        assert resp.status_code == 422, resp.text
        assert await _side_effect_counts(db) == before
    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product["id"], "reason": "x" * 501},
    )
    assert resp.status_code == 422
    assert await _side_effect_counts(db) == before

    resp = await client.post(
        "/api/v1/reports",
        headers=buyer_h,
        json={"target_type": "product", "target_id": product["id"], "reason": " 有效原因 "},
    )
    assert resp.status_code == 201, resp.text
    report_id = resp.json()["id"]
    case_id = await _case_id_for_report(db, report_id)

    # SupplementIn.content：2000 上限保持；空白/超长均不写补充。
    before = await _side_effect_counts(db)
    for blank in ("   ", "\t\n "):
        resp = await client.post(
            f"/api/v1/reports/{report_id}/supplements", headers=buyer_h, json={"content": blank}
        )
        assert resp.status_code == 422, resp.text
        assert await _side_effect_counts(db) == before
    resp = await client.post(
        f"/api/v1/reports/{report_id}/supplements", headers=buyer_h, json={"content": "x" * 2001}
    )
    assert resp.status_code == 422
    assert await _side_effect_counts(db) == before

    await _claim(client, admin_h, case_id)

    # InquiryIn.content：空白/超长 422，不写问询消息或通知。
    before = await _side_effect_counts(db)
    for blank in ("   ", "\t\n "):
        resp = await client.post(
            f"/api/v1/admin/cases/{case_id}/inquiry", headers=admin_h, json={"content": blank}
        )
        assert resp.status_code == 422, resp.text
        assert await _side_effect_counts(db) == before
    resp = await client.post(
        f"/api/v1/admin/cases/{case_id}/inquiry", headers=admin_h, json={"content": "x" * 2001}
    )
    assert resp.status_code == 422
    assert await _side_effect_counts(db) == before

    # CaseMessageIn.content：空白/超长 422，不写回复或通知。
    before = await _side_effect_counts(db)
    for blank in ("   ", "\t\n "):
        resp = await client.post(
            f"/api/v1/admin/cases/{case_id}/messages", headers=admin_h, json={"content": blank}
        )
        assert resp.status_code == 422, resp.text
        assert await _side_effect_counts(db) == before
    resp = await client.post(
        f"/api/v1/admin/cases/{case_id}/messages", headers=admin_h, json={"content": "x" * 2001}
    )
    assert resp.status_code == 422
    assert await _side_effect_counts(db) == before

    # 有效问询后 StatementIn.content 空白/超长 422，不写说明消息。
    resp = await client.post(
        f"/api/v1/admin/cases/{case_id}/inquiry", headers=admin_h, json={"content": "请说明商品来源"}
    )
    assert resp.status_code == 200, resp.text
    before = await _side_effect_counts(db)
    for blank in ("   ", "\t\n "):
        resp = await client.post(
            f"/api/v1/me/cases/{case_id}/statement", headers=seller_h, json={"content": blank}
        )
        assert resp.status_code == 422, resp.text
        assert await _side_effect_counts(db) == before
    resp = await client.post(
        f"/api/v1/me/cases/{case_id}/statement", headers=seller_h, json={"content": "x" * 2001}
    )
    assert resp.status_code == 422
    assert await _side_effect_counts(db) == before

    # 合法输入仍正常落库，证明 422 不是把所有输入都拒绝。
    resp = await client.post(
        f"/api/v1/me/cases/{case_id}/statement", headers=seller_h, json={"content": " 自用闲置 "}
    )
    assert resp.status_code == 200, resp.text
    after = await _side_effect_counts(db)
    assert after["messages"] == before["messages"] + 1
    detail = (await client.get(f"/api/v1/me/cases/{case_id}", headers=seller_h)).json()
    assert detail["messages"][-1]["content"] == "自用闲置"


async def test_inquiry_requires_processing_and_capability_matches(client, db, world):
    """仅 processing 可新问询；pending/disposed 均 409，详情布尔值与 POST 入口一致。"""
    admin_h, seller_h = world["admin_h"], world["seller_h"]
    case = await _create_case(
        db,
        case_type="report",
        title="问询状态门禁",
        subject_user_id=world["seller"]["id"],
    )

    before = await _side_effect_counts(db)
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/inquiry", headers=admin_h, json={"content": "待处理阶段问询"}
    )
    assert resp.status_code == 409, resp.text
    assert await _side_effect_counts(db) == before
    detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=seller_h)).json()
    assert detail["status"] == "pending"
    assert detail["can_submit_statement"] is False
    assert (
        await client.post(
            f"/api/v1/me/cases/{case.id}/statement", headers=seller_h, json={"content": "提前说明"}
        )
    ).status_code == 409

    await _claim(client, admin_h, case.id)
    detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=seller_h)).json()
    assert detail["status"] == "processing"
    assert detail["can_submit_statement"] is False
    before = await _side_effect_counts(db)
    resp = await client.post(
        f"/api/v1/me/cases/{case.id}/statement", headers=seller_h, json={"content": "未问询先说明"}
    )
    assert resp.status_code == 409
    assert await _side_effect_counts(db) == before

    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/inquiry", headers=admin_h, json={"content": "请说明情况"}
    )
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=seller_h)).json()
    assert detail["can_submit_statement"] is True
    assert (
        await client.post(
            f"/api/v1/me/cases/{case.id}/statement", headers=seller_h, json={"content": "情况说明"}
        )
    ).status_code == 200

    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/dispose", headers=admin_h, json={"conclusion": "处理完毕"}
    )
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=seller_h)).json()
    assert detail["status"] == "disposed"
    assert detail["can_submit_statement"] is False
    assert detail["can_submit_appeal"] is True
    before = await _side_effect_counts(db)
    resp = await client.post(
        f"/api/v1/admin/cases/{case.id}/inquiry", headers=admin_h, json={"content": "处置后再问询"}
    )
    assert resp.status_code == 409
    assert await _side_effect_counts(db) == before


async def test_banned_user_can_still_submit_appeal(client, db, world):
    """封禁用户仍可使用处置沟通单申辩，不因全局写限制被 403 挡住。"""
    from app.models import User

    buyer_h, buyer_id = world["buyer_h"], world["buyer"]["id"]
    case = await _create_case(
        db,
        case_type="report",
        title="封禁用户申辩通道",
        status="disposed",
        subject_user_id=buyer_id,
        conclusion="认定违规并处置",
        disposed_at=datetime.now(UTC),
    )
    banned = await db.get(User, buyer_id)
    banned.status = "banned"
    await db.commit()

    detail = (await client.get(f"/api/v1/me/cases/{case.id}", headers=buyer_h)).json()
    assert detail["can_submit_statement"] is False
    assert detail["can_submit_appeal"] is True
    before = await _side_effect_counts(db)
    resp = await client.post(
        f"/api/v1/me/cases/{case.id}/appeal", headers=buyer_h, json={"content": "申请复核"}
    )
    assert resp.status_code == 200, resp.text
    after = await _side_effect_counts(db)
    assert after["messages"] == before["messages"] + 1
    # 说明入口仍按状态关闭，返回 409 而不是被全局封禁检查改成 403。
    assert (
        await client.post(
            f"/api/v1/me/cases/{case.id}/statement", headers=buyer_h, json={"content": "处置后说明"}
        )
    ).status_code == 409

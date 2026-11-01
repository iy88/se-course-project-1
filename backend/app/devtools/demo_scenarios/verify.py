"""持久演示数据的只读核验。

核验项：manifest/目录摘要、账号、文件可读性与对象登记、场景覆盖、目录初始状态、
跨实体不变量，以及一组只读 API 可见性/权限检查。不写业务记录、不推进已读、
不打印密码、签名 URL 或连接串。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.devtools.demo_scenarios import catalog


@dataclass
class VerificationReport:
    checks: int = 0
    errors: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def ok(self) -> bool:
        return not self.errors


def _object_models():
    from app.models.category import Category, CategoryAlias
    from app.models.governance import DisposalCase, Notification, Report, ReportSupplement
    from app.models.im import Conversation, Message
    from app.models.product import (
        Comment,
        Favorite,
        Product,
        ProductEditHistory,
        ProductTagApplication,
        ReviewRecord,
    )
    from app.models.trade import (
        CompletionConfirmation,
        Trade,
        TradeAgreement,
        TradeReview,
        TradeTransition,
    )
    from app.models.user import AccountRestriction, User

    return {
        "account": User,
        "avatar": User,
        "category": Category,
        "category_alias": CategoryAlias,
        "product": Product,
        "review_record": ReviewRecord,
        "tag_application": ProductTagApplication,
        "edit_history": ProductEditHistory,
        "comment": Comment,
        "favorite": Favorite,
        "trade": Trade,
        "agreement": TradeAgreement,
        "confirmation": CompletionConfirmation,
        "trade_transition": TradeTransition,
        "trade_review": TradeReview,
        "conversation": Conversation,
        "message": Message,
        "report": Report,
        "report_supplement": ReportSupplement,
        "disposal_case": DisposalCase,
        "account_restriction": AccountRestriction,
        "notification": Notification,
    }


def _id(data: dict, key: str) -> int:
    entry = data["objects"].get(key)
    if not isinstance(entry, dict):
        raise ValueError(f"manifest 缺少对象 {key}")
    return int(entry["id"])


def _at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _scenario_object_keys() -> Iterable[str]:
    for scenario in catalog.SCENARIOS:
        yield from scenario.objects


async def _verify_accounts(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.core.security import verify_password
    from app.models.user import User

    for spec in catalog.ACCOUNTS:
        account = data["accounts"][spec.key]
        user = await session.get(User, account.get("id"))
        report.check(user is not None, f"账号不存在：{spec.key}")
        if user is None:
            continue
        report.check(user.email == account["email"], f"账号邮箱不符：{spec.key}")
        report.check(user.role == spec.role, f"账号角色不符：{spec.key}")
        report.check(user.display_name == spec.display_name, f"账号显示名不符：{spec.key}")
        report.check(verify_password(account["password"], user.password_hash), f"账号密码不可验证：{spec.key}")
    report.counts["accounts"] = len(catalog.ACCOUNTS)


async def _verify_objects(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    models = _object_models()
    for key, entry in data["objects"].items():
        report.check(isinstance(entry, dict) and "kind" in entry and "id" in entry, f"对象结构不完整：{key}")
        if not isinstance(entry, dict):
            continue
        model = models.get(entry.get("kind"))
        report.check(model is not None, f"未知对象类型：{key}")
        if model is None:
            continue
        obj = await session.get(model, entry["id"])
        report.check(obj is not None, f"对象记录缺失：{key}")
    for scenario in catalog.SCENARIOS:
        for key in scenario.objects:
            report.check(key in data["objects"], f"场景对象未登记：{scenario.key}/{key}")
    report.check(set(data.get("scenarios", [])) == {s.key for s in catalog.SCENARIOS},
                 "manifest 场景列表与目录不一致")
    report.counts["objects"] = len(data["objects"])


async def _verify_files(session: AsyncSession, storage, data: dict, report: VerificationReport) -> None:
    import hashlib

    from app.models.stored_object import StoredObject
    from app.storage.base import bucket_role_for_namespace

    for name, entry in data["files"].items():
        key = entry["key"]
        try:
            content = storage.open(key)
        except Exception:  # noqa: BLE001 - storage boundary
            report.check(False, f"文件不可读：{name}")
            continue
        report.check(len(content) == entry.get("size"), f"文件大小不符：{name}")
        report.check(hashlib.sha256(content).hexdigest() == entry.get("sha256"), f"文件摘要不符：{name}")
        obj = await session.get(StoredObject, key)
        report.check(obj is not None and obj.state == "committed", f"对象登记未提交：{name}")
        if obj is not None:
            report.check(obj.size_bytes == len(content), f"对象大小不符：{name}")
            report.check(obj.namespace == entry.get("namespace"), f"对象命名空间不符：{name}")
            report.check(obj.bucket_role == bucket_role_for_namespace(entry["namespace"]), f"对象桶角色不符：{name}")
    # 文件与业务对象关联：商品图、头像、举报证据/补充证据。
    from app.models.governance import Report, ReportSupplement
    from app.models.product import Product, ProductImage
    from app.models.user import User

    checked_refs: set[str] = set()
    for spec in catalog.PRODUCTS:
        product = await session.get(Product, _id(data, spec.key))
        if product is None:
            continue
        images = (await session.exec(select(ProductImage).where(ProductImage.product_id == product.id))).all()
        report.check(len(images) == 1, f"商品图片数量不符：{spec.key}")
        for image in images:
            obj = await session.get(StoredObject, image.file_key)
            report.check(obj is not None, f"商品图未登记对象：{spec.key}")
            if obj is not None:
                report.check(obj.ref_type == "product" and obj.ref_id == product.id, f"商品图关联不符：{spec.key}")
            checked_refs.add(image.file_key)
    for avatar_spec in catalog.AVATARS:
        user = await session.get(User, _id(data, f"account_{avatar_spec.user}"))
        if user is None or not user.avatar_pending_key:
            continue
        obj = await session.get(StoredObject, user.avatar_pending_key)
        report.check(obj is not None and obj.ref_type == "avatar" and obj.ref_id == user.id,
                     f"头像对象关联不符：{avatar_spec.user}")
        checked_refs.add(user.avatar_pending_key)
    for report_spec in catalog.REPORTS:
        item = await session.get(Report, _id(data, report_spec.key))
        if item is None:
            continue
        for key in item.evidence_keys:
            obj = await session.get(StoredObject, key)
            report.check(obj is not None and obj.ref_type == "report" and obj.ref_id == item.id,
                         f"举报证据关联不符：{report_spec.key}")
            checked_refs.add(key)
        for supplement in (await session.exec(
            select(ReportSupplement).where(ReportSupplement.report_id == item.id)
        )).all():
            for key in supplement.evidence_keys:
                obj = await session.get(StoredObject, key)
                report.check(obj is not None and obj.ref_type == "report_supplement" and obj.ref_id == supplement.id,
                             f"举报补充证据关联不符：{report_spec.key}")
                checked_refs.add(key)
    report.check(len(checked_refs) == len(data["files"]), "存在未关联业务对象的登记文件")
    report.counts["files"] = len(data["files"])


async def _verify_products(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.category import CategoryAlias
    from app.models.product import (
        Comment,
        Favorite,
        Product,
        ProductEditHistory,
        ProductTag,
        ProductTagApplication,
        ReviewRecord,
    )

    for spec in catalog.PRODUCTS:
        product = await session.get(Product, _id(data, spec.key))
        report.check(product is not None, f"商品缺失：{spec.key}")
        if product is None:
            continue
        report.check(product.title == spec.title, f"商品标题不符：{spec.key}")
        report.check(product.description == spec.description, f"商品描述不符：{spec.key}")
        report.check(product.price_cents == spec.price_cents, f"商品价格不符：{spec.key}")
        report.check(product.status == spec.status, f"商品状态不符：{spec.key}")
        report.check(product.display_restricted == spec.display_restricted, f"商品展示限制不符：{spec.key}")
        if spec.display_restricted:
            report.check(product.display_restricted_case_id is not None, f"受限商品缺少事项：{spec.key}")
            report.check(bool(product.display_restricted_reason), f"受限商品缺少原因：{spec.key}")
        else:
            report.check(not product.display_restricted_reason, f"未受限商品残留限制原因：{spec.key}")
        for tag_key in spec.all_tags:
            category_id = _id(data, tag_key)
            tagged = (await session.exec(
                select(ProductTag).where(ProductTag.product_id == product.id, ProductTag.category_id == category_id)
            )).first()
            report.check(tagged is not None, f"商品标签缺失：{spec.key}/{tag_key}")

        reviews = list((await session.exec(
            select(ReviewRecord).where(ReviewRecord.product_id == product.id).order_by(col(ReviewRecord.id))
        )).all())
        expected_reviews = spec.reviews or (
            (catalog.ReviewSpec("approved", spec.listed_days_ago or spec.created_days_ago, reviewer="admin"),)
            if spec.status in {"listed", "in_transaction", "delisted"} else ()
        )
        report.check(len(reviews) >= len(expected_reviews), f"审核记录不足：{spec.key}")
        for index, review_spec in enumerate(expected_reviews):
            if index >= len(reviews):
                continue
            record = reviews[index]
            report.check(record.result == review_spec.result, f"审核结论不符：{spec.key}/{index}")
            if review_spec.result == "pending":
                case = await session.get(__import__("app.models", fromlist=["DisposalCase"]).DisposalCase, record.case_id)
                report.check(case is not None and case.status != "disposed", f"待审事项状态不符：{spec.key}")
            else:
                report.check(record.reviewed_at is not None, f"审核时间缺失：{spec.key}/{index}")

        apps = list((await session.exec(
            select(ProductTagApplication).where(ProductTagApplication.product_id == product.id).order_by(col(ProductTagApplication.id))
        )).all())
        report.check(len(apps) == len(spec.tag_apps), f"标签申请数量不符：{spec.key}")
        for index, app_spec in enumerate(spec.tag_apps):
            if index >= len(apps):
                continue
            report.check(apps[index].requested_name == app_spec.requested_name, f"标签申请名称不符：{spec.key}")
            report.check(apps[index].status == app_spec.status, f"标签申请状态不符：{spec.key}")
            if app_spec.status == "rejected":
                report.check(bool(apps[index].decision_reason), f"拒绝标签缺少原因：{spec.key}")
        if "课本" in [app.requested_name for app in spec.tag_apps]:
            alias = (await session.exec(
                select(CategoryAlias).where(CategoryAlias.name == "课本", CategoryAlias.removed_at.is_(None))
            )).first()
            report.check(alias is not None, "教材别名“课本”缺失")

        edits = list((await session.exec(
            select(ProductEditHistory).where(ProductEditHistory.product_id == product.id).order_by(col(ProductEditHistory.id))
        )).all())
        report.check(len(edits) == len(spec.edits), f"商品编辑历史数量不符：{spec.key}")
        for index, edit_spec in enumerate(spec.edits):
            if index >= len(edits):
                continue
            report.check(edits[index].edit_type == edit_spec.edit_type, f"编辑类型不符：{spec.key}")
            report.check(edits[index].before_json == edit_spec.before, f"编辑前内容不符：{spec.key}")
            report.check(edits[index].after_json == edit_spec.after, f"编辑后内容不符：{spec.key}")

        comments = list((await session.exec(
            select(Comment).where(Comment.product_id == product.id).order_by(col(Comment.id))
        )).all())
        report.check(len(comments) == len(spec.comments), f"评论数量不符：{spec.key}")
        by_key = {}
        for index, comment_spec in enumerate(spec.comments):
            if index >= len(comments):
                continue
            comment = comments[index]
            by_key[comment_spec.key] = comment
            report.check(comment.content == comment_spec.content, f"评论内容不符：{comment_spec.key}")
            report.check((comment.deleted_at is not None) == (comment_spec.deleted_days_ago is not None),
                         f"评论删除标记不符：{comment_spec.key}")
            if comment_spec.reply_to:
                parent = by_key.get(comment_spec.reply_to)
                report.check(parent is not None and comment.reply_to_comment_id == parent.id,
                             f"评论回复关系不符：{comment_spec.key}")
        for user_key in spec.favorites:
            favorite = (await session.exec(
                select(Favorite).where(Favorite.user_id == _id(data, f"account_{user_key}"), Favorite.product_id == product.id)
            )).first()
            report.check(favorite is not None, f"收藏缺失：{spec.key}/{user_key}")
    report.counts["products"] = len(catalog.PRODUCTS)


async def _verify_case_messages(session: AsyncSession, data: dict, case, case_spec, report: VerificationReport, label: str) -> None:
    from app.models.governance import DisposalMessage

    messages = list((await session.exec(
        select(DisposalMessage).where(DisposalMessage.case_id == case.id).order_by(col(DisposalMessage.id))
    )).all())
    report.check(len(messages) == len(case_spec.messages), f"事项沟通数量不符：{label}")
    for index, message_spec in enumerate(case_spec.messages):
        if index >= len(messages):
            continue
        message = messages[index]
        report.check(message.content == message_spec.content, f"事项沟通内容不符：{label}/{index}")
        report.check(message.role == message_spec.role, f"事项沟通角色不符：{label}/{index}")
        expected = _id(data, f"account_{message_spec.sender}") if message_spec.sender else None
        report.check(message.sender_id == expected, f"事项沟通发送者不符：{label}/{index}")


async def _verify_trades(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.im import Conversation, ConversationRead, Message
    from app.models.product import Product
    from app.models.trade import (
        CompletionConfirmation,
        Trade,
        TradeAgreement,
        TradeReview,
        TradeTransition,
    )

    locking_products: set[int] = set()
    for spec in catalog.TRADES:
        trade = await session.get(Trade, _id(data, spec.key))
        report.check(trade is not None, f"交易缺失：{spec.key}")
        if trade is None:
            continue
        product = await session.get(Product, _id(data, spec.product))
        report.check(product is not None, f"交易商品缺失：{spec.key}")
        report.check(trade.status == spec.status, f"交易状态不符：{spec.key}")
        report.check(trade.buyer_id == _id(data, f"account_{spec.buyer}"), f"交易买方不符：{spec.key}")
        if product is not None:
            report.check(trade.seller_id == product.seller_id, f"交易卖方不符：{spec.key}")
            if spec.status in {"in_progress", "disputed", "abnormal"}:
                report.check(product.status == "in_transaction", f"锁单商品状态不符：{spec.key}")
                report.check(product.id not in locking_products, f"同商品存在多笔锁单：{spec.key}")
                locking_products.add(product.id)
            if spec.status in {"completed", "terminated"}:
                report.check(product.status == "delisted", f"结束交易商品未下架：{spec.key}")
                report.check(trade.finished_at is not None, f"结束交易缺少完成时间：{spec.key}")
        report.check((trade.accepted_at is not None) == (spec.accepted_days_ago is not None), f"接受时间不符：{spec.key}")
        if spec.status in {"completed", "terminated"}:
            report.check(trade.frozen is False, f"结束交易仍冻结：{spec.key}")
            report.check(trade.finished_at is not None, f"结束时间缺失：{spec.key}")

        agreements = list((await session.exec(
            select(TradeAgreement).where(TradeAgreement.trade_id == trade.id).order_by(col(TradeAgreement.round_no))
        )).all())
        report.check(len(agreements) == len(spec.agreements), f"约定数量不符：{spec.key}")
        for index, agreement_spec in enumerate(spec.agreements):
            if index >= len(agreements):
                continue
            report.check(agreements[index].round_no == agreement_spec.round_no, f"约定轮次不符：{spec.key}")
            report.check(agreements[index].status == agreement_spec.status, f"约定状态不符：{spec.key}")
            report.check(agreements[index].amount_cents == agreement_spec.amount_cents, f"约定金额不符：{spec.key}")
        if spec.current_round is None:
            report.check(trade.current_agreement_id is None, f"不应有当前约定：{spec.key}")
        else:
            current = next((item for item in agreements if item.round_no == spec.current_round), None)
            report.check(current is not None and trade.current_agreement_id == (current.id if current else None),
                         f"当前约定不符：{spec.key}")
            report.check(current is not None and current.status == "confirmed", f"当前约定未确认：{spec.key}")

        confirmations = list((await session.exec(
            select(CompletionConfirmation).where(CompletionConfirmation.trade_id == trade.id).order_by(col(CompletionConfirmation.id))
        )).all())
        report.check(len(confirmations) == len(spec.confirmations), f"完成确认数量不符：{spec.key}")
        expected_current = {item.confirmer for item in spec.confirmations if item.is_current}
        actual_current = {item.confirmer_id for item in confirmations if item.is_current}
        report.check(actual_current == {_id(data, f"account_{key}") for key in expected_current},
                     f"当前完成确认不符：{spec.key}")
        if spec.status in {"completed"} and spec.finished_by is None:
            report.check(len(actual_current) == 2, f"正常完成交易缺少双方当前确认：{spec.key}")
        if spec.status in {"disputed"}:
            report.check(trade.confirm_wait_started_at is None, f"争议交易仍计时：{spec.key}")
        if spec.frozen:
            report.check(trade.frozen, f"交易冻结标记不符：{spec.key}")
            if spec.confirm_wait_started_days_ago is not None and any(c.is_current for c in confirmations):
                report.check(trade.confirm_wait_paused_at is not None, f"冻结交易未暂停计时：{spec.key}")
                report.check(trade.confirm_wait_remaining_seconds is not None, f"冻结交易缺少剩余时间：{spec.key}")
        if spec.cancel_requested_by:
            report.check(trade.cancel_requested_by_id == _id(data, f"account_{spec.cancel_requested_by}"),
                         f"取消申请人不符：{spec.key}")
        else:
            report.check(trade.cancel_requested_by_id is None, f"取消申请人残留：{spec.key}")
        if spec.resolution_confirmed_by:
            report.check(trade.resolution_confirmed_by_id == _id(data, f"account_{spec.resolution_confirmed_by}"),
                         f"争议解决确认人不符：{spec.key}")

        transitions = list((await session.exec(
            select(TradeTransition).where(TradeTransition.trade_id == trade.id).order_by(col(TradeTransition.id))
        )).all())
        report.check(len(transitions) >= 1, f"交易缺少状态转移：{spec.key}")
        if transitions:
            report.check(transitions[0].to_status == "pending_acceptance", f"首个转移不是待接受：{spec.key}")
            report.check(transitions[-1].to_status == spec.status, f"最后转移与状态不符：{spec.key}")
            previous = None
            for transition in transitions:
                created = _at(transition.created_at)
                report.check(created is not None, f"转移缺时间：{spec.key}")
                report.check(previous is None or (created is not None and previous is not None and created >= previous),
                             f"转移时间倒序：{spec.key}")
                previous = created

        reviews = list((await session.exec(
            select(TradeReview).where(TradeReview.trade_id == trade.id).order_by(col(TradeReview.id))
        )).all())
        report.check(len(reviews) == len(spec.reviews), f"交易评价数量不符：{spec.key}")
        for index, review_spec in enumerate(spec.reviews):
            if index >= len(reviews):
                continue
            report.check(reviews[index].rating == review_spec.rating, f"交易评分不符：{spec.key}")
            report.check(reviews[index].content == review_spec.content, f"交易评价内容不符：{spec.key}")
            report.check((reviews[index].deleted_at is not None) == (review_spec.deleted_days_ago is not None),
                         f"交易评价删除标记不符：{spec.key}")

        conversation = (await session.exec(
            select(Conversation).where(Conversation.type == "trade", Conversation.trade_id == trade.id)
        )).first()
        report.check(conversation is not None, f"交易分支缺失：{spec.key}")
        if conversation is not None:
            terminal = spec.status in {"completed", "terminated", "rejected", "withdrawn", "closed"}
            report.check(conversation.archived == terminal, f"分支归档不符：{spec.key}")
            messages = list((await session.exec(
                select(Message).where(Message.conversation_id == conversation.id).order_by(col(Message.id))
            )).all())
            report.check(len(messages) == len(spec.messages), f"交易消息数量不符：{spec.key}")
            for index, message_spec in enumerate(spec.messages):
                if index >= len(messages):
                    continue
                message = messages[index]
                report.check(message.content == message_spec.content, f"交易消息内容不符：{spec.key}/{index}")
                expected_sender = _id(data, f"account_{message_spec.sender}") if message_spec.sender else None
                report.check(message.sender_id == expected_sender, f"交易消息发送者不符：{spec.key}/{index}")
            for user_key, count in spec.reads:
                row = (await session.exec(
                    select(ConversationRead).where(
                        ConversationRead.conversation_id == conversation.id,
                        ConversationRead.user_id == _id(data, f"account_{user_key}"),
                    )
                )).first()
                report.check(row is not None and row.last_read_message_id == messages[count - 1].id,
                             f"交易分支已读不符：{spec.key}/{user_key}")
        if spec.case is not None:
            case = await session.get(__import__("app.models", fromlist=["DisposalCase"]).DisposalCase, _id(data, spec.case.key))
            report.check(case is not None and case.trade_id == trade.id, f"交易事项关联不符：{spec.key}")
            if case is not None:
                await _verify_case_messages(session, data, case, spec.case, report, spec.key)
    report.counts["trades"] = len(catalog.TRADES)


async def _verify_reports(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import DisposalCase, Report, ReportSupplement

    for spec in catalog.REPORTS:
        item = await session.get(Report, _id(data, spec.key))
        report.check(item is not None, f"举报缺失：{spec.key}")
        if item is None:
            continue
        report.check(item.status == spec.status, f"举报状态不符：{spec.key}")
        report.check(item.result_confirmed == spec.result_confirmed, f"举报结果确认标记不符：{spec.key}")
        report.check(item.public_result == spec.public_result, f"举报公开结果不符：{spec.key}")
        report.check(item.result_reason == spec.result_reason, f"举报结论原因不符：{spec.key}")
        report.check((item.closed_at is not None) == (spec.closed_days_ago is not None), f"举报结案时间不符：{spec.key}")
        if spec.status == "unfounded":
            report.check(item.public_result is None, f"不予处理不应公开结果：{spec.key}")
        supplements = list((await session.exec(
            select(ReportSupplement).where(ReportSupplement.report_id == item.id).order_by(col(ReportSupplement.id))
        )).all())
        report.check(len(supplements) == len(spec.supplements), f"举报补充数量不符：{spec.key}")
        for index, supplement_spec in enumerate(spec.supplements):
            if index < len(supplements):
                report.check(supplements[index].content == supplement_spec.content, f"举报补充内容不符：{spec.key}")
                report.check(len(supplements[index].evidence_keys) == len(supplement_spec.evidence),
                             f"举报补充证据数量不符：{spec.key}")
        if spec.case is not None:
            case = await session.get(DisposalCase, _id(data, spec.case.key))
            report.check(case is not None and case.report_id == item.id, f"举报事项关联不符：{spec.key}")
            if case is not None:
                report.check(case.status == spec.case.status, f"举报事项状态不符：{spec.key}")
                report.check((case.claimed_by_id is not None) == (spec.case.claimed_by is not None),
                             f"举报事项认领不符：{spec.key}")
                report.check((case.disposed_at is not None) == (spec.case.disposed_days_ago is not None),
                             f"举报事项处置时间不符：{spec.key}")
                await _verify_case_messages(session, data, case, spec.case, report, spec.key)
        if spec.target_type == "product":
            product = await session.get(__import__("app.models", fromlist=["Product"]).Product, item.target_id)
            report.check(product is not None, f"举报商品目标缺失：{spec.key}")
            if spec.status == "handled" and spec.key == "report_product_handled" and product is not None:
                report.check(product.display_restricted, f"处置后商品未受限：{spec.key}")
                report.check(product.display_restricted_case_id == _id(data, spec.case.key), f"受限事项关联不符：{spec.key}")
        elif spec.target_type == "comment":
            comment = await session.get(__import__("app.models", fromlist=["Comment"]).Comment, item.target_id)
            report.check(comment is not None, f"举报评论目标缺失：{spec.key}")
            report.check(comment is not None and comment.deleted_at is not None, f"举报评论未移除：{spec.key}")
        elif spec.target_type == "review":
            review = await session.get(__import__("app.models", fromlist=["TradeReview"]).TradeReview, item.target_id)
            report.check(review is not None, f"举报评价目标缺失：{spec.key}")
            report.check(review is not None and review.deleted_at is not None, f"举报评价未移除：{spec.key}")
        elif spec.target_type == "user":
            user = await session.get(__import__("app.models", fromlist=["User"]).User, item.target_id)
            report.check(user is not None, f"举报用户目标缺失：{spec.key}")
    report.counts["reports"] = len(catalog.REPORTS)


async def _verify_restrictions(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.user import AccountRestriction, User

    for spec in catalog.RESTRICTIONS:
        restriction = await session.get(AccountRestriction, _id(data, spec.key))
        report.check(restriction is not None, f"限制缺失：{spec.key}")
        if restriction is None:
            continue
        report.check(restriction.user_id == _id(data, f"account_{spec.user}"), f"限制用户不符：{spec.key}")
        report.check(restriction.status == spec.status, f"限制状态不符：{spec.key}")
        report.check(restriction.case_id == _id(data, spec.case), f"限制事项关联不符：{spec.key}")
        if spec.status == "lifted":
            report.check(restriction.lifted_at is not None and bool(restriction.lift_reason),
                         f"解除限制缺少依据：{spec.key}")
        else:
            user = await session.get(User, restriction.user_id)
            report.check(user is not None and user.status == "banned", f"生效限制对应用户未封禁：{spec.key}")
    report.counts["restrictions"] = len(catalog.RESTRICTIONS)


async def _verify_notifications(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import Notification
    from app.models.user import User

    for spec in catalog.NOTIFICATIONS:
        item = await session.get(Notification, _id(data, spec.key))
        report.check(item is not None, f"通知缺失：{spec.key}")
        if item is None:
            continue
        report.check(item.user_id == _id(data, f"account_{spec.user}"), f"通知接收人不符：{spec.key}")
        report.check(item.is_read == spec.is_read, f"通知已读状态不符：{spec.key}")
        report.check((item.read_at is not None) == spec.is_read, f"通知已读时间不符：{spec.key}")
        report.check(item.type == spec.type, f"通知类型不符：{spec.key}")
        if spec.link:
            report.check(item.link_id == _resolve_link(data, spec.link, spec.link_type),
                         f"通知关联不符：{spec.key}")
        user = await session.get(User, item.user_id)
        report.check(user is not None and user.role != "admin", f"管理员收到个人通知：{spec.key}")
    report.counts["notifications"] = len(catalog.NOTIFICATIONS)


def _resolve_link(data: dict, key: str, link_type: str | None) -> int:
    if link_type == "conversation":
        return _id(data, key)
    return _id(data, key)


async def _verify_conversations(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.im import Conversation, ConversationRead, Message

    for spec in catalog.NORMAL_CONVERSATIONS:
        conversation = await session.get(Conversation, _id(data, spec.key))
        report.check(conversation is not None, f"普通会话缺失：{spec.key}")
        if conversation is None:
            continue
        report.check(conversation.type == "normal", f"普通会话类型不符：{spec.key}")
        report.check(conversation.user_low_id == min(_id(data, f"account_{u}") for u in spec.users),
                     f"普通会话成员不符：{spec.key}")
        messages = list((await session.exec(
            select(Message).where(Message.conversation_id == conversation.id).order_by(col(Message.id))
        )).all())
        report.check(len(messages) == len(spec.messages), f"普通会话消息数量不符：{spec.key}")
        for index, message_spec in enumerate(spec.messages):
            if index < len(messages):
                report.check(messages[index].content == message_spec.content, f"普通会话消息不符：{spec.key}/{index}")
        for user_key, count in spec.reads:
            row = (await session.exec(
                select(ConversationRead).where(ConversationRead.conversation_id == conversation.id,
                                               ConversationRead.user_id == _id(data, f"account_{user_key}"))
            )).first()
            report.check(row is not None and row.last_read_message_id == messages[count - 1].id,
                         f"普通会话已读不符：{spec.key}/{user_key}")
    report.counts["conversations"] = len(catalog.NORMAL_CONVERSATIONS)


async def _verify_avatars(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import DisposalCase
    from app.models.user import User
    from app.models.stored_object import StoredObject

    for spec in catalog.AVATARS:
        user = await session.get(User, _id(data, f"account_{spec.user}"))
        report.check(user is not None and user.avatar_pending_key is not None, f"头像待审键缺失：{spec.user}")
        if user is not None:
            report.check(user.avatar_review_status == "pending", f"头像审核状态不符：{spec.user}")
        case = await session.get(DisposalCase, _id(data, spec.case.key))
        report.check(case is not None and case.avatar_key == (user.avatar_pending_key if user else None),
                     f"头像事项关联不符：{spec.user}")
        if user is not None and user.avatar_pending_key:
            obj = await session.get(StoredObject, user.avatar_pending_key)
            report.check(obj is not None and obj.state == "committed", f"头像对象未提交：{spec.user}")


async def _verify_cross_invariants(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import DisposalCase, Report
    from app.models.product import Product
    from app.models.trade import Trade
    from app.models.user import AccountRestriction, User

    restricted_without_case = (await session.exec(
        select(Product.id).where(Product.display_restricted.is_(True), Product.display_restricted_case_id.is_(None))
    )).all()
    report.check(not restricted_without_case, "受限商品缺少关联事项")
    active_bans = (await session.exec(
        select(AccountRestriction.user_id).where(AccountRestriction.status == "active")
    )).all()
    for user_id in set(active_bans):
        user = await session.get(User, user_id)
        report.check(user is not None and user.status == "banned", "生效封禁对应用户未封禁")
    for user in (await session.exec(select(User).where(User.status == "banned"))).all():
        active = (await session.exec(
            select(AccountRestriction.id).where(AccountRestriction.user_id == user.id,
                                                AccountRestriction.status == "active")
        )).first()
        report.check(active is not None, f"封禁用户缺少生效限制：{user.display_name}")
    locking = (await session.exec(
        select(Trade.product_id).where(Trade.status.in_(["in_progress", "disputed", "abnormal"]))
    )).all()
    report.check(len(locking) == len(set(locking)), "同一商品存在多笔锁单交易")
    for product in (await session.exec(select(Product).where(Product.status == "in_transaction"))).all():
        report.check(product.id in set(locking), "交易中商品缺少锁单交易")
    for report_row in (await session.exec(select(Report).where(Report.status.in_(["handled", "unfounded"])))).all():
        report.check(report_row.result_confirmed and report_row.closed_at is not None,
                     f"已结举报缺少确认或结案时间：{report_row.id}")
        report.check(report_row.public_result is not None if report_row.status == "handled" else report_row.public_result is None,
                     f"举报公开结果与状态不符：{report_row.id}")
    for case in (await session.exec(select(DisposalCase))).all():
        if case.status == "disposed":
            report.check(bool(case.conclusion) and case.disposed_at is not None, f"已处置事项缺结论：{case.id}")
        if case.status == "processing":
            report.check(case.claimed_by_id is not None, f"处理中事项未认领：{case.id}")
        if case.status == "pending":
            report.check(case.claimed_by_id is None, f"待处理事项已认领：{case.id}")


async def _verify_standalone_cases(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import DisposalCase

    for spec in catalog.CASES:
        case = await session.get(DisposalCase, _id(data, spec.key))
        report.check(case is not None, f"独立事项缺失：{spec.key}")
        if case is None:
            continue
        report.check(case.status == spec.status, f"独立事项状态不符：{spec.key}")
        report.check((case.claimed_by_id is not None) == (spec.claimed_by is not None), f"独立事项认领不符：{spec.key}")
        report.check((case.disposed_at is not None) == (spec.disposed_days_ago is not None), f"独立事项处置时间不符：{spec.key}")
        await _verify_case_messages(session, data, case, spec, report, spec.key)
    for avatar in catalog.AVATARS:
        case = await session.get(DisposalCase, _id(data, avatar.case.key))
        report.check(case is not None, f"头像事项缺失：{avatar.user}")
        if case is not None:
            await _verify_case_messages(session, data, case, avatar.case, report, avatar.case.key)


async def _verify_api_visibility(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    """直接调用只读接口函数，核验公开/限制/私有范围（不启动服务）。"""
    from fastapi import HTTPException

    from app.api.v1.admin.cases import case_detail
    from app.api.v1.products import detail, restriction_result, search
    from app.api.v1.trades import trade_detail
    from app.models.user import User

    buyer = await session.get(User, _id(data, "account_buyer"))
    admin = await session.get(User, _id(data, "account_admin"))
    admin2 = await session.get(User, _id(data, "account_admin2"))
    outsider = await session.get(User, _id(data, "account_outsider"))
    if not all((buyer, admin, admin2, outsider)):
        report.check(False, "只读 API 核验缺少账号")
        return
    result = await search(session, buyer, keyword="山地车", category_ids=None, category_names=None,
                          price_min_cents=None, price_max_cents=None, page=1, page_size=20)
    report.check(any(item.id == _id(data, "product_bike") for item in result.items), "公开搜索未返回山地车")
    restricted_id = _id(data, "product_powerbank")
    report.check(all(item.id != restricted_id for item in result.items), "受限商品出现在公开搜索")
    try:
        await detail(restricted_id, buyer, session)
        report.check(False, "受限商品详情未被拒绝")
    except HTTPException as exc:
        report.check(exc.status_code == 404, "受限商品详情应 404")
    public = await restriction_result(restricted_id, buyer, session)
    report.check(public == {"public_result": "经核查，商品存在电池鼓包安全隐患，已停止公开访问并提醒卖方妥善处理"},
                 "匿名处置结果不符")
    try:
        await trade_detail(_id(data, "trade_frozen"), outsider, session)
        report.check(False, "非交易方读取交易详情未被拒绝")
    except HTTPException as exc:
        report.check(exc.status_code == 404, "非交易方交易详情应 404")
    try:
        await case_detail(_id(data, "case_review_product_keyboard"), admin2, session)
        report.check(False, "非认领管理员读取事项未被拒绝")
    except HTTPException as exc:
        report.check(exc.status_code == 403, "非认领管理员事项详情应 403")
    report.counts["api_visibility"] = 6


async def verify(
    session: AsyncSession,
    storage,
    data: dict,
    *,
    verify_api: bool = True,
) -> VerificationReport:
    """执行全部只读核验；调用方负责 manifest 版本/目标/目录摘要检查。"""
    report = VerificationReport()
    if not data.get("complete"):
        report.errors.append("manifest 未完成")
        return report
    from app.devtools.demo_scenarios.checks import validate_catalog

    summary = validate_catalog()
    report.check(data.get("catalog_signature") == catalog.catalog_signature(), "manifest 目录摘要不匹配")
    report.check(set(map(str, data.get("scenarios", []))) == {s.key for s in catalog.SCENARIOS},
                 "manifest 场景覆盖与目录不一致")
    report.check(data.get("object_kinds") == {key: value.get("kind") for key, value in data.get("objects", {}).items()},
                 "manifest object_kinds 与 objects 不一致")
    await _verify_accounts(session, data, report)
    await _verify_objects(session, data, report)
    await _verify_files(session, storage, data, report)
    await _verify_products(session, data, report)
    await _verify_trades(session, data, report)
    await _verify_reports(session, data, report)
    await _verify_restrictions(session, data, report)
    await _verify_notifications(session, data, report)
    await _verify_conversations(session, data, report)
    await _verify_avatars(session, data, report)
    await _verify_standalone_cases(session, data, report)
    await _verify_cross_invariants(session, data, report)
    if verify_api:
        await _verify_api_visibility(session, data, report)
    report.counts["scenarios"] = summary.scenarios
    report.counts["checks"] = report.checks
    return report

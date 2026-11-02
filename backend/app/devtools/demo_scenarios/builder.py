"""把共享场景目录物化为持久演示数据。

只由 ``demo_seed`` 调用。构建器不自行判断“是否已初始化”，也不读取秘密；
恢复、目标绑定、文件登记与上传由 CLI 层负责。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, overload

from sqlmodel.ext.asyncio.session import AsyncSession

from app.devtools.demo_scenarios import catalog
from app.devtools.demo_scenarios.checks import (
    agreement_key,
    confirmation_key,
    conversation_key,
    edit_key,
    favorite_key,
    message_key,
    product_review_case_key,
    product_review_key,
    tag_application_key,
    trade_review_key,
)
from app.models.category import Category, CategoryAlias
from app.models.governance import (
    DisposalCase,
    DisposalMessage,
    Notification,
    Report,
    ReportSupplement,
)
from app.models.im import Conversation, ConversationRead, Message
from app.models.product import (
    Comment,
    Favorite,
    Product,
    ProductEditHistory,
    ProductImage,
    ProductTag,
    ProductTagApplication,
    ProhibitedItem,
    ReviewRecord,
)
from app.models.stored_object import StoredObject
from app.models.trade import (
    CompletionConfirmation,
    Trade,
    TradeAgreement,
    TradeReview,
    TradeTransition,
)
from app.models.user import AccountRestriction, User

ASSETS = Path(__file__).resolve().parent / "assets"

EnsureFile = Callable[[str, str, str, str, bytes], dict]


def _asset_bytes(name: str) -> bytes:
    return (ASSETS / name).read_bytes()


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class _Builder:
    def __init__(
        self,
        session: AsyncSession,
        *,
        data: dict,
        settings: Any,
        ensure_file: EnsureFile,
        now: datetime,
    ) -> None:
        self.session = session
        self.data = data
        self.settings = settings
        self.ensure_file = ensure_file
        self.now = now
        self.objects: dict[str, dict] = {}
        self.users: dict[str, User] = {}
        self.categories: dict[str, Category] = {}
        self.products: dict[str, Product] = {}
        self.trades: dict[str, Trade] = {}
        self.cases: dict[str, DisposalCase] = {}
        self.reports: dict[str, Report] = {}
        self.comments: dict[str, Comment] = {}
        self.reviews: dict[str, TradeReview] = {}
        self.conversations: dict[str, Conversation] = {}
        self.messages: dict[str, Message] = {}

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    @overload
    def at(self, days_ago: float) -> datetime: ...
    @overload
    def at(self, days_ago: None) -> None: ...
    @overload
    def at(self, days_ago: float | None) -> datetime | None: ...
    def at(self, days_ago: float | None) -> datetime | None:
        if days_ago is None:
            return None
        return self.now - timedelta(days=float(days_ago))

    def add(self, key: str, obj: Any, kind: str) -> Any:
        self.session.add(obj)
        return obj

    async def flush_add(self, key: str, obj: Any, kind: str) -> Any:
        self.session.add(obj)
        await self.session.flush()
        if key in self.objects:
            raise ValueError(f"演示对象 key 重复：{key}")
        self.objects[key] = {"id": int(getattr(obj, "id")), "kind": kind}
        return obj

    def user(self, key: str) -> User:
        return self.users[key]

    def category(self, key: str) -> Category:
        return self.categories[key]

    def product_spec(self, key: str):
        for spec in catalog.PRODUCTS:
            if spec.key == key:
                return spec
        raise KeyError(key)

    def resolve_id(self, key: str) -> int:
        if key.startswith("account_"):
            return self.users[key.removeprefix("account_")].id
        if key not in self.objects:
            raise ValueError(f"演示对象尚未创建：{key}")
        return int(self.objects[key]["id"])

    # ------------------------------------------------------------------
    # 账号、分类、禁发范围
    # ------------------------------------------------------------------
    async def build_accounts(self) -> None:
        from app.core.security import hash_password

        for spec in catalog.ACCOUNTS:
            account = self.data["accounts"][spec.key]
            user = User(
                email=account["email"],
                password_hash=hash_password(account["password"]),
                display_name=spec.display_name,
                role=spec.role,
                created_at=self.at(90),
            )
            await self.flush_add(f"account_{spec.key}", user, "account")
            self.users[spec.key] = user
            account["id"] = user.id
            account["display_name"] = spec.display_name
            account["role"] = spec.role

    async def build_categories(self) -> None:
        for spec in catalog.CATEGORIES:
            category = Category(
                name=spec.name,
                status="disabled" if spec.disabled_days_ago else "active",
                deleted_at=self.at(spec.deleted_days_ago),
                created_by_id=self.user(spec.created_by).id,
                created_at=self.at(spec.days_ago),
                updated_at=self.at(spec.disabled_days_ago or spec.days_ago),
            )
            await self.flush_add(spec.key, category, "category")
            self.categories[spec.key] = category
            for alias_spec in spec.aliases:
                alias = CategoryAlias(
                    category_id=category.id,
                    name=alias_spec.name,
                    created_by_id=self.user(spec.created_by).id,
                    created_at=self.at(alias_spec.days_ago),
                    removed_at=self.at(alias_spec.removed_days_ago),
                )
                await self.flush_add(alias_spec.key, alias, "category_alias")

        for spec in catalog.PROHIBITED:
            session = self.session
            session.add(ProhibitedItem(
                group_name=spec.group_name,
                content=spec.content,
                sort=spec.sort,
                updated_by_id=self.user(spec.updated_by).id,
                updated_at=self.at(spec.days_ago),
            ))

    # ------------------------------------------------------------------
    # 商品
    # ------------------------------------------------------------------
    async def _review_case(self, product: Product, spec, *, case_key: str) -> DisposalCase:
        if spec.result == "pending":
            case = DisposalCase(
                case_type="product_review",
                product_id=product.id,
                subject_user_id=product.seller_id,
                title=f"商品审核：{product.title}",
                status="processing" if spec.claimed_by else "pending",
                claimed_by_id=self.user(spec.claimed_by).id if spec.claimed_by else None,
                claimed_at=self.at(spec.claimed_days_ago) if spec.claimed_by else None,
                created_at=self.at(spec.days_ago),
            )
        else:
            conclusion = {
                "approved": "审核通过",
                "rejected": "审核不通过",
                "withdrawn": "卖方撤回审核",
            }[spec.result]
            case = DisposalCase(
                case_type="product_review",
                product_id=product.id,
                subject_user_id=product.seller_id,
                title=f"商品审核：{product.title}",
                status="disposed",
                claimed_by_id=self.user(spec.reviewer).id if spec.reviewer else None,
                claimed_at=self.at(spec.days_ago) if spec.reviewer else None,
                conclusion=conclusion,
                conclusion_reason=spec.reason,
                basis="商品审核",
                disposed_at=self.at(spec.days_ago),
                created_at=self.at(spec.days_ago),
            )
        await self.flush_add(case_key, case, "disposal_case")
        self.cases[case_key] = case
        return case

    async def build_products(self) -> None:
        for spec in catalog.PRODUCTS:
            reviews = spec.reviews
            if not reviews and spec.status in {"listed", "in_transaction", "delisted"}:
                reviews = (catalog.ReviewSpec("approved", spec.listed_days_ago or spec.created_days_ago, reviewer="admin"),)
            product = Product(
                seller_id=self.user(spec.seller).id,
                title=spec.title,
                description=spec.description,
                price_cents=spec.price_cents,
                status=spec.status,
                reject_reason=spec.reject_reason,
                display_restricted=spec.display_restricted,
                display_restricted_reason=None,
                display_restricted_at=None,
                display_restricted_case_id=None,
                created_at=self.at(spec.created_days_ago),
                updated_at=self.at(spec.created_days_ago),
                listed_at=None,
                delisted_at=self.at(spec.delisted_days_ago),
            )
            approved = [review for review in reviews if review.result == "approved"]
            if approved:
                product.listed_at = self.at(spec.listed_days_ago or approved[0].days_ago)
            await self.flush_add(spec.key, product, "product")
            self.products[spec.key] = product

            await self._product_image(product, spec)
            for tag_key in spec.all_tags:
                self.session.add(ProductTag(product_id=product.id, category_id=self.category(tag_key).id))

            for index, review_spec in enumerate(reviews):
                if index < len(spec.reviews):
                    case_key = product_review_case_key(spec, index)
                else:
                    case_key = f"case_review_{spec.key.removeprefix('product_')}_auto"
                case = await self._review_case(product, review_spec, case_key=case_key)
                review_key = (
                    product_review_key(spec, index)
                    if index < len(spec.reviews)
                    else f"review_{spec.key.removeprefix('product_')}_auto"
                )
                review = ReviewRecord(
                    product_id=product.id,
                    content_json={
                        "title": product.title,
                        "description": product.description,
                        "price_cents": product.price_cents,
                    },
                    result=review_spec.result,
                    reviewer_id=self.user(review_spec.reviewer).id if review_spec.reviewer else None,
                    reviewed_at=self.at(review_spec.days_ago) if review_spec.result != "pending" else None,
                    reason=review_spec.reason,
                    case_id=case.id,
                    created_at=self.at(review_spec.days_ago),
                )
                await self.flush_add(review_key, review, "review_record")

            for index, app_spec in enumerate(spec.tag_apps):
                app = ProductTagApplication(
                    product_id=product.id,
                    requested_name=app_spec.requested_name,
                    status=app_spec.status,
                    resolved_category_id=self.category(app_spec.resolved_category).id if app_spec.resolved_category else None,
                    decision_reason=app_spec.reason,
                    decided_at=self.at(app_spec.decided_days_ago),
                    created_at=self.at(app_spec.days_ago),
                )
                await self.flush_add(tag_application_key(spec, index), app, "tag_application")

            for index, edit_spec in enumerate(spec.edits):
                history = ProductEditHistory(
                    product_id=product.id,
                    editor_id=self.user(edit_spec.editor).id,
                    edit_type=edit_spec.edit_type,
                    before_json=edit_spec.before,
                    after_json=edit_spec.after,
                    reason=edit_spec.reason,
                    created_at=self.at(edit_spec.days_ago),
                )
                await self.flush_add(edit_key(spec, index), history, "edit_history")

            for comment_spec in spec.comments:
                parent = self.comments.get(comment_spec.reply_to) if comment_spec.reply_to else None
                if comment_spec.reply_to and parent is None:
                    raise ValueError(f"评论回复目标不存在：{comment_spec.key}")
                comment = Comment(
                    product_id=product.id,
                    author_id=self.user(comment_spec.author).id,
                    content=comment_spec.content,
                    reply_to_comment_id=parent.id if parent else None,
                    reply_to_user_id=parent.author_id if parent else None,
                    deleted_at=self.at(comment_spec.deleted_days_ago),
                    deleted_by_id=self.user(comment_spec.deleted_by).id if comment_spec.deleted_by else None,
                    delete_reason=comment_spec.delete_reason,
                    created_at=self.at(comment_spec.days_ago),
                )
                await self.flush_add(comment_spec.key, comment, "comment")
                self.comments[comment_spec.key] = comment

            for user_key in spec.favorites:
                favorite = Favorite(
                    user_id=self.user(user_key).id,
                    product_id=product.id,
                    created_at=self.at(spec.created_days_ago - 0.5),
                )
                await self.flush_add(favorite_key(user_key, spec), favorite, "favorite")

    async def _product_image(self, product: Product, spec) -> None:
        slug = spec.image_slug or spec.key
        content = _asset_bytes(spec.asset)
        entry = self.ensure_file(slug, "product", spec.asset, spec.asset, content)
        self.session.add(ProductImage(product_id=product.id, file_key=entry["key"], sort=0))
        self.session.add(StoredObject(
            key=entry["key"], namespace="product", bucket_role="media",
            owner_id=product.seller_id, content_type="image/jpeg", size_bytes=len(content),
            state="committed", ref_type="product", ref_id=product.id,
            committed_at=self.at(spec.created_days_ago),
        ))

    # ------------------------------------------------------------------
    # 交易
    # ------------------------------------------------------------------
    def _final_transition(self, spec, product: Product) -> catalog.TransitionSpec | None:
        buyer_key = spec.buyer
        seller_key = next(key for key, user in self.users.items() if user.id == product.seller_id)
        at = spec.finished_days_ago
        if spec.status == "completed":
            actor_key = spec.finished_by or buyer_key
            role = "admin" if spec.finished_by else "buyer"
            return catalog.TransitionSpec("in_progress", "completed", spec.finished_trigger or "both_confirmed",
                                          actor_key, role, at or 0, spec.finished_reason or "双方确认完成",
                                          spec.finished_case)
        if spec.status == "terminated":
            trigger = spec.finished_trigger or ("buyer_cancel" if spec.current_round is None else "cancel_agreed")
            actor_key = spec.finished_by or buyer_key
            role = "admin" if spec.finished_by else "buyer"
            return catalog.TransitionSpec("in_progress", "terminated", trigger,
                                          actor_key, role, at or 0,
                                          spec.finished_reason or "交易终止", spec.finished_case)
        if spec.status == "rejected":
            return catalog.TransitionSpec("pending_acceptance", "rejected", "request_rejected",
                                          seller_key, "seller", at or 0, spec.close_reason, None)
        if spec.status == "withdrawn":
            return catalog.TransitionSpec("pending_acceptance", "withdrawn", "request_withdrawn",
                                          buyer_key, "buyer", at or 0, spec.close_reason, None)
        if spec.status == "closed":
            return catalog.TransitionSpec("pending_acceptance", "closed", "request_closed_by_lock",
                                          None, "system", at or 0, spec.close_reason, None)
        if spec.status == "disputed":
            return catalog.TransitionSpec("in_progress", "disputed", "dispute_created",
                                          buyer_key, "buyer", spec.case.created_days_ago if spec.case else (at or 0),
                                          "交易进入争议", None)
        return None

    async def build_trades(self) -> None:
        for spec in catalog.TRADES:
            if spec.case is not None and spec.case.key not in self.cases:
                await self._case(spec.case)
            product = self.products[spec.product]
            seller = self.users[next(key for key, user in self.users.items() if user.id == product.seller_id)]
            buyer = self.user(spec.buyer)
            trade = Trade(
                product_id=product.id,
                buyer_id=buyer.id,
                seller_id=seller.id,
                status=spec.status,
                request_note=spec.request_note,
                close_reason=spec.close_reason,
                created_at=self.at(spec.created_days_ago),
                accepted_at=self.at(spec.accepted_days_ago),
                finished_at=self.at(spec.finished_days_ago) if spec.status in {"completed", "terminated"} else None,
                cancel_requested_by_id=self.user(spec.cancel_requested_by).id if spec.cancel_requested_by else None,
                cancel_requested_at=self.at(spec.cancel_requested_days_ago),
                resolution_confirmed_by_id=self.user(spec.resolution_confirmed_by).id if spec.resolution_confirmed_by else None,
                resolution_confirmed_at=self.at(spec.resolution_confirmed_days_ago),
                frozen=spec.frozen,
                frozen_reason=spec.frozen_reason,
                frozen_at=self.at(spec.frozen_days_ago) if spec.frozen else None,
                frozen_by_id=self.user(spec.frozen_by).id if spec.frozen_by else None,
            )
            if spec.accepted_days_ago is not None:
                trade.product_snapshot_json = {
                    "product_id": product.id,
                    "title": product.title,
                    "description": product.description,
                    "price_cents": product.price_cents,
                    "images": [self.data["files"][self.product_spec(spec.product).image_slug or spec.product]["key"]],
                    "tags": [self.category(tag_key).name for tag_key in self.product_spec(spec.product).all_tags],
                    "captured_at": self.at(spec.accepted_days_ago).isoformat(),
                }
            await self.flush_add(spec.key, trade, "trade")
            self.trades[spec.key] = trade
            if spec.case is not None:
                self.cases[spec.case.key].trade_id = trade.id

            for agreement_spec in spec.agreements:
                agreement = TradeAgreement(
                    trade_id=trade.id,
                    round_no=agreement_spec.round_no,
                    proposer_id=self.user(agreement_spec.proposer).id,
                    delivery_time=agreement_spec.delivery_time,
                    delivery_location=agreement_spec.delivery_location,
                    delivery_method=agreement_spec.delivery_method,
                    amount_cents=agreement_spec.amount_cents,
                    payment_method=agreement_spec.payment_method,
                    payment_timing=agreement_spec.payment_timing,
                    status=agreement_spec.status,
                    proposed_at=self.at(agreement_spec.proposed_days_ago),
                    decided_at=self.at(agreement_spec.decided_days_ago),
                )
                await self.flush_add(agreement_key(spec, agreement_spec.round_no), agreement, "agreement")
                if spec.current_round == agreement_spec.round_no:
                    trade.current_agreement_id = agreement.id

            for confirmation_spec in spec.confirmations:
                confirmation = CompletionConfirmation(
                    trade_id=trade.id,
                    confirmer_id=self.user(confirmation_spec.confirmer).id,
                    note=confirmation_spec.note,
                    is_current=confirmation_spec.is_current,
                    confirmed_at=self.at(confirmation_spec.days_ago),
                )
                await self.flush_add(confirmation_key(spec, confirmation_spec), confirmation, "confirmation")

            if spec.frozen:
                frozen_at = self.at(spec.frozen_days_ago)
                trade.frozen_case_id = self.resolve_id(spec.frozen_case) if spec.frozen_case else None
                if spec.confirm_wait_started_days_ago is not None and frozen_at is not None:
                    started = self.at(spec.confirm_wait_started_days_ago)
                    timeout = int(self.settings.trade_confirm_timeout_days) * 24 * 60 * 60
                    elapsed = (frozen_at - started).total_seconds()
                    trade.confirm_wait_started_at = started
                    trade.confirm_wait_paused_at = frozen_at
                    trade.confirm_wait_remaining_seconds = max(0, int(timeout - elapsed))
            elif spec.confirm_wait_started_days_ago is not None:
                trade.confirm_wait_started_at = self.at(spec.confirm_wait_started_days_ago)
                trade.confirm_wait_paused_at = None
                trade.confirm_wait_remaining_seconds = None

            await self._trade_transitions(trade, spec, product, seller, buyer)
            await self._trade_conversation(trade, spec)
            for review_spec in spec.reviews:
                review = TradeReview(
                    trade_id=trade.id,
                    reviewer_id=self.user(review_spec.reviewer).id,
                    reviewee_id=seller.id if review_spec.reviewer == spec.buyer else buyer.id,
                    rating=review_spec.rating,
                    content=review_spec.content,
                    deleted_at=self.at(review_spec.deleted_days_ago),
                    deleted_by_id=self.user(review_spec.deleted_by).id if review_spec.deleted_by else None,
                    delete_reason=review_spec.delete_reason,
                    created_at=self.at(review_spec.days_ago),
                )
                await self.flush_add(trade_review_key(spec, review_spec), review, "trade_review")
                self.reviews[trade_review_key(spec, review_spec)] = review

            self._apply_trade_final_effects(trade, spec, product)

    def _apply_trade_final_effects(self, trade: Trade, spec, product: Product) -> None:
        # 已结束交易：商品默认下架；结束同时解本笔冻结。
        if spec.status in {"completed", "terminated"}:
            trade.frozen = False
            trade.frozen_at = None
            trade.frozen_reason = None
            trade.frozen_by_id = None
            trade.frozen_case_id = None
            if product.status == "in_transaction":
                product.status = "delisted"
                product.delisted_at = self.at(spec.finished_days_ago)
        if spec.status in {"rejected", "withdrawn", "closed"}:
            if product.status == "in_transaction":
                product.status = "delisted"

    async def _trade_transitions(self, trade: Trade, spec, product: Product, seller: User, buyer: User) -> None:
        transitions: list[catalog.TransitionSpec] = [
            catalog.TransitionSpec(None, "pending_acceptance", "request_created", spec.buyer, "buyer", spec.created_days_ago, spec.request_note),
        ]
        if spec.accepted_days_ago is not None:
            transitions.append(catalog.TransitionSpec(
                "pending_acceptance", "in_progress", "request_accepted",
                next(key for key, user in self.users.items() if user.id == seller.id), "seller",
                spec.accepted_days_ago,
            ))
        transitions.extend(spec.history)
        final = self._final_transition(spec, product)
        if final is not None:
            reached = {transition.to_status for transition in transitions}
            if final.to_status not in reached:
                transitions.append(final)
        for transition in transitions:
            actor_id = self.user(transition.actor).id if transition.actor else None
            self.session.add(TradeTransition(
                trade_id=trade.id,
                from_status=transition.from_status,
                to_status=transition.to_status,
                actor_id=actor_id,
                actor_role=transition.actor_role,
                trigger=transition.trigger,
                reason=transition.reason,
                basis_case_id=self.resolve_id(transition.basis_case) if transition.basis_case else None,
                created_at=self.at(transition.days_ago),
            ))

    async def _trade_conversation(self, trade: Trade, spec) -> None:
        low, high = sorted((trade.buyer_id, trade.seller_id))
        archived = spec.status in {"completed", "terminated", "rejected", "withdrawn", "closed"}
        conversation = Conversation(
            type="trade",
            trade_id=trade.id,
            user_low_id=low,
            user_high_id=high,
            archived=archived,
            archived_at=self.at(spec.finished_days_ago) if archived else None,
            created_at=self.at(spec.created_days_ago),
        )
        await self.flush_add(conversation_key(spec), conversation, "conversation")
        self.conversations[conversation_key(spec)] = conversation
        message_ids: list[int] = []
        for index, message_spec in enumerate(spec.messages, start=1):
            message = Message(
                conversation_id=conversation.id,
                sender_id=self.user(message_spec.sender).id if message_spec.sender else None,
                kind="system" if message_spec.sender is None else "text",
                content=message_spec.content,
                created_at=self.at(message_spec.days_ago),
            )
            key = message_key(spec.key, index)
            await self.flush_add(key, message, "message")
            self.messages[key] = message
            message_ids.append(message.id)
        for user_key, count in spec.reads:
            if count <= 0 or count > len(message_ids):
                raise ValueError(f"{spec.key} 已读位置越界")
            self.session.add(ConversationRead(
                conversation_id=conversation.id,
                user_id=self.user(user_key).id,
                last_read_message_id=message_ids[count - 1],
                updated_at=self.at(spec.messages[count - 1].days_ago),
            ))

    # ------------------------------------------------------------------
    # 举报、事项与限制
    # ------------------------------------------------------------------
    async def _evidence(self, spec: catalog.EvidenceSpec, *, owner_id: int, ref_type: str, ref_id: int, days_ago: float) -> str:
        content = _asset_bytes(spec.asset)
        entry = self.ensure_file(spec.slug, "report", spec.asset, spec.asset, content)
        self.session.add(StoredObject(
            key=entry["key"], namespace="report", bucket_role="evidence",
            owner_id=owner_id, content_type="image/jpeg", size_bytes=len(content),
            state="committed", ref_type=ref_type, ref_id=ref_id,
            committed_at=self.at(days_ago),
        ))
        return entry["key"]

    async def _case(self, spec: catalog.CaseSpec, *, subject_key: str | None = None, **links: int | None) -> DisposalCase:
        subject = subject_key or spec.subject
        case = DisposalCase(
            case_type=spec.case_type,
            status=spec.status,
            claimed_by_id=self.user(spec.claimed_by).id if spec.claimed_by else None,
            claimed_at=self.at(spec.claimed_days_ago),
            product_id=links.get("product_id"),
            report_id=links.get("report_id"),
            trade_id=links.get("trade_id"),
            subject_user_id=self.user(subject).id if subject else None,
            title=spec.title,
            conclusion=spec.conclusion,
            conclusion_reason=spec.conclusion_reason,
            basis=spec.basis,
            disposed_at=self.at(spec.disposed_days_ago),
            created_at=self.at(spec.created_days_ago),
        )
        await self.flush_add(spec.key, case, "disposal_case")
        self.cases[spec.key] = case
        for message_spec in spec.messages:
            self.session.add(DisposalMessage(
                case_id=case.id,
                sender_id=self.user(message_spec.sender).id if message_spec.sender else None,
                role=message_spec.role,
                kind=message_spec.kind,
                content=message_spec.content,
                created_at=self.at(message_spec.days_ago),
            ))
        return case

    def _report_target(self, spec: catalog.ReportSpec) -> int:
        if spec.target_type == "user":
            return self.users[spec.target.removeprefix("account_")].id
        return self.resolve_id(spec.target)

    async def build_reports(self) -> None:
        for spec in catalog.REPORTS:
            target_id = self._report_target(spec)
            report = Report(
                reporter_id=self.user(spec.reporter).id,
                target_type=spec.target_type,
                target_id=target_id,
                reason=spec.reason,
                detail=spec.detail,
                evidence_keys=[],
                status=spec.status,
                result_confirmed=spec.result_confirmed,
                public_result=spec.public_result,
                result_reason=spec.result_reason,
                closed_at=self.at(spec.closed_days_ago),
                created_at=self.at(spec.days_ago),
                updated_at=self.at(spec.closed_days_ago or spec.days_ago),
            )
            await self.flush_add(spec.key, report, "report")
            self.reports[spec.key] = report
            for evidence in spec.evidence:
                report.evidence_keys = [*report.evidence_keys, await self._evidence(
                    evidence, owner_id=report.reporter_id, ref_type="report", ref_id=report.id, days_ago=spec.days_ago,
                )]
            for supplement_spec in spec.supplements:
                supplement = ReportSupplement(
                    report_id=report.id,
                    author_id=self.user(supplement_spec.author).id,
                    content=supplement_spec.content,
                    evidence_keys=[],
                    created_at=self.at(supplement_spec.days_ago),
                )
                await self.flush_add(supplement_spec.key, supplement, "report_supplement")
                for evidence in supplement_spec.evidence:
                    supplement.evidence_keys = [*supplement.evidence_keys, await self._evidence(
                        evidence, owner_id=supplement.author_id, ref_type="report_supplement",
                        ref_id=supplement.id, days_ago=supplement_spec.days_ago,
                    )]
            if spec.case is not None:
                await self._case(spec.case, report_id=report.id)

        for spec in catalog.PRODUCTS:
            if not spec.display_restricted:
                continue
            product = self.products[spec.key]
            product.display_restricted_case_id = self.resolve_id(spec.restricted_case) if spec.restricted_case else None
            product.display_restricted_reason = spec.restricted_reason
            product.display_restricted_at = self.at(spec.restricted_days_ago)

        for spec in catalog.RESTRICTIONS:
            restriction = AccountRestriction(
                user_id=self.user(spec.user).id,
                type="ban",
                status=spec.status,
                reason=spec.reason,
                basis=spec.basis,
                case_id=self.resolve_id(spec.case),
                created_by_id=self.user(spec.created_by).id,
                created_at=self.at(spec.days_ago),
                lifted_at=self.at(spec.lifted_days_ago),
                lifted_by_id=self.user(spec.lifted_by).id if spec.lifted_by else None,
                lift_reason=spec.lift_reason,
            )
            await self.flush_add(spec.key, restriction, "account_restriction")
            if spec.status == "active":
                self.user(spec.user).status = "banned"

    # ------------------------------------------------------------------
    # 普通私聊、头像、通知
    # ------------------------------------------------------------------
    async def build_normal_conversations(self) -> None:
        for spec in catalog.NORMAL_CONVERSATIONS:
            low, high = sorted((self.user(spec.users[0]).id, self.user(spec.users[1]).id))
            conversation = Conversation(
                type="normal", user_low_id=low, user_high_id=high,
                created_at=self.at(spec.created_days_ago),
            )
            await self.flush_add(spec.key, conversation, "conversation")
            self.conversations[spec.key] = conversation
            message_ids: list[int] = []
            for index, message_spec in enumerate(spec.messages, start=1):
                message = Message(
                    conversation_id=conversation.id,
                    sender_id=self.user(message_spec.sender).id if message_spec.sender else None,
                    kind="system" if message_spec.sender is None else "text",
                    content=message_spec.content,
                    created_at=self.at(message_spec.days_ago),
                )
                key = message_key(spec.key, index)
                await self.flush_add(key, message, "message")
                self.messages[key] = message
                message_ids.append(message.id)
            for user_key, count in spec.reads:
                self.session.add(ConversationRead(
                    conversation_id=conversation.id,
                    user_id=self.user(user_key).id,
                    last_read_message_id=message_ids[count - 1] if count > 0 else 0,
                    updated_at=self.at(spec.messages[count - 1].days_ago) if count > 0 else self.at(spec.created_days_ago),
                ))

    async def build_avatars(self) -> None:
        for spec in catalog.AVATARS:
            content = _asset_bytes(spec.asset)
            entry = self.ensure_file(spec.slug, "avatar", spec.asset, spec.asset, content)
            user = self.user(spec.user)
            user.avatar_pending_key = entry["key"]
            user.avatar_review_status = "pending"
            self.session.add(StoredObject(
                key=entry["key"], namespace="avatar", bucket_role="media",
                owner_id=user.id, content_type="image/jpeg", size_bytes=len(content),
                state="committed", ref_type="avatar", ref_id=user.id,
                committed_at=self.at(spec.days_ago),
            ))
            await self._case(spec.case, subject_key=spec.user)
            case = self.cases[spec.case.key]
            case.avatar_key = entry["key"]
            if spec.slug in self.objects:
                raise ValueError(f"演示对象 key 重复：{spec.slug}")
            self.objects[spec.slug] = {"id": user.id, "kind": "avatar"}

    async def build_notifications(self) -> None:
        for spec in catalog.NOTIFICATIONS:
            link_id = self.resolve_id(spec.link) if spec.link else None
            notification = Notification(
                user_id=self.user(spec.user).id,
                type=spec.type,
                title=spec.title,
                content=spec.content,
                link_type=spec.link_type,
                link_id=link_id,
                payload=spec.payload,
                is_read=spec.is_read,
                read_at=self.at(spec.read_days_ago),
                created_at=self.at(spec.days_ago),
            )
            await self.flush_add(spec.key, notification, "notification")

    async def finish(self) -> dict[str, dict]:
        # 所有场景/核验引用对象必须已物化，防止目录与构建器漂移。
        from app.devtools.demo_scenarios.checks import object_inventory

        missing = sorted(set(object_inventory()) - set(self.objects))
        if missing:
            raise ValueError("场景对象未构建：" + "、".join(missing[:10]))
        self.data["objects"] = self.objects
        self.data["object_kinds"] = {key: value["kind"] for key, value in self.objects.items()}
        self.data["scenarios"] = [scenario.key for scenario in catalog.SCENARIOS]
        return self.objects



async def build(
    session: AsyncSession,
    *,
    data: dict,
    settings: Any,
    ensure_file: EnsureFile,
    now: datetime,
) -> dict[str, dict]:
    builder = _Builder(session, data=data, settings=settings, ensure_file=ensure_file, now=now)
    await builder.build_accounts()
    await builder.build_categories()
    await builder.build_products()
    for case_spec in catalog.CASES:
        await builder._case(case_spec)
    await builder.build_trades()
    await builder.build_reports()
    await builder.build_normal_conversations()
    await builder.build_avatars()
    await builder.build_notifications()
    return await builder.finish()

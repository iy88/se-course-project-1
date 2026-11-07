"""Read-only verification of persistent demo data.

Covers: manifest/catalog signature, accounts, file readability and object
registration, scenario coverage, initial catalog state, cross-entity
invariants, and a set of read-only API visibility/permission checks. Writes no
business records, advances no read state, and prints no passwords, signed URLs,
or connection strings.
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
        raise ValueError(f"manifest is missing object {key}")
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
        report.check(user is not None, f"Account not found: {spec.key}")
        if user is None:
            continue
        report.check(user.email == account["email"], f"Account email mismatch: {spec.key}")
        report.check(user.role == spec.role, f"Account role mismatch: {spec.key}")
        report.check(user.display_name == spec.display_name, f"Account display name mismatch: {spec.key}")
        report.check(verify_password(account["password"], user.password_hash), f"Account password cannot be verified: {spec.key}")
    report.counts["accounts"] = len(catalog.ACCOUNTS)


async def _verify_objects(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    models = _object_models()
    for key, entry in data["objects"].items():
        report.check(isinstance(entry, dict) and "kind" in entry and "id" in entry, f"Object structure is incomplete: {key}")
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        model = models.get(kind) if isinstance(kind, str) else None
        report.check(model is not None, f"Unknown object kind: {key}")
        if model is None:
            continue
        obj = await session.get(model, entry["id"])
        report.check(obj is not None, f"Object record is missing: {key}")
    for scenario in catalog.SCENARIOS:
        for key in scenario.objects:
            report.check(key in data["objects"], f"Scenario object is not registered: {scenario.key}/{key}")
    report.check(set(data.get("scenarios", [])) == {s.key for s in catalog.SCENARIOS},
                 "manifest scenario list does not match the catalog")
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
            report.check(False, f"File is unreadable: {name}")
            continue
        report.check(len(content) == entry.get("size"), f"File size mismatch: {name}")
        report.check(hashlib.sha256(content).hexdigest() == entry.get("sha256"), f"File digest mismatch: {name}")
        obj = await session.get(StoredObject, key)
        report.check(obj is not None and obj.state == "committed", f"Object registration is not committed: {name}")
        if obj is not None:
            report.check(obj.size_bytes == len(content), f"Object size mismatch: {name}")
            report.check(obj.namespace == entry.get("namespace"), f"Object namespace mismatch: {name}")
            report.check(obj.bucket_role == bucket_role_for_namespace(entry["namespace"]), f"Object bucket role mismatch: {name}")
    # Link files to business objects: product images, avatars, report evidence/supplement evidence.
    from app.models.governance import Report, ReportSupplement
    from app.models.product import Product, ProductImage
    from app.models.user import User

    checked_refs: set[str] = set()
    for spec in catalog.PRODUCTS:
        product = await session.get(Product, _id(data, spec.key))
        if product is None:
            continue
        images = (await session.exec(select(ProductImage).where(ProductImage.product_id == product.id))).all()
        report.check(len(images) == 1, f"Product image count mismatch: {spec.key}")
        for image in images:
            obj = await session.get(StoredObject, image.file_key)
            report.check(obj is not None, f"Product image has no registered object: {spec.key}")
            if obj is not None:
                report.check(obj.ref_type == "product" and obj.ref_id == product.id, f"Product image association mismatch: {spec.key}")
            checked_refs.add(image.file_key)
    for avatar_spec in catalog.AVATARS:
        user = await session.get(User, _id(data, f"account_{avatar_spec.user}"))
        if user is None or not user.avatar_pending_key:
            continue
        obj = await session.get(StoredObject, user.avatar_pending_key)
        report.check(obj is not None and obj.ref_type == "avatar" and obj.ref_id == user.id,
                     f"Avatar object association mismatch: {avatar_spec.user}")
        checked_refs.add(user.avatar_pending_key)
    for report_spec in catalog.REPORTS:
        item = await session.get(Report, _id(data, report_spec.key))
        if item is None:
            continue
        for key in item.evidence_keys:
            obj = await session.get(StoredObject, key)
            report.check(obj is not None and obj.ref_type == "report" and obj.ref_id == item.id,
                         f"Report evidence association mismatch: {report_spec.key}")
            checked_refs.add(key)
        for supplement in (await session.exec(
            select(ReportSupplement).where(ReportSupplement.report_id == item.id)
        )).all():
            for key in supplement.evidence_keys:
                obj = await session.get(StoredObject, key)
                report.check(obj is not None and obj.ref_type == "report_supplement" and obj.ref_id == supplement.id,
                             f"Report supplement evidence association mismatch: {report_spec.key}")
                checked_refs.add(key)
    report.check(len(checked_refs) == len(data["files"]), "Registered files are not linked to any business object")
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
        report.check(product is not None, f"Product is missing: {spec.key}")
        if product is None:
            continue
        report.check(product.title == spec.title, f"Product title mismatch: {spec.key}")
        report.check(product.description == spec.description, f"Product description mismatch: {spec.key}")
        report.check(product.price_cents == spec.price_cents, f"Product price mismatch: {spec.key}")
        report.check(product.status == spec.status, f"Product status mismatch: {spec.key}")
        report.check(product.display_restricted == spec.display_restricted, f"Product display restriction mismatch: {spec.key}")
        if spec.display_restricted:
            report.check(product.display_restricted_case_id is not None, f"Restricted product is missing its case: {spec.key}")
            report.check(bool(product.display_restricted_reason), f"Restricted product is missing a reason: {spec.key}")
        else:
            report.check(not product.display_restricted_reason, f"Unrestricted product has a leftover restriction reason: {spec.key}")
        for tag_key in spec.all_tags:
            category_id = _id(data, tag_key)
            tagged = (await session.exec(
                select(ProductTag).where(ProductTag.product_id == product.id, ProductTag.category_id == category_id)
            )).first()
            report.check(tagged is not None, f"Product tag is missing: {spec.key}/{tag_key}")

        reviews = list((await session.exec(
            select(ReviewRecord).where(ReviewRecord.product_id == product.id).order_by(col(ReviewRecord.id))
        )).all())
        expected_reviews = spec.reviews or (
            (catalog.ReviewSpec("approved", spec.listed_days_ago or spec.created_days_ago, reviewer="admin"),)
            if spec.status in {"listed", "in_transaction", "delisted"} else ()
        )
        report.check(len(reviews) >= len(expected_reviews), f"Not enough review records: {spec.key}")
        for index, review_spec in enumerate(expected_reviews):
            if index >= len(reviews):
                continue
            record = reviews[index]
            report.check(record.result == review_spec.result, f"Review result mismatch: {spec.key}/{index}")
            if review_spec.result == "pending":
                case = await session.get(__import__("app.models", fromlist=["DisposalCase"]).DisposalCase, record.case_id)
                report.check(case is not None and case.status != "disposed", f"Pending review case status mismatch: {spec.key}")
            else:
                report.check(record.reviewed_at is not None, f"Review time is missing: {spec.key}/{index}")

        apps = list((await session.exec(
            select(ProductTagApplication).where(ProductTagApplication.product_id == product.id).order_by(col(ProductTagApplication.id))
        )).all())
        report.check(len(apps) == len(spec.tag_apps), f"Tag application count mismatch: {spec.key}")
        for index, app_spec in enumerate(spec.tag_apps):
            if index >= len(apps):
                continue
            report.check(apps[index].requested_name == app_spec.requested_name, f"Tag application name mismatch: {spec.key}")
            report.check(apps[index].status == app_spec.status, f"Tag application status mismatch: {spec.key}")
            if app_spec.status == "rejected":
                report.check(bool(apps[index].decision_reason), f"Rejected tag is missing a reason: {spec.key}")
        if "课本" in [app.requested_name for app in spec.tag_apps]:
            alias = (await session.exec(
                select(CategoryAlias).where(CategoryAlias.name == "课本", col(CategoryAlias.removed_at).is_(None))
            )).first()
            report.check(alias is not None, "Textbook alias “课本” is missing")

        edits = list((await session.exec(
            select(ProductEditHistory).where(ProductEditHistory.product_id == product.id).order_by(col(ProductEditHistory.id))
        )).all())
        report.check(len(edits) == len(spec.edits), f"Product edit history count mismatch: {spec.key}")
        for index, edit_spec in enumerate(spec.edits):
            if index >= len(edits):
                continue
            report.check(edits[index].edit_type == edit_spec.edit_type, f"Edit type mismatch: {spec.key}")
            report.check(edits[index].before_json == edit_spec.before, f"Content before edit mismatch: {spec.key}")
            report.check(edits[index].after_json == edit_spec.after, f"Content after edit mismatch: {spec.key}")

        comments = list((await session.exec(
            select(Comment).where(Comment.product_id == product.id).order_by(col(Comment.id))
        )).all())
        report.check(len(comments) == len(spec.comments), f"Comment count mismatch: {spec.key}")
        by_key = {}
        for index, comment_spec in enumerate(spec.comments):
            if index >= len(comments):
                continue
            comment = comments[index]
            by_key[comment_spec.key] = comment
            report.check(comment.content == comment_spec.content, f"Comment content mismatch: {comment_spec.key}")
            report.check((comment.deleted_at is not None) == (comment_spec.deleted_days_ago is not None),
                         f"Comment deletion flag mismatch: {comment_spec.key}")
            if comment_spec.reply_to:
                parent = by_key.get(comment_spec.reply_to)
                report.check(parent is not None and comment.reply_to_comment_id == parent.id,
                             f"Comment reply relation mismatch: {comment_spec.key}")
        for user_key in spec.favorites:
            favorite = (await session.exec(
                select(Favorite).where(Favorite.user_id == _id(data, f"account_{user_key}"), Favorite.product_id == product.id)
            )).first()
            report.check(favorite is not None, f"Favorite is missing: {spec.key}/{user_key}")
    report.counts["products"] = len(catalog.PRODUCTS)


async def _verify_case_messages(session: AsyncSession, data: dict, case, case_spec, report: VerificationReport, label: str) -> None:
    from app.models.governance import DisposalMessage

    messages = list((await session.exec(
        select(DisposalMessage).where(DisposalMessage.case_id == case.id).order_by(col(DisposalMessage.id))
    )).all())
    report.check(len(messages) == len(case_spec.messages), f"Case message count mismatch: {label}")
    for index, message_spec in enumerate(case_spec.messages):
        if index >= len(messages):
            continue
        message = messages[index]
        report.check(message.content == message_spec.content, f"Case message content mismatch: {label}/{index}")
        report.check(message.role == message_spec.role, f"Case message role mismatch: {label}/{index}")
        expected = _id(data, f"account_{message_spec.sender}") if message_spec.sender else None
        report.check(message.sender_id == expected, f"Case message sender mismatch: {label}/{index}")


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
        report.check(trade is not None, f"Trade is missing: {spec.key}")
        if trade is None:
            continue
        product = await session.get(Product, _id(data, spec.product))
        report.check(product is not None, f"Trade product is missing: {spec.key}")
        report.check(trade.status == spec.status, f"Trade status mismatch: {spec.key}")
        report.check(trade.buyer_id == _id(data, f"account_{spec.buyer}"), f"Trade buyer mismatch: {spec.key}")
        if product is not None:
            report.check(trade.seller_id == product.seller_id, f"Trade seller mismatch: {spec.key}")
            if spec.status in {"in_progress", "disputed", "abnormal"}:
                report.check(product.status == "in_transaction", f"Locked product status mismatch: {spec.key}")
                report.check(product.id not in locking_products, f"Product has more than one locking trade: {spec.key}")
                locking_products.add(product.id)
            if spec.status in {"completed", "terminated"}:
                report.check(product.status == "delisted", f"Product of finished trade is not delisted: {spec.key}")
                report.check(trade.finished_at is not None, f"Finished trade is missing its completion time: {spec.key}")
        report.check((trade.accepted_at is not None) == (spec.accepted_days_ago is not None), f"Acceptance time mismatch: {spec.key}")
        if spec.status in {"completed", "terminated"}:
            report.check(trade.frozen is False, f"Finished trade is still frozen: {spec.key}")
            report.check(trade.finished_at is not None, f"Finish time is missing: {spec.key}")

        agreements = list((await session.exec(
            select(TradeAgreement).where(TradeAgreement.trade_id == trade.id).order_by(col(TradeAgreement.round_no))
        )).all())
        report.check(len(agreements) == len(spec.agreements), f"Agreement count mismatch: {spec.key}")
        for index, agreement_spec in enumerate(spec.agreements):
            if index >= len(agreements):
                continue
            report.check(agreements[index].round_no == agreement_spec.round_no, f"Agreement round mismatch: {spec.key}")
            report.check(agreements[index].status == agreement_spec.status, f"Agreement status mismatch: {spec.key}")
            report.check(agreements[index].amount_cents == agreement_spec.amount_cents, f"Agreement amount mismatch: {spec.key}")
        if spec.current_round is None:
            report.check(trade.current_agreement_id is None, f"Unexpected current agreement: {spec.key}")
        else:
            current = next((item for item in agreements if item.round_no == spec.current_round), None)
            report.check(current is not None and trade.current_agreement_id == (current.id if current else None),
                         f"Current agreement mismatch: {spec.key}")
            report.check(current is not None and current.status == "confirmed", f"Current agreement is not confirmed: {spec.key}")

        confirmations = list((await session.exec(
            select(CompletionConfirmation).where(CompletionConfirmation.trade_id == trade.id).order_by(col(CompletionConfirmation.id))
        )).all())
        report.check(len(confirmations) == len(spec.confirmations), f"Completion confirmation count mismatch: {spec.key}")
        expected_current = {item.confirmer for item in spec.confirmations if item.is_current}
        actual_current = {item.confirmer_id for item in confirmations if item.is_current}
        report.check(actual_current == {_id(data, f"account_{key}") for key in expected_current},
                     f"Current completion confirmation mismatch: {spec.key}")
        if spec.status in {"completed"} and spec.finished_by is None:
            report.check(len(actual_current) == 2, f"Normally completed trade is missing both parties' current confirmation: {spec.key}")
        if spec.status in {"disputed"}:
            report.check(trade.confirm_wait_started_at is None, f"Disputed trade is still counting down: {spec.key}")
        if spec.frozen:
            report.check(trade.frozen, f"Trade frozen flag mismatch: {spec.key}")
            if spec.confirm_wait_started_days_ago is not None and any(c.is_current for c in confirmations):
                report.check(trade.confirm_wait_paused_at is not None, f"Frozen trade has not paused its countdown: {spec.key}")
                report.check(trade.confirm_wait_remaining_seconds is not None, f"Frozen trade is missing the remaining time: {spec.key}")
        if spec.cancel_requested_by:
            report.check(trade.cancel_requested_by_id == _id(data, f"account_{spec.cancel_requested_by}"),
                         f"Cancellation requester mismatch: {spec.key}")
        else:
            report.check(trade.cancel_requested_by_id is None, f"Leftover cancellation requester: {spec.key}")
        if spec.resolution_confirmed_by:
            report.check(trade.resolution_confirmed_by_id == _id(data, f"account_{spec.resolution_confirmed_by}"),
                         f"Dispute resolution confirmer mismatch: {spec.key}")

        transitions = list((await session.exec(
            select(TradeTransition).where(TradeTransition.trade_id == trade.id).order_by(col(TradeTransition.id))
        )).all())
        report.check(len(transitions) >= 1, f"Trade is missing status transitions: {spec.key}")
        if transitions:
            report.check(transitions[0].to_status == "pending_acceptance", f"First transition is not pending acceptance: {spec.key}")
            report.check(transitions[-1].to_status == spec.status, f"Last transition does not match the status: {spec.key}")
            previous = None
            for transition in transitions:
                created = _at(transition.created_at)
                report.check(created is not None, f"Transition is missing a timestamp: {spec.key}")
                report.check(previous is None or (created is not None and created >= previous),
                             f"Transition timestamps are out of order: {spec.key}")
                previous = created

        reviews = list((await session.exec(
            select(TradeReview).where(TradeReview.trade_id == trade.id).order_by(col(TradeReview.id))
        )).all())
        report.check(len(reviews) == len(spec.reviews), f"Trade review count mismatch: {spec.key}")
        for index, review_spec in enumerate(spec.reviews):
            if index >= len(reviews):
                continue
            report.check(reviews[index].rating == review_spec.rating, f"Trade rating mismatch: {spec.key}")
            report.check(reviews[index].content == review_spec.content, f"Trade review content mismatch: {spec.key}")
            report.check((reviews[index].deleted_at is not None) == (review_spec.deleted_days_ago is not None),
                         f"Trade review deletion flag mismatch: {spec.key}")

        conversation = (await session.exec(
            select(Conversation).where(Conversation.type == "trade", Conversation.trade_id == trade.id)
        )).first()
        report.check(conversation is not None, f"Trade branch is missing: {spec.key}")
        if conversation is not None:
            terminal = spec.status in {"completed", "terminated", "rejected", "withdrawn", "closed"}
            report.check(conversation.archived == terminal, f"Branch archive flag mismatch: {spec.key}")
            messages = list((await session.exec(
                select(Message).where(Message.conversation_id == conversation.id).order_by(col(Message.id))
            )).all())
            report.check(len(messages) == len(spec.messages), f"Trade message count mismatch: {spec.key}")
            for index, message_spec in enumerate(spec.messages):
                if index >= len(messages):
                    continue
                message = messages[index]
                report.check(message.content == message_spec.content, f"Trade message content mismatch: {spec.key}/{index}")
                expected_sender = _id(data, f"account_{message_spec.sender}") if message_spec.sender else None
                report.check(message.sender_id == expected_sender, f"Trade message sender mismatch: {spec.key}/{index}")
            for user_key, count in spec.reads:
                row = (await session.exec(
                    select(ConversationRead).where(
                        ConversationRead.conversation_id == conversation.id,
                        ConversationRead.user_id == _id(data, f"account_{user_key}"),
                    )
                )).first()
                report.check(row is not None and row.last_read_message_id == messages[count - 1].id,
                             f"Trade branch read state mismatch: {spec.key}/{user_key}")
        if spec.case is not None:
            case = await session.get(__import__("app.models", fromlist=["DisposalCase"]).DisposalCase, _id(data, spec.case.key))
            report.check(case is not None and case.trade_id == trade.id, f"Trade case association mismatch: {spec.key}")
            if case is not None:
                await _verify_case_messages(session, data, case, spec.case, report, spec.key)
    report.counts["trades"] = len(catalog.TRADES)


async def _verify_reports(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import DisposalCase, Report, ReportSupplement

    for spec in catalog.REPORTS:
        item = await session.get(Report, _id(data, spec.key))
        report.check(item is not None, f"Report is missing: {spec.key}")
        if item is None:
            continue
        report.check(item.status == spec.status, f"Report status mismatch: {spec.key}")
        report.check(item.result_confirmed == spec.result_confirmed, f"Report result-confirmed flag mismatch: {spec.key}")
        report.check(item.public_result == spec.public_result, f"Report public result mismatch: {spec.key}")
        report.check(item.result_reason == spec.result_reason, f"Report conclusion reason mismatch: {spec.key}")
        report.check((item.closed_at is not None) == (spec.closed_days_ago is not None), f"Report closure time mismatch: {spec.key}")
        if spec.status == "unfounded":
            report.check(item.public_result is None, f"Unfounded report should not have a public result: {spec.key}")
        supplements = list((await session.exec(
            select(ReportSupplement).where(ReportSupplement.report_id == item.id).order_by(col(ReportSupplement.id))
        )).all())
        report.check(len(supplements) == len(spec.supplements), f"Report supplement count mismatch: {spec.key}")
        for index, supplement_spec in enumerate(spec.supplements):
            if index < len(supplements):
                report.check(supplements[index].content == supplement_spec.content, f"Report supplement content mismatch: {spec.key}")
                report.check(len(supplements[index].evidence_keys) == len(supplement_spec.evidence),
                             f"Report supplement evidence count mismatch: {spec.key}")
        if spec.case is not None:
            case = await session.get(DisposalCase, _id(data, spec.case.key))
            report.check(case is not None and case.report_id == item.id, f"Report case association mismatch: {spec.key}")
            if case is not None:
                report.check(case.status == spec.case.status, f"Report case status mismatch: {spec.key}")
                report.check((case.claimed_by_id is not None) == (spec.case.claimed_by is not None),
                             f"Report case claim mismatch: {spec.key}")
                report.check((case.disposed_at is not None) == (spec.case.disposed_days_ago is not None),
                             f"Report case disposal time mismatch: {spec.key}")
                await _verify_case_messages(session, data, case, spec.case, report, spec.key)
        if spec.target_type == "product":
            product = await session.get(__import__("app.models", fromlist=["Product"]).Product, item.target_id)
            report.check(product is not None, f"Reported product target is missing: {spec.key}")
            if spec.status == "handled" and spec.key == "report_product_handled" and product is not None:
                report.check(product.display_restricted, f"Product was not restricted after disposal: {spec.key}")
                report.check(spec.case is not None and product.display_restricted_case_id == _id(data, spec.case.key),
                             f"Restriction case association mismatch: {spec.key}")
        elif spec.target_type == "comment":
            comment = await session.get(__import__("app.models", fromlist=["Comment"]).Comment, item.target_id)
            report.check(comment is not None, f"Reported comment target is missing: {spec.key}")
            report.check(comment is not None and comment.deleted_at is not None, f"Reported comment was not removed: {spec.key}")
        elif spec.target_type == "review":
            review = await session.get(__import__("app.models", fromlist=["TradeReview"]).TradeReview, item.target_id)
            report.check(review is not None, f"Reported review target is missing: {spec.key}")
            report.check(review is not None and review.deleted_at is not None, f"Reported review was not removed: {spec.key}")
        elif spec.target_type == "user":
            user = await session.get(__import__("app.models", fromlist=["User"]).User, item.target_id)
            report.check(user is not None, f"Reported user target is missing: {spec.key}")
    report.counts["reports"] = len(catalog.REPORTS)


async def _verify_restrictions(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.user import AccountRestriction, User

    for spec in catalog.RESTRICTIONS:
        restriction = await session.get(AccountRestriction, _id(data, spec.key))
        report.check(restriction is not None, f"Restriction is missing: {spec.key}")
        if restriction is None:
            continue
        report.check(restriction.user_id == _id(data, f"account_{spec.user}"), f"Restriction user mismatch: {spec.key}")
        report.check(restriction.status == spec.status, f"Restriction status mismatch: {spec.key}")
        report.check(restriction.case_id == _id(data, spec.case), f"Restriction case association mismatch: {spec.key}")
        if spec.status == "lifted":
            report.check(restriction.lifted_at is not None and bool(restriction.lift_reason),
                         f"Lifted restriction is missing its justification: {spec.key}")
        else:
            user = await session.get(User, restriction.user_id)
            report.check(user is not None and user.status == "banned", f"User under an active restriction is not banned: {spec.key}")
    report.counts["restrictions"] = len(catalog.RESTRICTIONS)


async def _verify_notifications(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import Notification
    from app.models.user import User

    for spec in catalog.NOTIFICATIONS:
        item = await session.get(Notification, _id(data, spec.key))
        report.check(item is not None, f"Notification is missing: {spec.key}")
        if item is None:
            continue
        report.check(item.user_id == _id(data, f"account_{spec.user}"), f"Notification recipient mismatch: {spec.key}")
        report.check(item.is_read == spec.is_read, f"Notification read state mismatch: {spec.key}")
        report.check((item.read_at is not None) == spec.is_read, f"Notification read time mismatch: {spec.key}")
        report.check(item.type == spec.type, f"Notification type mismatch: {spec.key}")
        if spec.link:
            report.check(item.link_id == _resolve_link(data, spec.link, spec.link_type),
                         f"Notification link mismatch: {spec.key}")
        user = await session.get(User, item.user_id)
        report.check(user is not None and user.role != "admin", f"Admin received a personal notification: {spec.key}")
    report.counts["notifications"] = len(catalog.NOTIFICATIONS)


def _resolve_link(data: dict, key: str, link_type: str | None) -> int:
    if link_type == "conversation":
        return _id(data, key)
    return _id(data, key)


async def _verify_conversations(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.im import Conversation, ConversationRead, Message

    for spec in catalog.NORMAL_CONVERSATIONS:
        conversation = await session.get(Conversation, _id(data, spec.key))
        report.check(conversation is not None, f"Normal conversation is missing: {spec.key}")
        if conversation is None:
            continue
        report.check(conversation.type == "normal", f"Normal conversation type mismatch: {spec.key}")
        report.check(conversation.user_low_id == min(_id(data, f"account_{u}") for u in spec.users),
                     f"Normal conversation members mismatch: {spec.key}")
        messages = list((await session.exec(
            select(Message).where(Message.conversation_id == conversation.id).order_by(col(Message.id))
        )).all())
        report.check(len(messages) == len(spec.messages), f"Normal conversation message count mismatch: {spec.key}")
        for index, message_spec in enumerate(spec.messages):
            if index < len(messages):
                report.check(messages[index].content == message_spec.content, f"Normal conversation message mismatch: {spec.key}/{index}")
        for user_key, count in spec.reads:
            row = (await session.exec(
                select(ConversationRead).where(ConversationRead.conversation_id == conversation.id,
                                               ConversationRead.user_id == _id(data, f"account_{user_key}"))
            )).first()
            report.check(row is not None and row.last_read_message_id == messages[count - 1].id,
                         f"Normal conversation read state mismatch: {spec.key}/{user_key}")
    report.counts["conversations"] = len(catalog.NORMAL_CONVERSATIONS)


async def _verify_avatars(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import DisposalCase
    from app.models.user import User
    from app.models.stored_object import StoredObject

    for spec in catalog.AVATARS:
        user = await session.get(User, _id(data, f"account_{spec.user}"))
        report.check(user is not None and user.avatar_pending_key is not None, f"Avatar pending-review key is missing: {spec.user}")
        if user is not None:
            report.check(user.avatar_review_status == "pending", f"Avatar review status mismatch: {spec.user}")
        case = await session.get(DisposalCase, _id(data, spec.case.key))
        report.check(case is not None and case.avatar_key == (user.avatar_pending_key if user else None),
                     f"Avatar case association mismatch: {spec.user}")
        if user is not None and user.avatar_pending_key:
            obj = await session.get(StoredObject, user.avatar_pending_key)
            report.check(obj is not None and obj.state == "committed", f"Avatar object is not committed: {spec.user}")


async def _verify_cross_invariants(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import DisposalCase, Report
    from app.models.product import Product
    from app.models.trade import Trade
    from app.models.user import AccountRestriction, User

    restricted_without_case = (await session.exec(
        select(Product.id).where(col(Product.display_restricted).is_(True),
                                 col(Product.display_restricted_case_id).is_(None))
    )).all()
    report.check(not restricted_without_case, "Restricted product is missing its associated case")
    active_bans = (await session.exec(
        select(AccountRestriction.user_id).where(AccountRestriction.status == "active")
    )).all()
    for user_id in set(active_bans):
        user = await session.get(User, user_id)
        report.check(user is not None and user.status == "banned", "User subject to an active ban is not banned")
    for user in (await session.exec(select(User).where(User.status == "banned"))).all():
        active = (await session.exec(
            select(AccountRestriction.id).where(AccountRestriction.user_id == user.id,
                                                AccountRestriction.status == "active")
        )).first()
        report.check(active is not None, f"Banned user is missing an active restriction: {user.display_name}")
    locking = (await session.exec(
        select(Trade.product_id).where(col(Trade.status).in_(["in_progress", "disputed", "abnormal"]))
    )).all()
    report.check(len(locking) == len(set(locking)), "The same product has more than one locking trade")
    for product in (await session.exec(select(Product).where(Product.status == "in_transaction"))).all():
        report.check(product.id in set(locking), "Product in transaction is missing a locking trade")
    for report_row in (await session.exec(select(Report).where(col(Report.status).in_(["handled", "unfounded"])))).all():
        report.check(report_row.result_confirmed and report_row.closed_at is not None,
                     f"Closed report is missing confirmation or closure time: {report_row.id}")
        report.check(report_row.public_result is not None if report_row.status == "handled" else report_row.public_result is None,
                     f"Report public result does not match status: {report_row.id}")
    for case in (await session.exec(select(DisposalCase))).all():
        if case.status == "disposed":
            report.check(bool(case.conclusion) and case.disposed_at is not None, f"Disposed case is missing a conclusion: {case.id}")
        if case.status == "processing":
            report.check(case.claimed_by_id is not None, f"Processing case is not claimed: {case.id}")
        if case.status == "pending":
            report.check(case.claimed_by_id is None, f"Pending case is already claimed: {case.id}")


async def _verify_standalone_cases(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    from app.models.governance import DisposalCase

    for spec in catalog.CASES:
        case = await session.get(DisposalCase, _id(data, spec.key))
        report.check(case is not None, f"Standalone case is missing: {spec.key}")
        if case is None:
            continue
        report.check(case.status == spec.status, f"Standalone case status mismatch: {spec.key}")
        report.check((case.claimed_by_id is not None) == (spec.claimed_by is not None), f"Standalone case claim mismatch: {spec.key}")
        report.check((case.disposed_at is not None) == (spec.disposed_days_ago is not None), f"Standalone case disposal time mismatch: {spec.key}")
        await _verify_case_messages(session, data, case, spec, report, spec.key)
    for avatar in catalog.AVATARS:
        case = await session.get(DisposalCase, _id(data, avatar.case.key))
        report.check(case is not None, f"Avatar case is missing: {avatar.user}")
        if case is not None:
            await _verify_case_messages(session, data, case, avatar.case, report, avatar.case.key)


async def _verify_api_visibility(session: AsyncSession, data: dict, report: VerificationReport) -> None:
    """Call the read-only endpoint functions directly to verify public/restricted/private scope (without starting the service)."""
    from fastapi import HTTPException

    from app.api.v1.admin.cases import case_detail
    from app.api.v1.products import detail, restriction_result, search
    from app.api.v1.trades import trade_detail
    from app.models.user import User

    buyer = await session.get(User, _id(data, "account_buyer"))
    admin = await session.get(User, _id(data, "account_admin"))
    admin2 = await session.get(User, _id(data, "account_admin2"))
    outsider = await session.get(User, _id(data, "account_outsider"))
    if buyer is None or admin is None or admin2 is None or outsider is None:
        report.check(False, "Read-only API verification is missing accounts")
        return
    result = await search(session, buyer, keyword="山地车", category_ids=None, category_names=None,
                          price_min_cents=None, price_max_cents=None, page=1, page_size=20)
    report.check(any(item.id == _id(data, "product_bike") for item in result.items), "Public search did not return “山地车”")
    restricted_id = _id(data, "product_powerbank")
    report.check(all(item.id != restricted_id for item in result.items), "Restricted product appeared in public search")
    try:
        await detail(restricted_id, buyer, session)
        report.check(False, "Restricted product detail was not rejected")
    except HTTPException as exc:
        report.check(exc.status_code == 404, "Restricted product detail should return 404")
    public = await restriction_result(restricted_id, buyer, session)
    report.check(public == {"public_result": "经核查，商品存在电池鼓包安全隐患，已停止公开访问并提醒卖方妥善处理"},
                 "Anonymous disposal result mismatch")
    try:
        await trade_detail(_id(data, "trade_frozen"), outsider, session)
        report.check(False, "Non-party trade detail read was not rejected")
    except HTTPException as exc:
        report.check(exc.status_code == 404, "Non-party trade detail should return 404")
    try:
        await case_detail(_id(data, "case_review_product_keyboard"), admin2, session)
        report.check(False, "Non-claiming admin case read was not rejected")
    except HTTPException as exc:
        report.check(exc.status_code == 403, "Non-claiming admin case detail should return 403")
    report.counts["api_visibility"] = 6


async def verify(
    session: AsyncSession,
    storage,
    data: dict,
    *,
    verify_api: bool = True,
) -> VerificationReport:
    """Run all read-only verifications; the caller is responsible for manifest version/target/catalog signature checks."""
    report = VerificationReport()
    if not data.get("complete"):
        report.errors.append("manifest is incomplete")
        return report
    from app.devtools.demo_scenarios.checks import validate_catalog

    summary = validate_catalog()
    report.check(data.get("catalog_signature") == catalog.catalog_signature(), "manifest catalog signature mismatch")
    report.check(set(map(str, data.get("scenarios", []))) == {s.key for s in catalog.SCENARIOS},
                 "manifest scenario coverage does not match the catalog")
    report.check(data.get("object_kinds") == {key: value.get("kind") for key, value in data.get("objects", {}).items()},
                 "manifest object_kinds does not match objects")
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

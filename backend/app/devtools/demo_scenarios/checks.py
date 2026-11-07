"""Static validation and object inventory for the scenario catalog.

``validate_catalog()`` connects to no database and reads no environment file, so it can be
shared by the CLI, tests, and seed startup; duplicate keys, dangling references, unmapped
scenarios, or objects shared by mutually exclusive branches all fail here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.devtools.demo_scenarios import catalog
from app.devtools.demo_scenarios.model import ScenarioSpec


class CatalogError(ValueError):
    """The scenario catalog is self-contradictory; callers show only this class of message."""


@dataclass(frozen=True)
class CatalogSummary:
    accounts: int
    products: int
    trades: int
    reports: int
    cases: int
    conversations: int
    notifications: int
    scenarios: int
    mappings: tuple[str, ...]


def _short(product_key: str) -> str:
    return product_key.removeprefix("product_")


def product_review_case_key(product, index: int) -> str:
    review = product.reviews[index]
    return review.case_key or f"case_review_{_short(product.key)}_{index + 1}"


def product_review_key(product, index: int) -> str:
    review = product.reviews[index]
    return review.key or f"review_{_short(product.key)}_{index + 1}"


def tag_application_key(product, index: int) -> str:
    application = product.tag_apps[index]
    return application.key or f"tag_app_{_short(product.key)}_{index + 1}"


def edit_key(product, index: int) -> str:
    edit = product.edits[index]
    return edit.key or f"edit_{_short(product.key)}_{index + 1}"


def favorite_key(user: str, product) -> str:
    return f"favorite_{user}_{_short(product.key)}"


def agreement_key(trade, round_no: int) -> str:
    return f"agreement_{trade.key.removeprefix('trade_')}_{round_no}"


def confirmation_key(trade, confirmation) -> str:
    return confirmation.key or f"confirmation_{trade.key.removeprefix('trade_')}_{confirmation.confirmer}"


def trade_review_key(trade, review) -> str:
    return review.key or f"review_{trade.key}_{review.reviewer}"


def conversation_key(trade) -> str:
    return f"conversation_{trade.key}"


def message_key(owner_key: str, index: int) -> str:
    """owner_key is trade_* or conversation_*; index starts at 1."""
    return f"message_{owner_key}_{index}"


def product_case_key(product) -> str:
    return f"case_review_{_short(product.key)}"


def object_inventory() -> dict[str, str]:
    """Return all object key -> kind entries in the catalog that a manifest/scenario may reference."""
    inventory: dict[str, str] = {}

    def add(key: str, kind: str) -> None:
        if key in inventory:
            raise CatalogError(f"Duplicate object key: {key}")
        inventory[key] = kind

    for account in catalog.ACCOUNTS:
        add(f"account_{account.key}", "account")
    for category in catalog.CATEGORIES:
        add(category.key, "category")
        for alias in category.aliases:
            add(alias.key, "category_alias")
    for product in catalog.PRODUCTS:
        add(product.key, "product")
        for index, review in enumerate(product.reviews):
            add(product_review_key(product, index), "review_record")
            add(product_review_case_key(product, index), "disposal_case")
        for index, _ in enumerate(product.tag_apps):
            add(tag_application_key(product, index), "tag_application")
        for index, _ in enumerate(product.edits):
            add(edit_key(product, index), "edit_history")
        for comment in product.comments:
            add(comment.key, "comment")
        for user in product.favorites:
            add(favorite_key(user, product), "favorite")
    for trade in catalog.TRADES:
        add(trade.key, "trade")
        for index, _ in enumerate(trade.agreements):
            add(agreement_key(trade, trade.agreements[index].round_no), "agreement")
        for confirmation in trade.confirmations:
            add(confirmation_key(trade, confirmation), "confirmation")
        for review in trade.reviews:
            add(trade_review_key(trade, review), "trade_review")
        add(conversation_key(trade), "conversation")
        for index, _ in enumerate(trade.messages, start=1):
            add(message_key(trade.key, index), "message")
        if trade.case is not None:
            add(trade.case.key, "disposal_case")
    for conversation in catalog.NORMAL_CONVERSATIONS:
        add(conversation.key, "conversation")
        for index, _ in enumerate(conversation.messages, start=1):
            add(message_key(conversation.key, index), "message")
    for report in catalog.REPORTS:
        add(report.key, "report")
        for supplement in report.supplements:
            add(supplement.key, "report_supplement")
        if report.case is not None:
            add(report.case.key, "disposal_case")
    for case in catalog.CASES:
        add(case.key, "disposal_case")
    for restriction in catalog.RESTRICTIONS:
        add(restriction.key, "account_restriction")
    for notification in catalog.NOTIFICATIONS:
        add(notification.key, "notification")
    for avatar in catalog.AVATARS:
        add(avatar.slug, "avatar")
        add(avatar.case.key, "disposal_case")
    return inventory


def _validate_unique_fixture_keys() -> None:
    groups = {
        "accounts": [item.key for item in catalog.ACCOUNTS],
        "categories": [item.key for item in catalog.CATEGORIES],
        "products": [item.key for item in catalog.PRODUCTS],
        "trades": [item.key for item in catalog.TRADES],
        "reports": [item.key for item in catalog.REPORTS],
        "cases": [item.key for item in [*catalog.CASES, *(t.case for t in catalog.TRADES if t.case), *(r.case for r in catalog.REPORTS if r.case), *(a.case for a in catalog.AVATARS)]],
        "restrictions": [item.key for item in catalog.RESTRICTIONS],
        "notifications": [item.key for item in catalog.NOTIFICATIONS],
        "normal conversations": [item.key for item in catalog.NORMAL_CONVERSATIONS],
    }
    for label, keys in groups.items():
        duplicated = [key for key, count in Counter(keys).items() if count > 1]
        if duplicated:
            raise CatalogError(f"Duplicate {label} key: " + ", ".join(sorted(duplicated)))


def _validate_accounts_and_refs() -> None:
    accounts = {item.key: item for item in catalog.ACCOUNTS}
    if not any(item.role == "admin" for item in accounts.values()):
        raise CatalogError("At least one admin account is required")
    categories = {item.key for item in catalog.CATEGORIES}
    tags_by_product = {}
    for product in catalog.PRODUCTS:
        if product.seller not in accounts:
            raise CatalogError(f"Seller for {product.key} does not exist")
        if product.status not in {"pending_review", "rejected", "listed", "in_transaction", "delisted"}:
            raise CatalogError(f"Invalid status for {product.key}")
        if not product.description or len(product.description) < 40:
            raise CatalogError(f"Description for {product.key} is too short; missing usage/condition/delivery information")
        if product.price_cents <= 0:
            raise CatalogError(f"Invalid price for {product.key}")
        unknown = [tag for tag in product.all_tags if tag not in categories]
        if unknown:
            raise CatalogError(f"Unknown category referenced by {product.key}: " + ", ".join(unknown))
        tags_by_product[product.key] = set(product.all_tags)
    if len({product.description for product in catalog.PRODUCTS}) != len(catalog.PRODUCTS):
        raise CatalogError("Product descriptions are mechanically duplicated")
    if len({product.price_cents for product in catalog.PRODUCTS}) < 10:
        raise CatalogError("Product prices are too uniform")

    for trade in catalog.TRADES:
        product = next((item for item in catalog.PRODUCTS if item.key == trade.product), None)
        if product is None:
            raise CatalogError(f"Unknown product referenced by {trade.key}")
        if trade.buyer not in accounts:
            raise CatalogError(f"Buyer for {trade.key} does not exist")
        if product.seller == trade.buyer:
            raise CatalogError(f"Buyer and seller are the same for {trade.key}")
        if trade.status not in {
            "pending_acceptance", "rejected", "withdrawn", "closed", "in_progress",
            "disputed", "abnormal", "terminated", "completed",
        }:
            raise CatalogError(f"Invalid status for {trade.key}")
        rounds = [agreement.round_no for agreement in trade.agreements]
        if rounds != sorted(set(rounds)):
            raise CatalogError(f"Agreement rounds for {trade.key} are not unique or not increasing")
        if trade.current_round is not None:
            current = [agreement for agreement in trade.agreements if agreement.round_no == trade.current_round]
            if not current or current[0].status != "confirmed":
                raise CatalogError(f"current_round for {trade.key} does not point to a confirmed agreement")
        confirmed = [agreement for agreement in trade.agreements if agreement.status == "confirmed"]
        if len(confirmed) > 1:
            raise CatalogError(f"Multiple confirmed agreements exist for {trade.key}")
        if trade.status in {"in_progress", "disputed", "abnormal", "completed", "terminated"} and trade.accepted_days_ago is None:
            raise CatalogError(f"Acceptance time is missing for {trade.key}")
        if trade.status in {"pending_acceptance", "rejected", "withdrawn", "closed"} and trade.accepted_days_ago is not None:
            raise CatalogError(f"Acceptance time is recorded but the trade was not accepted for {trade.key}")
        if trade.frozen and trade.frozen_days_ago is None:
            raise CatalogError(f"Freeze time is missing for {trade.key}")
        if not trade.frozen and trade.frozen_case:
            raise CatalogError(f"A frozen case is linked but the trade is not frozen for {trade.key}")
        for confirmation in trade.confirmations:
            if confirmation.confirmer not in (trade.buyer, product.seller):
                raise CatalogError(f"Confirmer is not a party to {trade.key}")
        for review in trade.reviews:
            if review.reviewer not in (trade.buyer, product.seller):
                raise CatalogError(f"Reviewer is not a party to {trade.key}")
            if not 1 <= review.rating <= 5:
                raise CatalogError(f"Invalid review rating for {trade.key}")
        if trade.status != "completed" and trade.reviews:
            raise CatalogError(f"Review exists but the trade is not completed for {trade.key}")

    for report in catalog.REPORTS:
        if report.reporter not in accounts:
            raise CatalogError(f"Reporter for {report.key} does not exist")
        if report.target_type not in {"product", "comment", "message", "review", "user"}:
            raise CatalogError(f"Invalid target type for {report.key}")
    for restriction in catalog.RESTRICTIONS:
        if restriction.user not in accounts or restriction.created_by not in accounts:
            raise CatalogError(f"User or actor for {restriction.key} does not exist")
        if restriction.status not in {"active", "lifted"}:
            raise CatalogError(f"Invalid status for {restriction.key}")
        if restriction.status == "lifted" and (not restriction.lifted_by or restriction.lifted_days_ago is None):
            raise CatalogError(f"Restriction {restriction.key} is lifted but lift information is missing")
    for notification in catalog.NOTIFICATIONS:
        if notification.user not in accounts:
            raise CatalogError(f"Recipient for {notification.key} does not exist")
        if accounts[notification.user].role == "admin":
            raise CatalogError(f"{notification.key} cannot send a personal notification to an admin")


def _validate_scenarios(inventory: dict[str, str]) -> None:
    by_key: dict[str, ScenarioSpec] = {}
    mapped: set[str] = set()
    for scenario in catalog.SCENARIOS:
        if scenario.key in by_key:
            raise CatalogError(f"Duplicate scenario key: {scenario.key}")
        by_key[scenario.key] = scenario
        if not scenario.title or not scenario.initial_state:
            raise CatalogError(f"{scenario.key} is missing a title or initial state")
        if not scenario.timeline or not scenario.actions or not scenario.expected:
            raise CatalogError(f"{scenario.key} is missing timeline/allowed actions/expected results")
        if len(scenario.checks) < 2:
            raise CatalogError(f"Not enough checks for {scenario.key}")
        if not scenario.mappings:
            raise CatalogError(f"Missing US/UC/SC mappings for {scenario.key}")
        for mapping in scenario.mappings:
            if not (mapping.startswith("US-") or mapping.startswith("UC-") or mapping.startswith("SC-")):
                raise CatalogError(f"Invalid mapping format for {scenario.key}: {mapping}")
            mapped.add(mapping)
        duplicated = [key for key, count in Counter(scenario.objects).items() if count > 1]
        if duplicated:
            raise CatalogError(f"Duplicate objects listed for {scenario.key}: " + ", ".join(duplicated))
        for object_key in scenario.objects:
            if object_key not in inventory:
                raise CatalogError(f"Unknown object {object_key} referenced by {scenario.key}")
        for check in scenario.checks:
            prefix, _, value = check.partition(":")
            if prefix not in {"state", "history", "live"} or not value:
                raise CatalogError(f"Invalid check format for {scenario.key}: {check}")
            if prefix in {"state", "history"} and value not in inventory:
                raise CatalogError(f"Check for {scenario.key} references unknown object {value}")

    missing_us = set(catalog.US_ALL) - mapped
    missing_uc = set(catalog.UC_ALL) - mapped
    missing_sc = set(catalog.SC_ALL) - mapped
    if missing_us or missing_uc or missing_sc:
        raise CatalogError(
            "Scenario mappings do not cover: "
            + ", ".join(sorted(missing_us | missing_uc | missing_sc))
        )

    for scenario in catalog.SCENARIOS:
        for other_key in scenario.exclusive_with:
            if other_key not in by_key:
                raise CatalogError(f"Unknown mutually exclusive scenario {other_key} referenced by {scenario.key}")
            other = by_key[other_key]
            shared = set(scenario.objects) & set(other.objects)
            if shared:
                raise CatalogError(
                    f"Mutually exclusive scenarios {scenario.key} and {other_key} share objects: "
                    + ", ".join(sorted(shared))
                )


def _validate_content() -> None:
    user_messages = [
        message.content
        for trade in catalog.TRADES
        for message in trade.messages
        if message.sender is not None
    ] + [
        message.content
        for conversation in catalog.NORMAL_CONVERSATIONS
        for message in conversation.messages
        if message.sender is not None
    ]
    duplicated = [content for content, count in Counter(user_messages).items() if count > 1]
    if duplicated:
        raise CatalogError("Duplicate user conversations exist: " + "; ".join(duplicated[:3]))
    if any("演示" in product.title for product in catalog.PRODUCTS):
        raise CatalogError('Product titles must not use the "演示" prefix')
    banned_words = ("微信号", "手机号", "身份证", "密码")
    for product in catalog.PRODUCTS:
        text = product.title + product.description
        if any(word in text for word in banned_words):
            raise CatalogError(f"{product.key} contains text that looks like privacy or credentials")
        dimensions = {
            "usage time": any(word in text for word in ("购入", "买了", "用了", "使用", "大二", "去年", "上月", "202")),
            "condition or defects": any(word in text for word in ("划痕", "磕碰", "磨损", "掉漆", "痕迹", "正常", "无坏点", "泛黄", "水垢", "鼓包", "变形", "笔痕", "无缺页", "衰减")),
            "accessories": "附" in text or "无其他配件" in text or "含" in text,
            "delivery place or time": any(word in text for word in ("交付", "自提", "楼下", "门口", "取", "车棚", "看台", "实验楼", "体育馆", "验货", "试机", "试投", "校园内")),
            "price": "元" in text,
        }
        missing = [name for name, present in dimensions.items() if not present]
        if missing:
            raise CatalogError(f"Description for {product.key} is missing: " + ", ".join(missing))


def validate_catalog() -> CatalogSummary:
    _validate_unique_fixture_keys()
    inventory = object_inventory()
    _validate_accounts_and_refs()
    _validate_scenarios(inventory)
    _validate_content()
    mappings = sorted({mapping for scenario in catalog.SCENARIOS for mapping in scenario.mappings})
    return CatalogSummary(
        accounts=len(catalog.ACCOUNTS),
        products=len(catalog.PRODUCTS),
        trades=len(catalog.TRADES),
        reports=len(catalog.REPORTS),
        cases=sum(1 for kind in inventory.values() if kind == "disposal_case"),
        conversations=sum(1 for kind in inventory.values() if kind == "conversation"),
        notifications=len(catalog.NOTIFICATIONS),
        scenarios=len(catalog.SCENARIOS),
        mappings=tuple(mappings),
    )


def scenario_counts() -> dict[str, int]:
    counts: Counter[str] = Counter()
    for scenario in catalog.SCENARIOS:
        counts[scenario.area] += 1
    return dict(sorted(counts.items()))

"""场景目录的静态校验与对象清单。

``validate_catalog()`` 不连数据库、不读环境文件，可被 CLI、测试和 seed 启动前
共用；任何重复 key、悬空引用、未映射场景或互斥分支共用对象都会在这里失败。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.devtools.demo_scenarios import catalog
from app.devtools.demo_scenarios.model import ScenarioSpec


class CatalogError(ValueError):
    """场景目录自相矛盾；调用方只展示本类消息。"""


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
    """owner_key 为 trade_* 或 conversation_*，index 从 1 开始。"""
    return f"message_{owner_key}_{index}"


def product_case_key(product) -> str:
    return f"case_review_{_short(product.key)}"


def object_inventory() -> dict[str, str]:
    """返回目录中可被 manifest/场景引用的全部对象 key -> kind。"""
    inventory: dict[str, str] = {}

    def add(key: str, kind: str) -> None:
        if key in inventory:
            raise CatalogError(f"对象 key 重复：{key}")
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
        "账号": [item.key for item in catalog.ACCOUNTS],
        "分类": [item.key for item in catalog.CATEGORIES],
        "商品": [item.key for item in catalog.PRODUCTS],
        "交易": [item.key for item in catalog.TRADES],
        "举报": [item.key for item in catalog.REPORTS],
        "事项": [item.key for item in [*catalog.CASES, *(t.case for t in catalog.TRADES if t.case), *(r.case for r in catalog.REPORTS if r.case), *(a.case for a in catalog.AVATARS)]],
        "限制": [item.key for item in catalog.RESTRICTIONS],
        "通知": [item.key for item in catalog.NOTIFICATIONS],
        "普通会话": [item.key for item in catalog.NORMAL_CONVERSATIONS],
    }
    for label, keys in groups.items():
        duplicated = [key for key, count in Counter(keys).items() if count > 1]
        if duplicated:
            raise CatalogError(f"{label} key 重复：" + "、".join(sorted(duplicated)))


def _validate_accounts_and_refs() -> None:
    accounts = {item.key: item for item in catalog.ACCOUNTS}
    if not any(item.role == "admin" for item in accounts.values()):
        raise CatalogError("至少需要一个管理员账号")
    categories = {item.key for item in catalog.CATEGORIES}
    tags_by_product = {}
    for product in catalog.PRODUCTS:
        if product.seller not in accounts:
            raise CatalogError(f"{product.key} 的卖家不存在")
        if product.status not in {"pending_review", "rejected", "listed", "in_transaction", "delisted"}:
            raise CatalogError(f"{product.key} 状态非法")
        if not product.description or len(product.description) < 40:
            raise CatalogError(f"{product.key} 描述过短，缺少使用/成色/交付信息")
        if product.price_cents <= 0:
            raise CatalogError(f"{product.key} 价格非法")
        unknown = [tag for tag in product.all_tags if tag not in categories]
        if unknown:
            raise CatalogError(f"{product.key} 引用未知分类：" + "、".join(unknown))
        tags_by_product[product.key] = set(product.all_tags)
    if len({product.description for product in catalog.PRODUCTS}) != len(catalog.PRODUCTS):
        raise CatalogError("商品描述存在机械重复")
    if len({product.price_cents for product in catalog.PRODUCTS}) < 10:
        raise CatalogError("商品价格过于单一")

    for trade in catalog.TRADES:
        product = next((item for item in catalog.PRODUCTS if item.key == trade.product), None)
        if product is None:
            raise CatalogError(f"{trade.key} 引用未知商品")
        if trade.buyer not in accounts:
            raise CatalogError(f"{trade.key} 买方不存在")
        if product.seller == trade.buyer:
            raise CatalogError(f"{trade.key} 买方与卖方相同")
        if trade.status not in {
            "pending_acceptance", "rejected", "withdrawn", "closed", "in_progress",
            "disputed", "abnormal", "terminated", "completed",
        }:
            raise CatalogError(f"{trade.key} 状态非法")
        rounds = [agreement.round_no for agreement in trade.agreements]
        if rounds != sorted(set(rounds)):
            raise CatalogError(f"{trade.key} 约定轮次不唯一或不递增")
        if trade.current_round is not None:
            current = [agreement for agreement in trade.agreements if agreement.round_no == trade.current_round]
            if not current or current[0].status != "confirmed":
                raise CatalogError(f"{trade.key} current_round 未指向 confirmed 约定")
        confirmed = [agreement for agreement in trade.agreements if agreement.status == "confirmed"]
        if len(confirmed) > 1:
            raise CatalogError(f"{trade.key} 同时存在多个 confirmed 约定")
        if trade.status in {"in_progress", "disputed", "abnormal", "completed", "terminated"} and trade.accepted_days_ago is None:
            raise CatalogError(f"{trade.key} 缺少接受时间")
        if trade.status in {"pending_acceptance", "rejected", "withdrawn", "closed"} and trade.accepted_days_ago is not None:
            raise CatalogError(f"{trade.key} 未接受却记录接受时间")
        if trade.frozen and trade.frozen_days_ago is None:
            raise CatalogError(f"{trade.key} 冻结缺少时间")
        if not trade.frozen and trade.frozen_case:
            raise CatalogError(f"{trade.key} 未冻结却关联冻结事项")
        for confirmation in trade.confirmations:
            if confirmation.confirmer not in (trade.buyer, product.seller):
                raise CatalogError(f"{trade.key} 确认人不是交易一方")
        for review in trade.reviews:
            if review.reviewer not in (trade.buyer, product.seller):
                raise CatalogError(f"{trade.key} 评价人不是交易一方")
            if not 1 <= review.rating <= 5:
                raise CatalogError(f"{trade.key} 评价分数非法")
        if trade.status != "completed" and trade.reviews:
            raise CatalogError(f"{trade.key} 未完成却有评价")

    for report in catalog.REPORTS:
        if report.reporter not in accounts:
            raise CatalogError(f"{report.key} 举报人不存在")
        if report.target_type not in {"product", "comment", "message", "review", "user"}:
            raise CatalogError(f"{report.key} 目标类型非法")
    for restriction in catalog.RESTRICTIONS:
        if restriction.user not in accounts or restriction.created_by not in accounts:
            raise CatalogError(f"{restriction.key} 用户或执行人不存在")
        if restriction.status not in {"active", "lifted"}:
            raise CatalogError(f"{restriction.key} 状态非法")
        if restriction.status == "lifted" and (not restriction.lifted_by or restriction.lifted_days_ago is None):
            raise CatalogError(f"{restriction.key} 已解除但缺少解除信息")
    for notification in catalog.NOTIFICATIONS:
        if notification.user not in accounts:
            raise CatalogError(f"{notification.key} 接收人不存在")
        if accounts[notification.user].role == "admin":
            raise CatalogError(f"{notification.key} 不能给管理员发个人通知")


def _validate_scenarios(inventory: dict[str, str]) -> None:
    by_key: dict[str, ScenarioSpec] = {}
    mapped: set[str] = set()
    for scenario in catalog.SCENARIOS:
        if scenario.key in by_key:
            raise CatalogError(f"场景 key 重复：{scenario.key}")
        by_key[scenario.key] = scenario
        if not scenario.title or not scenario.initial_state:
            raise CatalogError(f"{scenario.key} 缺少标题或初始状态")
        if not scenario.timeline or not scenario.actions or not scenario.expected:
            raise CatalogError(f"{scenario.key} 缺少时间线/允许操作/预期")
        if len(scenario.checks) < 2:
            raise CatalogError(f"{scenario.key} 验证项不足")
        if not scenario.mappings:
            raise CatalogError(f"{scenario.key} 缺少 US/UC/SC 映射")
        for mapping in scenario.mappings:
            if not (mapping.startswith("US-") or mapping.startswith("UC-") or mapping.startswith("SC-")):
                raise CatalogError(f"{scenario.key} 映射格式非法：{mapping}")
            mapped.add(mapping)
        duplicated = [key for key, count in Counter(scenario.objects).items() if count > 1]
        if duplicated:
            raise CatalogError(f"{scenario.key} 重复列出对象：" + "、".join(duplicated))
        for object_key in scenario.objects:
            if object_key not in inventory:
                raise CatalogError(f"{scenario.key} 引用未知对象 {object_key}")
        for check in scenario.checks:
            prefix, _, value = check.partition(":")
            if prefix not in {"state", "history", "live"} or not value:
                raise CatalogError(f"{scenario.key} 验证项格式非法：{check}")
            if prefix in {"state", "history"} and value not in inventory:
                raise CatalogError(f"{scenario.key} 验证项引用未知对象 {value}")

    missing_us = set(catalog.US_ALL) - mapped
    missing_uc = set(catalog.UC_ALL) - mapped
    missing_sc = set(catalog.SC_ALL) - mapped
    if missing_us or missing_uc or missing_sc:
        raise CatalogError(
            "场景映射未覆盖："
            + "、".join(sorted(missing_us | missing_uc | missing_sc))
        )

    for scenario in catalog.SCENARIOS:
        for other_key in scenario.exclusive_with:
            if other_key not in by_key:
                raise CatalogError(f"{scenario.key} 引用未知互斥场景 {other_key}")
            other = by_key[other_key]
            shared = set(scenario.objects) & set(other.objects)
            if shared:
                raise CatalogError(
                    f"互斥场景 {scenario.key} 与 {other_key} 共用对象："
                    + "、".join(sorted(shared))
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
        raise CatalogError("存在重复的用户对话：" + "；".join(duplicated[:3]))
    if any("演示" in product.title for product in catalog.PRODUCTS):
        raise CatalogError("商品标题不应带“演示”前缀")
    banned_words = ("微信号", "手机号", "身份证", "密码")
    for product in catalog.PRODUCTS:
        text = product.title + product.description
        if any(word in text for word in banned_words):
            raise CatalogError(f"{product.key} 含疑似隐私或凭据字样")
        dimensions = {
            "使用时间": any(word in text for word in ("购入", "买了", "用了", "使用", "大二", "去年", "上月", "202")),
            "成色或缺陷": any(word in text for word in ("划痕", "磕碰", "磨损", "掉漆", "痕迹", "正常", "无坏点", "泛黄", "水垢", "鼓包", "变形", "笔痕", "无缺页", "衰减")),
            "配件": "附" in text or "无其他配件" in text or "含" in text,
            "交付地点或时间": any(word in text for word in ("交付", "自提", "楼下", "门口", "取", "车棚", "看台", "实验楼", "体育馆", "验货", "试机", "试投", "校园内")),
            "价格": "元" in text,
        }
        missing = [name for name, present in dimensions.items() if not present]
        if missing:
            raise CatalogError(f"{product.key} 描述缺少：" + "、".join(missing))


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

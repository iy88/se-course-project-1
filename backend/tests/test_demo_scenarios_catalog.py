"""共享场景目录的静态回归：不启动服务、不读环境文件。"""
from __future__ import annotations

from collections import Counter

import pytest

from app.devtools.demo_scenarios import catalog
from app.devtools.demo_scenarios.checks import (
    CatalogError,
    object_inventory,
    scenario_counts,
    validate_catalog,
)


def test_catalog_is_consistent_and_covers_all_mappings():
    summary = validate_catalog()
    assert summary.accounts == 19
    assert summary.products >= 30
    assert summary.trades >= 20
    assert summary.reports >= 8
    assert summary.scenarios >= 40
    for mapping in catalog.US_ALL + catalog.UC_ALL + catalog.SC_ALL:
        assert mapping in summary.mappings


def test_scenarios_have_distinct_live_objects_and_exclusive_branches():
    for scenario in catalog.SCENARIOS:
        assert len(set(scenario.objects)) == len(scenario.objects)
        assert any(check.startswith("live:") for check in scenario.checks), scenario.key
        assert scenario.live_start or scenario.note, scenario.key
        for other_key in scenario.exclusive_with:
            other = next(item for item in catalog.SCENARIOS if item.key == other_key)
            assert not (set(scenario.objects) & set(other.objects)), (scenario.key, other_key)


def test_content_is_varied_and_campus_specific():
    descriptions = [product.description for product in catalog.PRODUCTS]
    assert len(set(descriptions)) == len(descriptions)
    assert min(len(item) for item in descriptions) >= 40
    prices = {product.price_cents for product in catalog.PRODUCTS}
    assert len(prices) >= 15
    assert 8800 not in prices or len([p for p in catalog.PRODUCTS if p.price_cents == 8800]) == 1
    assert all("元" in product.description for product in catalog.PRODUCTS)
    assert not any(product.title.startswith("演示") for product in catalog.PRODUCTS)

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
    assert len(user_messages) == len(set(user_messages))
    senders = Counter(
        message.sender
        for trade in catalog.TRADES
        for message in trade.messages
        if message.sender is not None
    )
    assert len(senders) >= 8, "对话应覆盖多个真实角色"


def test_report_targets_cover_all_types_and_product_entries_are_traceable():
    assert {report.target_type for report in catalog.REPORTS} == {
        "product", "comment", "message", "review", "user",
    }
    inventory = object_inventory()
    referenced = {key for scenario in catalog.SCENARIOS for key in scenario.objects}
    for product in catalog.PRODUCTS:
        assert product.key in inventory
        # 商品既可作为场景入口，也可通过场景引用的交易/商品关联出现。
        assert product.key in referenced or any(trade.product == product.key for trade in catalog.TRADES)
    for trade in catalog.TRADES:
        assert trade.key in referenced
    account_keys = {f"account_{account.key}" for account in catalog.ACCOUNTS}
    for report in catalog.REPORTS:
        assert report.key in referenced
        assert report.target in inventory or f"account_{report.target}" in account_keys


def test_catalog_rejects_unknown_scenario_object():
    original = catalog.SCENARIOS
    broken = original[0]
    object.__setattr__(broken, "objects", (*broken.objects, "does-not-exist"))
    try:
        with pytest.raises(CatalogError):
            validate_catalog()
    finally:
        object.__setattr__(broken, "objects", tuple(item for item in broken.objects if item != "does-not-exist"))


def test_signature_stable_and_area_counts():
    assert catalog.catalog_signature() == catalog.catalog_signature()
    counts = scenario_counts()
    assert sum(counts.values()) == len(catalog.SCENARIOS)
    assert counts.get("product", 0) >= 5
    assert counts.get("trade", 0) >= 10
    assert counts.get("report", 0) >= 6

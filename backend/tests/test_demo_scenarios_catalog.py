"""共享场景目录的静态回归：不启动服务、不读环境文件。"""
from __future__ import annotations


import pytest

from app.devtools.demo_scenarios import catalog
from app.devtools.demo_scenarios.checks import CatalogError, object_inventory, validate_catalog


def test_scenarios_have_distinct_live_objects_and_exclusive_branches():
    for scenario in catalog.SCENARIOS:
        assert len(set(scenario.objects)) == len(scenario.objects)
        assert any(check.startswith("live:") for check in scenario.checks), scenario.key
        assert scenario.live_start or scenario.note, scenario.key
        for other_key in scenario.exclusive_with:
            other = next(item for item in catalog.SCENARIOS if item.key == other_key)
            assert not (set(scenario.objects) & set(other.objects)), (scenario.key, other_key)




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

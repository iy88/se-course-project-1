"""Shared package for the persistent demo scenario catalog (used by seed, read-only verification, and regression tests)."""

from app.devtools.demo_scenarios.checks import (
    CatalogError,
    CatalogSummary,
    object_inventory,
    scenario_counts,
    validate_catalog,
)
from app.devtools.demo_scenarios.model import ScenarioSpec

__all__ = [
    "CatalogError",
    "CatalogSummary",
    "ScenarioSpec",
    "object_inventory",
    "scenario_counts",
    "validate_catalog",
]

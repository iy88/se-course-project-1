"""Dotenv resource/timeout budgets cannot silently accept NaN or infinity."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


@pytest.mark.parametrize("field", [
    "db_pool_timeout_seconds", "redis_control_pool_timeout_seconds",
    "realtime_outbox_admission_cache_seconds", "outbox_run_time_budget_seconds",
    "taskiq_task_timeout_seconds", "taskiq_retry_delay_seconds",
    "taskiq_scheduler_send_timeout_seconds",
])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_timeout_and_cache_budgets_are_finite(field, value):
    values = get_settings().model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        Settings(**values)

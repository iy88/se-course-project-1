"""Stable job failure categories visible to Taskiq retry middleware."""

from __future__ import annotations


class RetryableJobError(RuntimeError):
    """A transient dependency failure that Taskiq may retry.

    Only this type is listed in ``SmartRetryMiddleware(types_of_exceptions=...)``
    so programming/validation errors are not retried forever. The message is a
    stable category (class name), never a payload, token or connection string.
    """

    def __init__(self, category: str) -> None:
        super().__init__(f"retryable job failure: {category}")
        self.category = category


class TerminalJobError(RuntimeError):
    """A non-retryable job failure (bad configuration/contract)."""

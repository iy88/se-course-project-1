"""Bounded Redis connection pool with safe acquisition observability.

`BlockingConnectionPool` gives a finite queue wait (`timeout`) instead of
waiting forever for a control slot. The observed wrapper records only duration
and stable failure categories; it never records URLs, keys, tokens or payloads.
Acquisition time can include creating/validating a connection, so it is not a
pure queue-wait measurement.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from redis.asyncio import BlockingConnectionPool
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.observability import counters


class ObservedBlockingConnectionPool(BlockingConnectionPool):
    def __init__(self, *args: Any, metric_prefix: str = "redis", **kwargs: Any) -> None:
        if "max_connections" in kwargs and kwargs["max_connections"] <= 0:
            raise ValueError("Redis max_connections must be positive")
        self._metric_prefix = metric_prefix
        super().__init__(*args, **kwargs)

    async def get_connection(self, *args: Any, **kwargs: Any):
        started = time.perf_counter()
        try:
            connection = await super().get_connection(*args, **kwargs)
        except asyncio.CancelledError:
            counters.observe(self._metric_prefix + ".acquire_ms", (time.perf_counter() - started) * 1000)
            counters.incr(self._metric_prefix + ".acquire_cancelled")
            raise
        except (TimeoutError, RedisTimeoutError):
            counters.observe(self._metric_prefix + ".acquire_ms", (time.perf_counter() - started) * 1000)
            counters.incr(self._metric_prefix + ".acquire_timeout")
            raise
        except RedisConnectionError as exc:
            counters.observe(self._metric_prefix + ".acquire_ms", (time.perf_counter() - started) * 1000)
            # redis-py reports blocking-pool exhaustion as
            # ConnectionError("No connection available."). Keep it distinct
            # from transport failure for backpressure alerting.
            if "no connection available" in str(exc).lower():
                counters.incr(self._metric_prefix + ".acquire_exhausted")
            else:
                counters.incr(self._metric_prefix + ".acquire_failed")
            raise
        except Exception:
            counters.observe(self._metric_prefix + ".acquire_ms", (time.perf_counter() - started) * 1000)
            counters.incr(self._metric_prefix + ".acquire_failed")
            raise
        counters.observe(self._metric_prefix + ".acquire_ms", (time.perf_counter() - started) * 1000)
        return connection

"""ACKed task storage is reclaimed, while pending/unread work stays intact.

Redis 8.2+ provides atomic XACKDEL ACKED for this policy. A thin broker storage
adapter may use that server primitive; it must not implement a second consumer,
claim, retry or scheduling loop. Reference: https://redis.io/docs/latest/commands/xackdel/
"""

import secrets

import pytest
import redis.asyncio as aioredis
from app.core.config import get_settings
from app.jobs.broker import build_bundle


@pytest.mark.parametrize("other_group", [False, True])
async def test_ack_reclaims_only_fully_acknowledged_work(other_group):
    nonce = secrets.token_hex(8)
    settings = get_settings().model_copy(update={
        "taskiq_queue_name": f"tasks:retention-probe:{nonce}",
        "taskiq_consumer_group": f"tasks:retention-group:{nonce}",
    })
    bundle = build_bundle(settings)
    broker = bundle.broker
    queue, group = broker.queue_name, broker.consumer_group_name
    client = aioredis.Redis.from_url(settings.redis_url, decode_responses=True, max_connections=1)
    second = f"{group}:second"
    try:
        await client.xgroup_create(queue, group, id="0-0", mkstream=True)
        if other_group:
            await client.xgroup_create(queue, second, id="0-0")
        ids = [await client.xadd(queue, {"data": f"test-{i}"}) for i in range(3)]
        await client.xreadgroup(group, "policy-probe", {queue: ">"}, count=2)
        # Use the actual Taskiq broker acknowledgement hook against Redis.
        await broker._ack_generator(ids[0], queue)()
        rows = await client.xrange(queue)
        if other_group:
            # A second group has not consumed it yet: retain the payload.
            assert [row[0] for row in rows] == ids
            await client.xreadgroup(second, "policy-probe-2", {queue: ">"}, count=1)
            await broker._ack_generator(ids[0], queue)()  # idempotent repeat in group 1
            async with aioredis.Redis(connection_pool=broker.connection_pool) as raw:
                await raw.xackdel(queue, second, ids[0], ref_policy="ACKED")
        assert [row[0] for row in await client.xrange(queue)] == ids[1:]
        assert (await client.xpending(queue, group))["pending"] == 1
        await broker._ack_generator(ids[1], queue)()
        # The third message was never consumed; ACK cleanup must preserve it.
        assert ids[2] in [row[0] for row in await client.xrange(queue)]
    finally:
        await client.delete(queue)
        await client.aclose()
        await broker.connection_pool.disconnect()
        if bundle.retry_source is not None:
            await bundle.retry_source.shutdown()
        await bundle.scheduler_heartbeat.close()

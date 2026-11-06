"""Optional read-only PostgreSQL connection/lock telemetry for load tests.

Separate from the Rust HTTP driver; no SQL text, URLs or credentials are exported.
Each sample uses a fresh READ ONLY transaction. Existing output is never replaced.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import load_settings, resolve_env_file


async def collect(connection) -> dict:
    states = dict((await connection.execute(text("""
        SELECT coalesce(state, 'unknown'), count(*) FROM pg_stat_activity
        WHERE datname=current_database() AND usename=current_user
          AND pid<>pg_backend_pid() GROUP BY state
    """))).all())
    waiting = (await connection.execute(text("""
        SELECT count(*) FROM pg_stat_activity
        WHERE datname=current_database() AND usename=current_user
          AND pid<>pg_backend_pid() AND wait_event_type='Lock'
    """))).scalar_one()
    locks = (await connection.execute(text("""
        SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid=l.relation
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=current_schema() AND NOT l.granted
          AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database())
    """))).scalar_one()
    return {'timestamp_utc': datetime.now(UTC).isoformat(), 'session_states': states,
            'sessions_waiting_for_lock': waiting, 'ungranted_schema_relation_locks': locks}


async def monitor(settings, output: Path, duration: float, interval: float) -> None:
    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0,
        connect_args={'server_settings': {'search_path': f'"{settings.database_schema}"',
            'default_transaction_read_only': 'on', 'application_name': 'campus-load-monitor'}})
    stop = asyncio.Event()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: stop.set())
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            start = time.monotonic()
            while not stop.is_set() and time.monotonic() - start < duration:
                try:
                    async with engine.connect() as connection:
                        async with connection.begin():
                            sample = await collect(connection)
                except Exception as exc:  # safe, bounded diagnostic; never export DB messages
                    sample = {'timestamp_utc': datetime.now(UTC).isoformat(), 'error_type': type(exc).__name__}
                sample['elapsed_seconds'] = time.monotonic() - start
                stream.write(json.dumps(sample) + '\n')
                stream.flush()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except TimeoutError:
                    pass
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        await engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default='.env.dev')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--duration-seconds', type=float, default=1800)
    parser.add_argument('--interval-seconds', type=float, default=1)
    args = parser.parse_args(argv)
    try:
        selected = resolve_env_file(args.env_file)
        if selected.name == '.env.prod':
            raise ValueError('only dev/test monitoring is permitted')
        settings = load_settings(selected)
        if settings.environment not in {'dev', 'test'} or not settings.database_url.startswith('postgresql+asyncpg:'):
            raise ValueError('requires dev/test PostgreSQL')
        if not 0 < args.duration_seconds <= 86400 or not 0.2 <= args.interval_seconds <= 60:
            raise ValueError('invalid sampling interval/duration')
        asyncio.run(monitor(settings, args.output.expanduser().absolute(), args.duration_seconds, args.interval_seconds))
        return 0
    except Exception as exc:
        print(f'load monitor failed: {type(exc).__name__}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

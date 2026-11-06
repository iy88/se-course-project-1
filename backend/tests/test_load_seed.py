"""Fixture integrity, idempotence, recovery and fail-closed guards (SQLite/local)."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.test_demo_seed import _write_env, _create_schema


def test_load_seed_idempotence_recovery_and_corruption(tmp_path):
    env, url, storage, manifest = _write_env(tmp_path)
    _create_schema(url, existing=False)
    command = [sys.executable, '-m', 'app.manage', 'load-seed', '--env-file', str(env),
               '--manifest', str(manifest), '--users', '3', '--products', '12']
    def run(*extra):
        return subprocess.run(command + list(extra), cwd=Path(__file__).resolve().parents[1],
                              env={**os.environ, 'APP_ENV_FILE': str(env)}, capture_output=True, text=True)
    result = run()
    assert result.returncode == 0, result.stderr
    before = json.loads(manifest.read_text())
    assert before['complete'] and len(before['accounts']) == 3 and len(before['product_ids']) == 12
    assert len(list(storage.rglob('*.jpg'))) == 12
    with sqlite3.connect(tmp_path / 'demo.db') as db:
        assert db.execute('select count(*) from products').fetchone()[0] == 12
        assert db.execute('select count(*) from stored_objects where state="committed"').fetchone()[0] == 12
        assert db.execute('select count(*) from messages').fetchone()[0] == 60
        snapshots = [json.loads(row[0]) for row in db.execute('select content_json from review_records')]
        assert all(set(s) == {'title', 'description', 'price_cents', 'images', 'tags'} for s in snapshots)
        assert db.execute('select count(distinct description) from products').fetchone()[0] > 1
        assert len({p.read_bytes() for p in storage.rglob('*.jpg')}) == 8
        assert db.execute('select count(distinct category_id) from product_tags t join products p on p.id=t.product_id where p.seller_id=?',
                          (before['accounts'][0]['id'],)).fetchone()[0] > 1
    assert run().returncode == 0
    assert json.loads(manifest.read_text()) == before
    # Simulate a successful commit followed by loss of final manifest response.
    before['complete'] = False
    manifest.write_text(json.dumps(before))
    assert run().returncode == 0
    assert json.loads(manifest.read_text())['complete']
    assert run('--verify-only').returncode == 0
    assert run('--products', '13').returncode != 0
    image = next(storage.rglob('*.jpg'))
    image.write_bytes(b'corrupt')
    assert run('--verify-only').returncode != 0
    # The seed must not overwrite a different existing object after DB reset/rollback.
    with sqlite3.connect(tmp_path / 'demo.db') as db:
        db.execute('delete from users')
    manifest_data = json.loads(manifest.read_text())
    manifest_data['complete'] = False
    manifest.write_text(json.dumps(manifest_data))
    assert run().returncode != 0
    assert image.read_bytes() == b'corrupt'


def test_load_seed_rejects_prod_filename_and_bad_scale(tmp_path):
    env, _url, _storage, manifest = _write_env(tmp_path)
    prod = tmp_path / '.env.prod'
    prod.write_text(env.read_text())
    command = [sys.executable, '-m', 'app.manage', 'load-seed', '--env-file', str(prod),
               '--manifest', str(manifest)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0 and 'only permits dev/test' in result.stderr
    assert not manifest.exists()
    result = subprocess.run(command + ['--users', '2'], capture_output=True, text=True)
    assert result.returncode != 0 and 'require 3 <=' in result.stderr

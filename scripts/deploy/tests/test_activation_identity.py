"""A successful probe must identify the selected release, including rollback."""

import argparse
import io
import json
import runpy
import urllib.request
from pathlib import Path

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "activate.py"))


class Response(io.BytesIO):
    status = 200


def activator(tmp_path):
    args = argparse.Namespace(
        deploy_root=str(tmp_path), release_id="b" * 40 + "-2",
        systemctl="/usr/bin/systemctl",
    )
    value = MODULE["Activator"](args)
    value.cwd.mkdir(parents=True)
    return value


def fake_probe(monkeypatch, body):
    class Opener:
        def open(self, *_args, **_kwargs):
            return Response(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())


def test_rollback_checks_previous_release_identity(tmp_path, monkeypatch):
    value = activator(tmp_path)
    previous = tmp_path / "releases" / ("a" * 40 + "-1") / "backend"
    previous.mkdir(parents=True)
    value.cwd = previous
    fake_probe(monkeypatch, {
        "status": "ready", "role": "ws", "release_id": previous.parent.name,
        "protocol_version": 2, "degraded": False,
    })
    assert value._http_health("ws")[0]


def test_split_probe_rejects_wrong_role_and_missing_identity(tmp_path, monkeypatch):
    value = activator(tmp_path)
    fake_probe(monkeypatch, {"status": "ready"})
    assert not value._http_health("ws")[0]
    fake_probe(monkeypatch, {
        "status": "ready", "role": "api", "release_id": value.args.release_id,
        "protocol_version": 2, "degraded": False,
    })
    assert not value._http_health("ws")[0]


def test_activation_requires_ready_dependencies(tmp_path, monkeypatch):
    value = activator(tmp_path)
    fake_probe(monkeypatch, {
        "status": "degraded", "role": "ws", "release_id": value.args.release_id,
        "protocol_version": 2, "degraded": True,
    })
    assert not value._http_health("ws")[0]

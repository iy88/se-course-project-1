"""Deployment activation tests using fake systemctl/health (no real services)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "activate.py"
BACKUP = "/var/backups/se-course-project1/predeploy-test"


def make_release(root: Path, release_id: str) -> Path:
    release = root / "releases" / release_id
    (release / "backend" / "app").mkdir(parents=True)
    (release / "backend" / "app" / "main.py").write_text("")
    (release / "backend" / ".env.prod").write_text("")
    (release / "deploy").mkdir()
    (release / "deploy" / "activate.py").write_text(SCRIPT.read_text())
    (release / "deploy" / "preflight.py").write_text("")
    (release / "release.txt").write_text(f"release_id={release_id}\n")
    (release / "PREPARED").write_text("ok\n")
    (release / "MIGRATED").write_text(f"backup_dir={BACKUP}\n")
    return release


def fake_commands(tmp_path: Path) -> tuple[Path, Path, Path]:
    log = tmp_path / "systemctl.log"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text('#!/bin/sh\necho "$@" >> "' + str(log) + '"\nexit 0\n')
    systemctl.chmod(0o755)
    health_log = tmp_path / "health.log"
    fail_role = tmp_path / "fail-once-role"
    health = tmp_path / "health"
    health.write_text(f'''#!/bin/sh
role="$1"
echo "$role" >> "{health_log}"
if [ -f "{fail_role}" ] && [ "$(cat "{fail_role}")" = "$role" ] && [ "$PWD" != "{tmp_path}/deploy/releases/{"a" * 40}-1/backend" ]; then
  exit 1
fi
exit 0
''')
    health.chmod(0o755)
    return systemctl, health, log


def run(root: Path, release_id: str, mode: str, systemctl: Path, health: Path,
        *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--release-id", release_id, "--backup-dir", BACKUP,
         "--mode", mode, "--deploy-root", str(root), "--systemctl", str(systemctl),
         "--health-command", str(health), "--health-timeout", "2", *extra],
        capture_output=True, text=True, timeout=60, check=False,
    )


def mark_active(release: Path) -> None:
    (release / "ACTIVATED").write_text("mode=split\nservices=scheduler,worker,ws,api\n")


def test_old_topology_is_refused_before_stopping_services(tmp_path):
    root = tmp_path / "deploy"
    previous = make_release(root, "a" * 40 + "-1")
    (previous / "ACTIVATED").write_text("mode=combined\n")
    make_release(root, "b" * 40 + "-2")
    (root / "current").symlink_to(previous)
    systemctl, health, log = fake_commands(tmp_path)
    result = run(root, "b" * 40 + "-2", "split", systemctl, health)
    assert result.returncode == 1
    assert not log.exists()
    assert (root / "current").resolve() == previous


def test_split_activation_starts_worker_scheduler_ws_api_and_records_health(tmp_path):
    root = tmp_path / "deploy"
    new = make_release(root, "c" * 40 + "-3")
    systemctl, health, log = fake_commands(tmp_path)
    result = run(root, "c" * 40 + "-3", "split", systemctl, health)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert "stop se-course-project1-backend.service" not in calls
    for suffix in ("scheduler", "worker", "ws", "api"):
        assert f"start se-course-project1-{suffix}.service" in calls
    activated = (new / "ACTIVATED").read_text()
    assert "services=scheduler,worker,ws,api" in activated
    assert "roles=scheduler,worker,ws,api" in activated
    assert "protocol=" in activated


def test_failed_health_rolls_back_to_previous_release(tmp_path):
    root = tmp_path / "deploy"
    previous = make_release(root, "a" * 40 + "-1")
    mark_active(previous)
    new = make_release(root, "d" * 40 + "-4")
    (root / "current").symlink_to(previous)
    systemctl, health, log = fake_commands(tmp_path)
    fail_role = tmp_path / "fail-once-role"
    fail_role.write_text("api")
    result = run(root, "d" * 40 + "-4", "split", systemctl, health)
    assert result.returncode == 1
    assert os.path.realpath(root / "current") == os.path.realpath(previous)
    assert not (new / "ACTIVATED").exists()
    assert (new / "ACTIVATION_FAILED").is_file()
    calls = log.read_text().splitlines()
    assert calls.count("start se-course-project1-api.service") == 2


def test_start_failure_rolls_back(tmp_path):
    root = tmp_path / "deploy"
    previous = make_release(root, "a" * 40 + "-1")
    mark_active(previous)
    new = make_release(root, "e" * 40 + "-5")
    (root / "current").symlink_to(previous)
    _, health, log = fake_commands(tmp_path)
    # First start (scheduler) fails once, forcing the rollback path.
    failing = tmp_path / "failing-systemctl"
    failing.write_text(f'''#!/bin/sh
echo "$@" >> "{log}"
if [ "$1" = "start" ] && [ ! -f "{tmp_path}/started" ]; then
  touch "{tmp_path}/started"
  exit 1
fi
exit 0
''')
    failing.chmod(0o755)
    result = run(root, "e" * 40 + "-5", "split", failing, health)
    assert result.returncode == 1
    assert os.path.realpath(root / "current") == os.path.realpath(previous)
    assert not (new / "ACTIVATED").exists()
    assert (new / "ACTIVATION_FAILED").is_file()


def test_invalid_release_identity_is_refused_before_switch(tmp_path):
    root = tmp_path / "deploy"
    make_release(root, "a" * 40 + "-1")
    (root / "current").symlink_to(root / "releases" / ("a" * 40 + "-1"))
    systemctl, health, _ = fake_commands(tmp_path)
    result = run(root, "not-a-release", "split", systemctl, health)
    assert result.returncode == 1
    assert not (tmp_path / "systemctl.log").exists()


def test_split_upgrade_stops_all_previous_split_roles(tmp_path):
    root = tmp_path / "deploy"
    previous = make_release(root, "a" * 40 + "-1")
    mark_active(previous)
    make_release(root, "f" * 40 + "-6")
    (root / "current").symlink_to(previous)
    systemctl, health, log = fake_commands(tmp_path)
    result = run(root, "f" * 40 + "-6", "split", systemctl, health)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    for suffix in ("api", "ws", "scheduler", "worker"):
        assert f"stop se-course-project1-{suffix}.service" in calls
    for suffix in ("scheduler", "worker", "ws", "api"):
        assert f"start se-course-project1-{suffix}.service" in calls
    assert "stop se-course-project1-backend.service" not in calls


def test_sudoers_grants_only_exact_unit_actions():
    text = (Path(__file__).resolve().parents[1] / "sudoers" / "se-course-project1-activate.sudoers").read_text()
    assert "activate *" not in text
    assert "/usr/bin/systemctl start se-course-project1-api.service" in text
    assert "systemctl *" not in text
    assert "NOPASSWD: ALL" not in text


def test_nginx_fragment_keeps_static_host_and_hides_ws_query_log():
    text = (Path(__file__).resolve().parents[1] / "nginx" / "se-course-project1-routes.conf").read_text()
    assert "access_log off;" in text
    assert "$request" not in text
    assert "location /ws" in text
    assert not any(line.strip().startswith("server {") for line in text.splitlines())
    assert "client_max_body_size 10m" in text


def test_systemd_units_are_non_root_and_allow_managed_python_reads():
    root = Path(__file__).resolve().parents[1] / "systemd"
    for unit in root.glob("*.service"):
        text = unit.read_text()
        assert "User=deploy" in text
        assert "ProtectHome=read-only" in text
        assert "ReadWritePaths=/srv/se-course-project1/current/backend" in text
        assert "APP_RUNTIME_ROLE=" in text


def test_rollback_stop_failure_is_reported_and_restore_still_attempted(tmp_path):
    root = tmp_path / "deploy"
    previous = make_release(root, "a" * 40 + "-1")
    mark_active(previous)
    new = make_release(root, "b" * 40 + "-7")
    (root / "current").symlink_to(previous)
    _systemctl, health, log = fake_commands(tmp_path)
    failing = tmp_path / "failing-stop"
    failing.write_text(f'''#!/bin/sh
echo "$@" >> "{log}"
if [ "$1" = "start" ]; then touch "{tmp_path}/started"; fi
if [ -f "{tmp_path}/started" ] && [ "$1" = "stop" ] && [ "$2" = "se-course-project1-ws.service" ]; then
  exit 1
fi
exit 0
''')
    failing.chmod(0o755)
    # Force activation failure after starts so rollback must stop the new set.
    (tmp_path / "fail-once-role").write_text("api")
    result = run(root, "b" * 40 + "-7", "split", failing, health)
    assert result.returncode == 1
    assert os.path.realpath(root / "current") == os.path.realpath(previous)
    failed = (new / "ACTIVATION_FAILED").read_text()
    assert "rollback incomplete" in failed
    assert "stop failures" in failed
    calls = log.read_text().splitlines()
    assert calls.count("start se-course-project1-api.service") == 2

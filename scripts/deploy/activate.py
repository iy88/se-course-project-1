#!/usr/bin/env python3
"""Fixed-purpose release activation (install as /usr/local/sbin/...).

Supports the legacy combined service and the split jobs/ws/api service set. It
does not deploy artifacts, run migrations or roll back PostgreSQL/Redis. It:

1. takes the existing activation lock;
2. verifies release identity, PREPARED/MIGRATED markers and the backup path;
3. switches the ``current`` symlink atomically;
4. starts the selected service set and waits for each role's readiness CLI;
5. on any failure stops the new set, restores the previous symlink and starts
   the previous service set, then records ACTIVATION_FAILED without writing a
   false ACTIVATED marker.

The systemd units, sudoers and Nginx split config are administrator-installed
one-time prerequisites; this script never writes them.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SERVICE_PREFIX = "se-course-project1"
# New split release: native Taskiq worker/scheduler plus WS/API. The previous
# transitional split used a single jobs service and remains stoppable for
# rollback.
SPLIT_SERVICES = ("scheduler", "worker", "ws", "api")
LEGACY_SPLIT_SERVICES = ("jobs", "ws", "api")
KNOWN_SERVICES = ("backend", "scheduler", "worker", "ws", "api", "jobs")
RELEASE_ID_RE = re.compile(r"^[0-9a-f]{40}-[0-9]+$")
BACKUP_RE = re.compile(r"^/var/backups/se-course-project1/predeploy-[A-Za-z0-9-]+$")


class ActivationError(RuntimeError):
    pass


class Activator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.deploy_root = Path(args.deploy_root)
        self.release_dir = self.deploy_root / "releases" / args.release_id
        self.current = self.deploy_root / "current"
        self.lock_path = self.deploy_root / ".activation.lock"
        self.systemctl = args.systemctl
        self.cwd = self.release_dir / "backend"

    def log(self, message: str) -> None:
        print(f"[activate] {message}", flush=True)

    def _run(self, command: list[str], *, cwd: Path | None = None, timeout: int = 60,
             check: bool = True) -> subprocess.CompletedProcess:
        self.log("+ " + " ".join(command))
        if getattr(self.args, "dry_run", False):
            return subprocess.CompletedProcess(command, 0, "", "")
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        if check and completed.returncode != 0:
            raise ActivationError(
                f"command failed ({completed.returncode}): {' '.join(command[:3])}: "
                f"{(completed.stderr or completed.stdout).strip()[:400]}"
            )
        return completed

    def service(self, name: str) -> str:
        # The existing production single-process unit is named "backend"; keep
        # that identity so combined rollback does not require an admin rename.
        suffix = "backend" if name == "combined" else name
        return f"{SERVICE_PREFIX}-{suffix}.service"

    def systemd(self, action: str, name: str, *, check: bool = True) -> None:
        command = [self.systemctl, action, self.service(name)]
        if getattr(self.args, "sudo", False):
            # sudoers allows only these exact unit/action tuples, never a
            # wildcard or an arbitrary script argument.
            command = ["sudo", "-n", *command]
        self._run(command, check=check)

    def deactivate(self, mode: str, *, services: tuple[str, ...] | None = None,
                   check: bool = True) -> list[str]:
        names = services or (("combined",) if mode == "combined" else SPLIT_SERVICES)
        failures: list[str] = []
        for name in reversed(names):
            try:
                self.systemd("stop", name)
            except ActivationError as exc:
                failures.append(f"{name}: {exc}")
                self.log(f"stop failed for {name}: {type(exc).__name__}")
        if check and failures:
            raise ActivationError("failed to stop previous service set: " + "; ".join(failures))
        return failures

    def activate_services(self, mode: str, *, services: tuple[str, ...] | None = None) -> None:
        names = services or (("combined",) if mode == "combined" else SPLIT_SERVICES)
        for name in names:
            self.systemd("start", name)

    def health_roles(self, mode: str, *, services: tuple[str, ...] | None = None) -> list[str]:
        names = services or (("combined",) if mode == "combined" else SPLIT_SERVICES)
        roles = ["combined" if name == "backend" else name for name in names]
        # Dependencies/consumers first; HTTP roles last so readiness reflects a
        # complete role set rather than a half-started one.
        order = ["scheduler", "worker", "jobs", "combined", "ws", "api"]
        return [role for role in order if role in roles]

    def _health_command(self, role: str) -> list[str]:
        if getattr(self.args, "health_command", None):
            return [getattr(self.args, "health_command", None), role]
        return [self.args.python, "-m", "app.manage", "health", "--role", role]

    def _env_value(self, key: str, default: str) -> str:
        try:
            for line in (self.cwd / ".env.prod").read_text(encoding="utf-8").splitlines():
                name, _, value = line.partition("=")
                if name.strip() == key:
                    return value.strip().strip('"').strip("'")
        except OSError:
            pass
        return default

    def _http_health(self, role: str) -> tuple[bool, str]:
        host = self._env_value("API_HOST" if role in {"combined", "api"} else
                               ("WS_HOST" if role == "ws" else "JOBS_HOST"), "127.0.0.1")
        port_key = "API_PORT" if role in {"combined", "api"} else ("WS_PORT" if role == "ws" else "JOBS_PORT")
        port = self._env_value(port_key, {"combined": "8001", "api": "8001", "ws": "8002", "jobs": "8003"}[role])
        path = "/api/health" if role in {"combined", "api"} else "/health/ready"
        url = f"http://{host}:{port}{path}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(url, timeout=3) as response:
                body = json.load(response)
                expected_release = self.cwd.parent.name
                release = str(body.get("release_id") or "")
                body_role = str(body.get("role") or "")
                legacy_combined = role == "combined" and not release and not body_role
                if response.status != 200 or str(body.get("status")) not in {"ok", "ready"}:
                    return False, f"{url} status={response.status} body_status={body.get('status')}"
                if body.get("degraded") is True:
                    return False, f"{url} degraded"
                if not legacy_combined and (release != expected_release or body_role != role):
                    return False, f"{url} role/release identity mismatch"
                if role == "combined" and body.get("status") != "ok":
                    return False, f"{url} combined status is not ok"
                return True, url
        except Exception as exc:  # noqa: BLE001
            return False, f"{url} {type(exc).__name__}"

    def wait_health(self, role: str, timeout: int) -> None:
        deadline = time.monotonic() + timeout
        env = dict(os.environ)
        env["APP_ENV_FILE"] = ".env.prod"
        env["APP_RUNTIME_ROLE"] = role
        last = "no probe"
        if getattr(self.args, "dry_run", False):
            self.log(f"would wait for {role} readiness")
            return
        while time.monotonic() < deadline:
            hook = getattr(self.args, "health_command", None)
            if hook or role in {"worker", "scheduler"}:
                command = ([hook, role] if hook else
                           [self.args.python, "-m", "app.manage", "health", "--role", role])
                completed = subprocess.run(
                    command, cwd=self.cwd, env=env,
                    capture_output=True, text=True, timeout=30, check=False,
                )
                ok = completed.returncode == 0
                last = (completed.stdout or completed.stderr).strip()[-500:]
            else:
                ok, last = self._http_health(role)
            if ok:
                mode = "cli" if (hook or role in {"worker", "scheduler"}) else "http"
                self.log(f"{role} readiness ok ({last if mode == 'cli' else 'http'})")
                return
            time.sleep(1.5)
        raise ActivationError(f"{role} readiness failed: {last}")

    def verify_process(self, role: str) -> None:
        if not getattr(self.args, "verify_process", False):
            return
        completed = self._run(
            [self.systemctl, "show", self.service(role), "--property=MainPID", "--value"],
            check=True,
        )
        try:
            pid = int(completed.stdout.strip())
        except ValueError:
            raise ActivationError(f"{role} has no MainPID") from None
        if pid <= 0:
            raise ActivationError(f"{role} has no MainPID")
        proc_cwd = Path(f"/proc/{pid}/cwd").resolve()
        expected = self.cwd.resolve()
        if proc_cwd != expected:
            raise ActivationError(f"{role} cwd is not the activated release")

    def validate_release(self) -> None:
        if not RELEASE_ID_RE.fullmatch(self.args.release_id):
            raise ActivationError("invalid release id")
        if not self.release_dir.is_dir():
            raise ActivationError("release directory is missing")
        for marker in ("PREPARED", "MIGRATED"):
            if not (self.release_dir / marker).is_file():
                raise ActivationError(f"missing {marker} marker")
        release_txt = (self.release_dir / "release.txt").read_text(encoding="utf-8", errors="replace")
        if f"release_id={self.args.release_id}" not in release_txt:
            raise ActivationError("release identity mismatch")
        migrated = (self.release_dir / "MIGRATED").read_text(encoding="utf-8", errors="replace")
        if f"backup_dir={self.args.backup_dir}" not in migrated:
            raise ActivationError("MIGRATED does not reference the supplied backup")
        if not BACKUP_RE.fullmatch(self.args.backup_dir):
            raise ActivationError("backup path is outside the approved directory")
        if not (self.cwd / ".env.prod").is_file():
            raise ActivationError("release .env.prod is missing")
        for relative in ("backend/app/main.py", "deploy/activate.py", "deploy/preflight.py"):
            if not (self.release_dir / relative).is_file():
                raise ActivationError(f"release is missing {relative}")

    def previous(self) -> tuple[str | None, str, tuple[str, ...], str]:
        if not self.current.is_symlink():
            return None, "combined", ("combined",), "0"
        target = Path(os.readlink(self.current))
        if not target.is_absolute():
            target = (self.current.parent / target).resolve()
        previous_id = target.name
        mode = "combined"
        services: tuple[str, ...] | None = None
        protocol = "unknown"
        activated = target / "ACTIVATED"
        if activated.is_file():
            for line in activated.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, value = line.partition("=")
                value = value.strip()
                if key == "mode" and value:
                    mode = value
                elif key == "protocol" and value:
                    protocol = value
                elif key == "services" and value:
                    parsed = tuple(name for name in value.split(",") if name in KNOWN_SERVICES)
                    if parsed:
                        services = parsed
        if services is None:
            # Legacy ACTIVATED markers predate services=. A split marker from
            # the transitional release therefore maps to jobs/ws/api.
            services = ("combined",) if mode == "combined" else LEGACY_SPLIT_SERVICES
        return previous_id, mode, services, protocol

    def switch(self, release_id: str) -> None:
        temp = self.deploy_root / f".activate-{os.getpid()}"
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()
        target = self.deploy_root / "releases" / release_id
        self.log(f"current -> {target}")
        if getattr(self.args, "dry_run", False):
            return
        temp.symlink_to(target)
        os.replace(temp, self.current)

    def run(self) -> int:
        self.validate_release()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            # Identify the previous set only after taking the activation lock.
            previous_id, previous_mode, previous_services, previous_protocol = self.previous()
            if previous_id == self.args.release_id:
                raise ActivationError("release is already current")
            new_services = (("combined",) if self.args.mode == "combined" else SPLIT_SERVICES)
            try:
                self.log(f"activating {self.args.release_id} mode={self.args.mode} "
                         f"previous={previous_id} previous_services={','.join(previous_services)}")
                self.deactivate(previous_mode, services=previous_services)
                self.switch(self.args.release_id)
                self.activate_services(self.args.mode, services=new_services)
                for role in self.health_roles(self.args.mode, services=new_services):
                    self.verify_process(role)
                    self.wait_health(role, self.args.health_timeout)
            except Exception as exc:  # noqa: BLE001 - rollback must cover any failure
                self.log(f"activation failed: {type(exc).__name__}: {exc}")
                failure = exc
                try:
                    self._rollback(previous_id, previous_mode, previous_services,
                                   new_services=new_services)
                except Exception as rollback_exc:  # noqa: BLE001 - preserve both failures
                    failure = ActivationError(f"{exc}; rollback failed: {type(rollback_exc).__name__}: {rollback_exc}")
                self._write_failed(failure)
                return 1
            self._write_activated(previous_id, previous_mode, previous_services, previous_protocol)
            self.log("activation complete")
        return 0

    def _rollback(self, previous_id: str | None, previous_mode: str,
                  previous_services: tuple[str, ...], *, new_services: tuple[str, ...]) -> None:
        stop_failures = self.deactivate(self.args.mode, services=new_services, check=False)
        if previous_id is None:
            if stop_failures:
                raise ActivationError("new service stop failures with no previous release: " + "; ".join(stop_failures))
            self.log("no previous release; leaving the service set stopped")
            return
        self.switch(previous_id)
        self.cwd = (self.deploy_root / "releases" / previous_id / "backend").resolve()
        restore_error: Exception | None = None
        try:
            self.activate_services(previous_mode, services=previous_services)
            for role in self.health_roles(previous_mode, services=previous_services):
                self.verify_process(role)
                self.wait_health(role, self.args.health_timeout)
        except Exception as exc:  # noqa: BLE001 - report both stop and restore failures
            restore_error = exc
        if stop_failures or restore_error is not None:
            detail = []
            if stop_failures:
                detail.append("stop failures: " + "; ".join(stop_failures))
            if restore_error is not None:
                detail.append(f"restore failed: {type(restore_error).__name__}: {restore_error}")
            raise ActivationError("rollback incomplete: " + "; ".join(detail))

    def _write_failed(self, exc: BaseException) -> None:
        if getattr(self.args, "dry_run", False):
            return
        path = self.release_dir / "ACTIVATION_FAILED"
        path.write_text(
            f"release_id={self.args.release_id}\nmode={self.args.mode}\n"
            f"failed_at={dt.datetime.now(dt.UTC).isoformat()}\n"
            f"error={type(exc).__name__}: {str(exc)[:500]}\n",
            encoding="utf-8",
        )

    def _write_activated(self, previous_id: str | None, previous_mode: str,
                         previous_services: tuple[str, ...], previous_protocol: str) -> None:
        if getattr(self.args, "dry_run", False):
            return
        new_services = (("combined",) if self.args.mode == "combined" else SPLIT_SERVICES)
        roles = self.health_roles(self.args.mode, services=new_services)
        protocol = self._env_value("REALTIME_PROTOCOL_VERSION", "2")
        (self.release_dir / "ACTIVATED").write_text(
            f"release_id={self.args.release_id}\nmode={self.args.mode}\n"
            f"protocol={protocol}\n"
            f"roles={','.join(roles)}\n"
            f"services={','.join(new_services)}\n"
            f"previous_release={previous_id or ''}\nprevious_mode={previous_mode}\n"
            f"previous_protocol={previous_protocol}\n"
            f"previous_services={','.join(previous_services)}\n"
            f"backup_dir={self.args.backup_dir}\n"
            f"activated_at={dt.datetime.now(dt.UTC).isoformat()}\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--mode", choices=("combined", "split"), required=True)
    parser.add_argument("--deploy-root", default="/srv/se-course-project1")
    parser.add_argument("--systemctl", default="/usr/bin/systemctl", help="test hook; production uses /usr/bin/systemctl")
    parser.add_argument("--sudo", action="store_true", help="run the fixed systemctl commands through sudo -n")
    parser.add_argument("--python", default=".venv/bin/python")
    parser.add_argument("--health-command", default=None, help="test hook: command receiving role argument")
    parser.add_argument("--health-timeout", type=int, default=90)
    parser.add_argument("--verify-process", action="store_true", help="require systemd MainPID cwd to equal the release")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        return Activator(args).run()
    except ActivationError as exc:
        print(f"activation refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

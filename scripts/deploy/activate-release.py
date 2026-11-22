#!/usr/bin/env python3
"""Deploy a prepared Project1 v2 release as the unprivileged SSH account."""

import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


ROOT = Path("/srv/se-course-project1-v2")
UPSTREAM = Path("/etc/nginx/snippets/project1-v2-upstream.conf")
JAVA = "/opt/project1-v2/java/bin/java"
SYSTEMCTL = "/usr/bin/systemctl"
RUNTIME_GROUP = "se-project1-v2"
SITES = {"mobile.v2.cm.iy88.site": "user-web", "admin.v2.cm.iy88.site": "admin-web"}


def run(*command, capture=False):
    return subprocess.run(command, check=True, text=True, capture_output=capture).stdout


def systemctl(action, unit):
    if action == "is-active":
        run(SYSTEMCTL, action, "--quiet", unit)
    else:
        run("sudo", "-n", SYSTEMCTL, action, unit)


def replace_link(link, target):
    pending = link.with_name(link.name + ".next")
    pending.unlink(missing_ok=True)
    pending.symlink_to(target)
    pending.replace(link)


def instance(unit):
    name = unit.removesuffix(".service").removeprefix("project1-v2-")
    return name.removeprefix("api@").replace("@", "-")


def smoke(url, host=None):
    options = ("-H", f"Host: {host}") if host else ()
    return run("curl", "-fsS", "--noproxy", "*", "--max-time", "3", *options, url, capture=True)


def stop_units(units):
    failed = []
    for unit in reversed(units):
        try:
            systemctl("stop", unit)
        except subprocess.CalledProcessError:
            failed.append(unit)
    if failed:
        raise RuntimeError("Unable to stop: " + ", ".join(failed))


def start_and_check(units, release, instances):
    for unit in units:
        replace_link(instances / instance(unit), release)
        systemctl("start", unit)

    for unit in units:
        if unit.startswith("project1-v2-api@"):
            url = f"http://127.0.0.1:{instance(unit)}"
            deadline = time.monotonic() + 75
            while True:
                try:
                    health = json.loads(smoke(url + "/actuator/health"))
                    if not isinstance(health, dict) or health.get("status") != "UP":
                        raise RuntimeError(f"API is still starting: {unit}")
                    check_api(url)
                    break
                except (ValueError, RuntimeError, subprocess.CalledProcessError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
        systemctl("is-active", unit)


def check_sites(release):
    for host, frontend in SITES.items():
        expected = (release / frontend / "index.html").read_text(encoding="utf-8")
        if smoke("http://127.0.0.1/", host) != expected:
            raise RuntimeError(f"Nginx served an unexpected frontend release for {host}")
        check_api("http://127.0.0.1", host)


def check_api(url, host=None):
    data = json.loads(smoke(url + "/api/v1/hello", host))
    if not isinstance(data, dict) or not data.get("message"):
        raise RuntimeError(f"Invalid API response at {url}")


def maintenance(release, command, config, *args):
    run(JAVA, "-jar", str(release / "backend/maintenance.jar"), "db", command,
        "--env-file", str(config), *args)


def activate(release, state):
    shared = ROOT / "shared"
    instances = ROOT / "instances"
    current = state / "current"
    inventory = shared / ".env.deploy"
    config = shared / ".env.maintenance.prod"
    renderer = release / "deploy/render-runtime.py"
    units = run(sys.executable, str(renderer), str(inventory), "units", capture=True)
    upstream = run(sys.executable, str(renderer), str(inventory), "upstream", capture=True)
    if upstream != UPSTREAM.read_text(encoding="utf-8"):
        raise RuntimeError("Installed Nginx upstream differs from .env.deploy")

    previous = current.resolve(strict=True) if current.is_symlink() else None
    if previous and (previous.parent != (ROOT / "releases").resolve()
                     or (previous / ".units").read_text(encoding="utf-8") != units):
        raise RuntimeError("Reconcile the installed topology before releasing")
    if release.resolve() == previous:
        raise RuntimeError("The candidate is already active")

    # The deploy login belongs to the runtime group so each snapshot can be shared with the service.
    run("install", "-m", "0640", "-g", RUNTIME_GROUP,
        str(shared / ".env.prod"), str(release / "backend/.env.prod"))
    (release / ".units").write_text(units, encoding="utf-8")
    backup = state / "backups" / (release.name + ".pgdump")
    candidate_units = sorted(units.splitlines(), key=lambda unit: unit == "project1-v2-scheduler.service")
    migration_started = False
    try:
        stop_units(candidate_units)
        maintenance(release, "backup", config, "--backup-file", str(backup))
        migration_started = True
        maintenance(release, "migrate", config)
        start_and_check(candidate_units, release, instances)
        replace_link(current, release)
        check_sites(release)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as failure:
        try:
            stop_units(candidate_units)
            if previous:
                replace_link(current, previous)
                if migration_started:
                    maintenance(previous, "validate", config)
                start_and_check(candidate_units, previous, instances)
                check_sites(previous)
                print(f"ROLLED_BACK_RELEASE={previous.name}", file=sys.stderr)
            elif current.is_symlink():
                current.unlink()
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as recovery:
            raise RuntimeError(f"Deployment failed: {failure}; recovery stopped: {recovery}") from recovery
        raise
    print(f"ACTIVATED_RELEASE={release.name}")


def interrupt(_number, _frame):
    raise RuntimeError("Deployment interrupted")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or not re.fullmatch(r"[0-9a-f]{40}-[0-9]+", sys.argv[1]):
            raise RuntimeError("Expected a release ID")
        release = ROOT / "releases" / sys.argv[1]
        if not (release / ".prepared").is_file():
            raise RuntimeError("Candidate has not been prepared")
        state = ROOT / "state"
        os.umask(0o077)
        signal.signal(signal.SIGHUP, interrupt)
        signal.signal(signal.SIGTERM, interrupt)
        with (state / ".deployment.lock").open("a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            activate(release, state)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        sys.exit(1)

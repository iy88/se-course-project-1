#!/usr/bin/env python3
"""Run the Project1 API, scheduler, workers and frontend development servers."""

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

if os.name == "posix":
    import fcntl

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "var/dev"
PID_FILE = RUNTIME / "dev.pid"
LOG_FILE = RUNTIME / "dev.log"
DEFAULT_WORKERS = 2
SHUTDOWN_SECONDS = 30


def signal_group(process, signum):
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def stop_services(services):
    for _, process in services:
        signal_group(process, signal.SIGTERM)
    deadline = time.monotonic() + SHUTDOWN_SECONDS
    for _, process in services:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            signal_group(process, signal.SIGKILL)
            process.wait()


def service_commands(env_file, workers):
    backend = ROOT / "backend"
    frontend = ROOT / "frontend"
    jar = backend / "backend-app/target/backend-app-0.0.1-SNAPSHOT.jar"
    if not jar.is_file():
        raise ValueError("build the backend first with mvn -f backend/pom.xml install")
    if not (frontend / "node_modules/.bin/rsbuild").is_file():
        raise ValueError("install frontend dependencies first with pnpm --dir frontend install --frozen-lockfile")
    for executable in ("java", "node"):
        if shutil.which(executable) is None:
            raise ValueError(f"{executable} was not found on PATH")

    env_file = (env_file if env_file is not None else backend / ".env.dev").expanduser().resolve()
    if not env_file.is_file():
        raise ValueError(f"environment file does not exist: {env_file}")
    backend_command = ["java", "-jar", str(jar), f"--env-file={env_file}"]

    return (
        ("api", backend_command, backend),
        ("scheduler", [*backend_command, "--spring.profiles.active=delivery-scheduler"], backend),
        *((f"worker-{number}", [*backend_command, "--spring.profiles.active=delivery-worker"], backend)
          for number in range(1, workers + 1)),
        ("frontend", ["node", "dev.mjs"], frontend),
    )


def supervise(pid_file, env_file, workers):
    services = []
    shutdown_signal = None

    def request_shutdown(signum, _frame):
        nonlocal shutdown_signal
        shutdown_signal = signum

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    try:
        for name, command, directory in service_commands(env_file, workers):
            if shutdown_signal is not None:
                break
            print(f"Starting {name}…", flush=True)
            process = subprocess.Popen(command, cwd=directory, start_new_session=True)
            services.append((name, process))

        if shutdown_signal is None:
            pid_file.seek(0)
            pids = [str(os.getpid()), *(f"{name}={process.pid}" for name, process in services)]
            pid_file.write(("\n".join(pids) + "\n").encode())
            pid_file.flush()

        while shutdown_signal is None:
            for name, process in services:
                code = process.poll()
                if code is not None:
                    print(f"{name} exited ({code}). Stopping development services.", flush=True)
                    return code if code > 0 else 1
            time.sleep(0.2)
        return 128 + shutdown_signal
    finally:
        stop_services(services)


def try_lock(pid_file):
    try:
        fcntl.flock(pid_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def read_pid(pid_file):
    pid_file.seek(0)
    value = pid_file.readline().strip()
    if not value.isdigit() or int(value) <= 1:
        raise RuntimeError(f"Could not read the active supervisor PID from {PID_FILE}")
    return int(value)


def start(env_file, workers):
    with PID_FILE.open("a+b") as pid_file:
        if not try_lock(pid_file):
            print(f"Already running (PID {read_pid(pid_file)}).")
            return
        service_commands(env_file, workers)
        pid_file.truncate(0)
        command = [sys.executable, str(Path(__file__).resolve()), "_supervise", str(pid_file.fileno()), str(workers)]
        if env_file is not None:
            command.append(str(env_file))
        with LOG_FILE.open("ab") as output:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True, pass_fds=(pid_file.fileno(),), env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            pid_file.seek(0)
            if pid_file.readline().strip() == str(process.pid).encode():
                print(f"Started (PID {process.pid}). Log: {LOG_FILE}")
                return
            time.sleep(0.1)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=SHUTDOWN_SECONDS + 5)
        raise RuntimeError(f"Development services did not start. See {LOG_FILE}")


def stop():
    with PID_FILE.open("a+b") as pid_file:
        if try_lock(pid_file):
            pid_file.truncate(0)
            print("Not running.")
            return

        pid = read_pid(pid_file)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + SHUTDOWN_SECONDS + 5
        while time.monotonic() < deadline:
            if try_lock(pid_file):
                pid_file.truncate(0)
                print(f"Stopped (PID {pid}).")
                return
            time.sleep(0.1)
        raise RuntimeError(f"Supervisor {pid} did not stop. See {LOG_FILE}")


def status():
    with PID_FILE.open("a+b") as pid_file:
        if try_lock(pid_file):
            print("Not running.")
            return 1
        print(f"Running (PID {read_pid(pid_file)}). Log: {LOG_FILE}")
        for line in pid_file:
            name, _, pid = line.decode().strip().partition("=")
            print(f"  {name} (PID {pid})")
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart", "status"))
    parser.add_argument("--env-file", type=Path, help="Override the default backend/.env.dev configuration file")
    parser.add_argument("--workers", type=int, help=f"Number of worker processes (default: {DEFAULT_WORKERS})")
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("this launcher requires macOS or Linux")
    if args.action in ("stop", "status") and (args.env_file is not None or args.workers is not None):
        parser.error("--env-file and --workers are available with start or restart")
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be at least 1")
    workers = args.workers if args.workers is not None else DEFAULT_WORKERS

    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (RUNTIME / "control.lock").open("ab") as control:
        fcntl.flock(control, fcntl.LOCK_EX)
        if args.action == "status":
            return status()
        if args.action == "restart":
            service_commands(args.env_file, workers)
        if args.action in ("stop", "restart"):
            stop()
        if args.action in ("start", "restart"):
            start(args.env_file, workers)
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) >= 4 and sys.argv[1] == "_supervise":
            env_file = Path(sys.argv[4]) if len(sys.argv) == 5 else None
            with os.fdopen(int(sys.argv[2]), "r+b", buffering=0) as pid_file:
                raise SystemExit(supervise(pid_file, env_file, int(sys.argv[3])))
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error)) from error

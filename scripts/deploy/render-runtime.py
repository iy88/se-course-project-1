#!/usr/bin/env python3
"""Render the systemd inventory and proxy configuration from .env.deploy."""

import argparse
from pathlib import Path
import re


KEYS = {"DEPLOY_API_PORTS", "DEPLOY_WORKER_COUNT"}


def read_inventory(path):
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or name not in KEYS or name in values:
            raise ValueError(f"Invalid or duplicate deployment setting on line {number}")
        values[name] = value.strip()
    if values.keys() != KEYS:
        raise ValueError("Required deployment settings: " + ", ".join(sorted(KEYS - values.keys())))

    ports = tuple(parse_number(value.strip(), 65535) for value in values["DEPLOY_API_PORTS"].split(","))
    if min(ports) < 1024 or len(ports) != len(set(ports)):
        raise ValueError("API ports must be unique and within 1024–65535")
    workers = parse_number(values["DEPLOY_WORKER_COUNT"], 65535)
    return ports, workers


def parse_number(value, maximum):
    if not re.fullmatch(r"[1-9][0-9]{0,4}", value) or int(value) > maximum:
        raise ValueError(f"Expected a decimal integer within 1–{maximum}")
    return int(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("format", choices=("upstream", "units", "sudoers"))
    parser.add_argument("--deploy-user", help="Account granted unit access in the sudoers output")
    args = parser.parse_args()
    if args.format == "sudoers" and not re.fullmatch(r"[a-z_][a-z0-9_-]*", args.deploy_user or ""):
        parser.error("sudoers requires a valid --deploy-user")
    try:
        ports, workers = read_inventory(args.config)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")

    if args.format == "upstream":
        for port in ports:
            print(f"server 127.0.0.1:{port};")
        return

    units = [f"project1-v2-api@{port}.service" for port in ports]
    units.append("project1-v2-scheduler.service")
    units.extend(f"project1-v2-worker@{index}.service" for index in range(1, workers + 1))
    if args.format == "units":
        print("\n".join(units))
        return

    for unit in units:
        commands = ", ".join(f"/usr/bin/systemctl {action} {unit}" for action in ("start", "stop", "restart"))
        print(f"{args.deploy_user} ALL=(root) NOPASSWD: {commands}")


if __name__ == "__main__":
    main()

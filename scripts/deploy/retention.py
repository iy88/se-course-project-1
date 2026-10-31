#!/usr/bin/env python3
"""Production retention. Preview by default; fixed paths, root-owned installation."""
import argparse
import fcntl
import re
import shutil
import time
from contextlib import ExitStack
from pathlib import Path

RELEASE_NAME = re.compile(r"[0-9a-f]{40}-[0-9]+")
BACKUP_NAME = re.compile(r"predeploy-[A-Za-z0-9-]+")
DAY = 86400


def metadata(path):
    if path.is_symlink():
        raise RuntimeError(f"Symlink marker refused: {path}")
    if not path.is_file():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def directories(root, pattern):
    return [p for p in root.iterdir()
            if pattern.fullmatch(p.name) and not p.is_symlink() and p.is_dir()]


def plan(root, backups, now):
    releases = root / "releases"
    link = root / "current"
    if not link.is_symlink():
        raise RuntimeError("current must be a symlink")
    current = link.resolve(strict=True)
    items = directories(releases, RELEASE_NAME)
    if current not in items:
        raise RuntimeError("current is outside the release directory")
    active = metadata(current / "ACTIVATED")
    previous = Path(active.get("previous_release", ""))
    if previous not in items or previous == current:
        raise RuntimeError("Missing or invalid previous release; refusing cleanup")
    successful = sorted(
        [p for p in items if (p / "ACTIVATED").is_file()],
        key=lambda p: (p / "ACTIVATED").stat().st_mtime, reverse=True,
    )
    keep = set(successful[:5]) | {current, previous}
    # A seven-day grace period also protects preparation/migration in progress.
    remove = [p for p in items if p not in keep and now - p.stat().st_mtime > 7 * DAY]
    retained = set(items) - set(remove)
    protected_backups = set()
    for release in retained:
        for marker in ("MIGRATED", "ACTIVATED"):
            value = metadata(release / marker).get("backup_dir")
            if value:
                target = Path(value)
                if target.parent != backups or not BACKUP_NAME.fullmatch(target.name):
                    raise RuntimeError(f"Invalid backup reference: {release}")
                protected_backups.add(target)
    complete = sorted(
        [p for p in directories(backups, BACKUP_NAME)
         if (p / "COMPLETE").is_file() and not (p / "COMPLETE").is_symlink()],
        key=lambda p: (p / "COMPLETE").stat().st_mtime, reverse=True,
    )
    protected_backups.update(complete[:10])
    old_backups = [p for p in complete if p not in protected_backups
                   and now - (p / "COMPLETE").stat().st_mtime > 30 * DAY]
    # Unknown names, symlinks and incomplete backups are never deleted.
    return remove, old_backups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = Path("/srv/se-course-project1")
    backups = Path("/var/backups/se-course-project1")
    with ExitStack() as stack:
        for directory in (root, root / "releases", backups):
            if directory.is_symlink() or not directory.is_dir():
                raise RuntimeError(f"Invalid directory: {directory}")
        # Match the existing activation and backup scripts' flock files.
        for path in (root / ".activation.lock", backups / ".backup.lock"):
            if path.is_symlink():
                raise RuntimeError(f"Symlink lock refused: {path}")
            handle = stack.enter_context(path.open("a"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        releases, old_backups = plan(root, backups, time.time())
        for path in releases + old_backups:
            print(f"{'DELETE' if args.execute else 'WOULD_DELETE'} {path}", flush=True)
            if args.execute:
                shutil.rmtree(path)
        print(f"Retention {'executed' if args.execute else 'preview'}: "
              f"releases={len(releases)}, backups={len(old_backups)}")


if __name__ == "__main__":
    main()

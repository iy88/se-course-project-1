"""One-shot acceptance identity seed: prepares eight logical roles in this run's isolated space and cleans up on exit.

Command::

    cd backend
    .venv/bin/python -m tests.acceptance_real.seed --run-id <run_id>

Design constraints:

- Reads only backend ``.env.dev``; uses isolated SQLite or a validated fixed test PostgreSQL
  target per configuration; never reads ``.env.prod``.
- Each isolated space uses independent identities; operations are idempotent within a space,
  and the standalone CLI cleans up when it exits.
- Never overwrites/resets a user's changed email, display name, password, or ban status;
  changes are reported and preserved.
- Passwords are random and written only to a 0600 private credentials file; stdout prints
  only paths and masked identifiers.
- Prepares identities only; creates no categories, products, trades, reports, or other
  business-flow data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.private_files import protect_private
from app.core.private_files import require_private as validate_private_file
from app.devtools._support import (
    DevConfig,
    GuardError,
    SeedError,
    credentials_lock,
    is_undefined_table,
    load_dev_config,
    make_async_engine,
    probe_database,
    write_private_json,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
ACCEPTANCE_ROOT = REPO_ROOT / "var" / "acceptance-real"
SEED_ROOT = ACCEPTANCE_ROOT / "seed"
SEED_DOMAIN = "acceptance.example.com"
SEED_VERSION = 2


@dataclass(frozen=True)
class SeedIdentity:
    key: str
    email: str
    label: str
    role: str


# Canonical roles: two admins, two buyers, two sellers, an outsider, and a rate-limit actor.
CANONICAL_IDENTITIES: tuple[SeedIdentity, ...] = (
    SeedIdentity("admin", "", "验收管理员", "admin"),
    SeedIdentity("admin2", "", "验收管理员2", "admin"),
    SeedIdentity("buyer", "", "验收买方", "user"),
    SeedIdentity("buyer2", "", "验收买方2", "user"),
    SeedIdentity("seller", "", "验收卖方", "user"),
    SeedIdentity("seller2", "", "验收卖方2", "user"),
    SeedIdentity("outsider", "", "验收第三方", "user"),
    SeedIdentity("commenter", "", "验收评论限频", "user"),
)


def normalize_run_id(run_id: str) -> str:
    value = re.sub(r"[^a-z0-9]", "", run_id.lower())
    if not value:
        raise SeedError("run_id must not be empty or contain only separators")
    return value[:32]


def identities_for_run(run_id: str) -> tuple[SeedIdentity, ...]:
    normalized = normalize_run_id(run_id)
    tag = normalized[:24] + "-" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8]
    return tuple(
        SeedIdentity(
            key=identity.key,
            email=f"dsh-accept-{identity.key}-{tag}@{SEED_DOMAIN}",
            label=identity.label,
            role=identity.role,
        )
        for identity in CANONICAL_IDENTITIES
    )


def credentials_path_for_run(run_id: str, root: Path = SEED_ROOT) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", run_id):
        raise SeedError("run_id allows only letters, digits, dots, underscores, and hyphens, length 1-64")
    return root / run_id / "identities.json"


@dataclass(frozen=True)
class SeedAccount:
    key: str
    id: int
    email: str
    display_name: str
    role: str
    password: str = field(repr=False)
    status: str = "normal"


@dataclass(frozen=True)
class SeedCredentials:
    version: int
    fingerprint: str
    run_id: str
    created_at: str
    accounts: Mapping[str, SeedAccount]


@dataclass(frozen=True)
class SeedSummary:
    created: tuple[str, ...]
    existing: tuple[str, ...]
    preserved: tuple[str, ...]
    would_create: tuple[str, ...]
    ready: bool
    check_only: bool
    credentials_path: Path
    fingerprint: str
    accounts: Mapping[str, SeedAccount]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _new_password() -> str:
    return secrets.token_urlsafe(32)


def _validate_fingerprint(value: str) -> str:
    if len(value) < 16:
        raise SeedError("Credentials file lacks a valid seed fingerprint; check manually; do not reset automatically")
    try:
        int(value, 16)
    except ValueError:
        raise SeedError("Credentials file seed fingerprint has an invalid format; check manually; do not reset automatically") from None
    return value


def _account_from_record(key: str, raw: Any) -> SeedAccount:
    if not isinstance(raw, dict):
        raise SeedError(f"Credentials file account record has an invalid format ({key}); check manually")
    try:
        account_id = int(raw["id"])
        email = str(raw["email"])
        display_name = str(raw["display_name"])
        role = str(raw["role"])
        password = str(raw["password"])
    except (KeyError, TypeError, ValueError):
        raise SeedError(f"Credentials file account fields are missing ({key}); check manually") from None
    status = str(raw.get("status") or "normal")
    if account_id <= 0 or not email or not display_name or role not in {"admin", "user"} or not password:
        raise SeedError(f"Credentials file account fields are invalid ({key}); check manually")
    return SeedAccount(
        key=key,
        id=account_id,
        email=email,
        display_name=display_name,
        role=role,
        password=password,
        status=status,
    )


def load_credentials(
    path: Path,
    *,
    require_private: bool = True,
    identities: Sequence[SeedIdentity] | None = None,
) -> SeedCredentials | None:
    """Read any number of identities; when identities is passed, all of their keys must exist.

    The old implementation accepted only the fixed admin/buyer/seller trio; this version
    supports custom multi-identity sets shared by humans and automation.
    """
    if not path.exists():
        return None
    if require_private:
        validate_private_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SeedError("Credentials file cannot be read or is corrupted; check manually; do not reset automatically") from None
    if not isinstance(data, dict) or int(data.get("version", 0)) != SEED_VERSION:
        raise SeedError("Credentials file version is unsupported; check manually; do not reset automatically")
    fingerprint = _validate_fingerprint(str(data.get("fingerprint", "")))
    raw_accounts = data.get("accounts")
    if not isinstance(raw_accounts, dict):
        raise SeedError("Credentials file lacks accounts; check manually; do not reset automatically")
    accounts: dict[str, SeedAccount] = {}
    required = [identity.key for identity in identities] if identities is not None else list(raw_accounts)
    for key in required:
        raw = raw_accounts.get(key)
        if raw is None:
            raise SeedError(f"Credentials file lacks an account record ({key}); check manually; do not reset automatically")
        accounts[key] = _account_from_record(key, raw)
    return SeedCredentials(
        version=SEED_VERSION,
        fingerprint=fingerprint,
        run_id=str(data.get("run_id", "")),
        created_at=str(data.get("created_at", "")),
        accounts=accounts,
    )


def _credentials_payload(
    *,
    fingerprint: str,
    run_id: str,
    created_at: str,
    accounts: Mapping[str, SeedAccount],
) -> dict[str, Any]:
    return {
        "version": SEED_VERSION,
        "fingerprint": fingerprint,
        "run_id": run_id,
        "created_at": created_at,
        "accounts": {
            key: {
                "id": account.id,
                "email": account.email,
                "display_name": account.display_name,
                "role": account.role,
                "password": account.password,
                "status": account.status,
            }
            for key, account in accounts.items()
        },
    }


async def _load_users(
    session: AsyncSession, *, emails: Sequence[str], ids: Sequence[int]
) -> tuple[dict[str, Any], dict[int, Any]]:
    from app.models.user import User

    conditions = []
    if emails:
        conditions.append(col(User.email).in_(list(emails)))
    if ids:
        conditions.append(col(User.id).in_(list(ids)))
    if not conditions:
        return {}, {}
    query = select(User)
    if len(conditions) == 1:
        query = query.where(conditions[0])
    else:
        query = query.where(or_(*conditions))
    result = await session.exec(query)
    users = list(result.all())
    return {user.email: user for user in users}, {user.id: user for user in users}


async def seed_identities_core(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    identities: Sequence[SeedIdentity],
    credentials_path: Path,
    run_id: str,
    check_only: bool = False,
) -> SeedSummary:
    """Run the seed on the caller's session; depends on no global configuration and touches no business data."""
    from app.core.security import hash_password, verify_password
    from app.models.user import User

    existing_credentials = load_credentials(credentials_path, require_private=False)
    fingerprint = existing_credentials.fingerprint if existing_credentials else secrets.token_hex(16)
    existing_accounts = dict(existing_credentials.accounts) if existing_credentials else {}
    created_at = existing_credentials.created_at if existing_credentials and existing_credentials.created_at else _utc_now()
    recorded_run_id = existing_credentials.run_id if existing_credentials else ""
    if recorded_run_id and recorded_run_id != run_id:
        raise SeedError("Credentials file run_id does not match this run; refusing reuse; use the matching run_id or a new credentials file")

    created: list[str] = []
    existing: list[str] = []
    preserved: list[str] = []
    would_create: list[str] = []
    accounts: dict[str, SeedAccount] = dict(existing_accounts)

    async with session_factory() as session:
        # The engine sets the validated sandbox search_path.
        ids = [account.id for account in existing_accounts.values()]
        users_by_email, users_by_id = await _load_users(
            session,
            emails=[identity.email for identity in identities],
            ids=ids,
        )

        for identity in identities:
            account = existing_accounts.get(identity.key)
            user = users_by_email.get(identity.email)
            by_id = users_by_id.get(account.id) if account else None

            if user is None and by_id is not None:
                # The account for the recorded ID still exists but the user changed its email; preserve it without resetting.
                preserved.append(identity.key)
                continue

            if account is not None and (account.email != identity.email or account.role != identity.role):
                raise SeedError(
                    f"Credentials file does not match this run's canonical identity definition ({identity.key}); refusing adoption"
                )

            if user is None:
                if account is not None:
                    # A record exists under this name but the database account is gone: do not silently recreate it; leave it for manual handling.
                    preserved.append(identity.key)
                    continue
                if check_only:
                    would_create.append(identity.key)
                    continue
                password = _new_password()
                new_user = User(
                    email=identity.email,
                    display_name=identity.label,
                    password_hash=hash_password(password),
                    role=identity.role,
                )
                session.add(new_user)
                await session.flush()
                accounts[identity.key] = SeedAccount(
                    key=identity.key,
                    id=int(new_user.id),
                    email=identity.email,
                    display_name=identity.label,
                    role=identity.role,
                    password=password,
                )
                created.append(identity.key)
                continue

            if account is None:
                raise SeedError(
                    f"Found a non-seed account with the same name ({identity.key}); refusing adoption; credentials are missing or were not created by this seed"
                )

            # Existing account: all fields and the password hash must match the credentials file to count as unchanged.
            unchanged = (
                int(account.id) == int(user.id)
                and user.email == identity.email
                and account.email == identity.email
                and user.display_name == account.display_name
                and user.role == account.role
                and account.role == identity.role
                and user.status == "normal"
                and account.status == "normal"
                and verify_password(account.password, user.password_hash)
            )
            if unchanged:
                existing.append(identity.key)
                accounts[identity.key] = SeedAccount(
                    key=identity.key,
                    id=int(user.id),
                    email=user.email,
                    display_name=user.display_name,
                    role=user.role,
                    password=account.password,
                    status=user.status,
                )
            else:
                # Do not update the database or rewrite password/email/name/status; preserve the record as-is.
                preserved.append(identity.key)

        if check_only:
            await session.rollback()
            return SeedSummary(
                created=(),
                existing=tuple(existing),
                preserved=tuple(preserved),
                would_create=tuple(would_create),
                ready=not would_create and not preserved,
                check_only=True,
                credentials_path=credentials_path,
                fingerprint=fingerprint,
                accounts=accounts,
            )

        try:
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            if is_undefined_table(exc):
                raise SeedError("Database tables are not migrated (users table missing); run migrations first") from None
            raise SeedError(f"Seed write to the test database failed ({type(exc).__name__})") from None

    # Write the file only for new accounts or first creation; do not rewrite the password when existing accounts are unchanged.
    if created or existing_credentials is None:
        write_private_json(
            credentials_path,
            _credentials_payload(
                fingerprint=fingerprint,
                run_id=run_id,
                created_at=created_at,
                accounts=accounts,
            ),
        )
    else:
        try:
            protect_private(credentials_path)
        except OSError:
            raise SeedError("Unable to set credentials file permissions to 0600; check manually") from None

    return SeedSummary(
        created=tuple(created),
        existing=tuple(existing),
        preserved=tuple(preserved),
        would_create=tuple(would_create),
        ready=not would_create and not preserved,
        check_only=False,
        credentials_path=credentials_path,
        fingerprint=fingerprint,
        accounts=accounts,
    )


async def seed_identities(
    *,
    run_id: str,
    credentials_path: Path | None = None,
    check_only: bool = False,
    config: DevConfig | None = None,
    env_file: str | Path | None = None,
) -> SeedSummary:
    # The configured database is shared. Never seed it without a per-run sandbox.
    if config is None or not getattr(config, "acceptance_sandbox", False):
        raise GuardError("The acceptance seed requires this run's isolated environment; refusing to write to a shared database")
    config = config or load_dev_config(for_acceptance=True, require_storage=False, env_file=env_file)
    await probe_database(config.database_url, expect_test_target=True)
    path = credentials_path or credentials_path_for_run(run_id)
    engine = make_async_engine(config.database_url, schema=config.database_schema)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        with credentials_lock(path):
            return await seed_identities_core(
                session_factory=session_factory,
                database_url=config.database_url,
                identities=identities_for_run(run_id),
                credentials_path=path,
                run_id=run_id,
                check_only=check_only,
            )
    finally:
        await engine.dispose()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tests.acceptance_real.seed",
        description="Create/validate canonical acceptance identities in the .env.dev test database (never outputs passwords).",
    )
    from app.devtools._support import new_run_id
    parser.add_argument("--run-id", default=new_run_id(), help="Unique run identifier for this run")
    parser.add_argument("--credentials-file", default=None, help="Optional private credentials path (defaults to run_id)")
    parser.add_argument("--check", action="store_true", help="Validate only the target and account state; do not write to the database")
    return parser.parse_args(argv)


def _masked(account: SeedAccount) -> str:
    local, _, domain = account.email.partition("@")
    return f"{account.key}#{account.id} {local[:12]}…@{domain}" if domain else f"{account.key}#{account.id}"


def main(
    argv: Sequence[str] | None = None,
    *,
    run_id: str | None = None,
    check: bool | None = None,
    credentials_file: str | Path | None = None,
    env_file: str | Path | None = None,
) -> int:
    effective_argv = argv if argv is not None else ([] if run_id is not None else None)
    args = _parse_args(effective_argv)
    if run_id is not None:
        args.run_id = run_id
    if check is not None:
        args.check = bool(check)
    if credentials_file is not None:
        args.credentials_file = str(credentials_file)
    if args.credentials_file:
        print("seed: refusing an external credentials path; credentials are stored only in the one-shot isolated directory", file=sys.stderr)
        return 2
    import signal

    from tests.acceptance_real.sandbox import Sandbox
    sandbox = None
    result = 2
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        sandbox = Sandbox(load_dev_config(for_acceptance=True, require_storage=True, env_file=env_file))
        config = sandbox.create()
        summary = asyncio.run(seed_identities(run_id=args.run_id, config=config,
            credentials_path=config.credentials_path, check_only=args.check))
        if not args.check:
            verification = asyncio.run(seed_identities(run_id=args.run_id, config=config,
                credentials_path=config.credentials_path, check_only=True))
            if not verification.ready:
                raise SeedError("One-shot identity verification did not pass")
        print(f"seed: run_id={args.run_id} created={len(summary.created)} would_create={len(summary.would_create)}")
        result = 1 if args.check and not summary.ready else 0
    except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
        print(f"seed: failed: {type(exc).__name__}", file=sys.stderr)
    finally:
        previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if sandbox is not None:
            try:
                cleanup = sandbox.cleanup()
                if cleanup["cleanup_failures"]:
                    print(f"seed: cleanup_failures={cleanup['cleanup_failures']} manifest={sandbox.manifest}", file=sys.stderr)
                    result = 2
                else:
                    print("seed: one-shot identities and isolated resources cleaned up")
            except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
                print(f"seed: cleanup failed: {type(exc).__name__}; manifest={sandbox.manifest}", file=sys.stderr)
                result = 2
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, previous_int)
    return result


run = main


if __name__ == "__main__":
    raise SystemExit(main())

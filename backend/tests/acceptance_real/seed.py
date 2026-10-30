"""一次性验收身份 seed：仅在本轮隔离空间准备8个逻辑角色，结束清理。

命令::

    cd backend
    .venv/bin/python -m tests.acceptance_real.seed --run-id <run_id>

设计约束：

- 只读取后端 ``.env.dev``，按配置使用隔离SQLite或校验固定test PostgreSQL目标；不读取 ``.env.prod``。
- 每个隔离空间使用独立身份；同一空间内幂等，独立CLI退出即清理。
- 不覆盖/重置用户已修改的邮箱、显示名称、密码或封禁状态；发现变更时只报告并保留。
- 密码随机生成，只写入 0600 私有凭据文件；标准输出只打印路径和脱敏标识。
- 只准备身份，不创建分类、商品、交易、举报等业务流程数据。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.devtools._support import (
    DevConfig,
    GuardError,
    SeedError,
    credentials_lock,
    file_mode,
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


# canonical 角色：两名管理员、两名买方、两名卖方、第三方与限频演员。
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
        raise SeedError("run_id 不能为空或只包含分隔符")
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
        raise SeedError("run_id 只允许字母、数字、点、下划线和短横线，长度 1—64")
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
    if not isinstance(value, str) or len(value) < 16:
        raise SeedError("凭据文件缺少有效 seed 指纹；请人工核对，不自动重置")
    try:
        int(value, 16)
    except ValueError:
        raise SeedError("凭据文件 seed 指纹格式错误；请人工核对，不自动重置") from None
    return value


def _account_from_record(key: str, raw: Any) -> SeedAccount:
    if not isinstance(raw, dict):
        raise SeedError(f"凭据文件账号记录格式错误（{key}）；请人工核对")
    try:
        account_id = int(raw["id"])
        email = str(raw["email"])
        display_name = str(raw["display_name"])
        role = str(raw["role"])
        password = str(raw["password"])
    except (KeyError, TypeError, ValueError):
        raise SeedError(f"凭据文件账号字段缺失（{key}）；请人工核对") from None
    status = str(raw.get("status") or "normal")
    if account_id <= 0 or not email or not display_name or role not in {"admin", "user"} or not password:
        raise SeedError(f"凭据文件账号字段非法（{key}）；请人工核对")
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
    """读取任意数量身份；传入 identities 时要求这些 key 全部存在。

    旧实现只接受固定 admin/buyer/seller 三项；这里用于自定义多身份与人工/自动共享。
    """
    if not path.exists():
        return None
    mode = file_mode(path)
    if require_private and mode != 0o600:
        raise SeedError("凭据文件权限不是 0600；拒绝读取，请先修正权限")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SeedError("凭据文件无法读取或已损坏；请人工核对，不自动重置") from None
    if not isinstance(data, dict) or int(data.get("version", 0)) != SEED_VERSION:
        raise SeedError("凭据文件版本不支持；请人工核对，不自动重置")
    fingerprint = _validate_fingerprint(str(data.get("fingerprint", "")))
    raw_accounts = data.get("accounts")
    if not isinstance(raw_accounts, dict):
        raise SeedError("凭据文件缺少 accounts；请人工核对，不自动重置")
    accounts: dict[str, SeedAccount] = {}
    required = [identity.key for identity in identities] if identities is not None else list(raw_accounts)
    for key in required:
        raw = raw_accounts.get(key)
        if raw is None:
            raise SeedError(f"凭据文件缺少账号记录（{key}）；请人工核对，不自动重置")
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
    """在调用方会话上执行 seed；不依赖全局配置，不触碰业务数据。"""
    from app.core.security import hash_password, verify_password
    from app.models.user import User

    existing_credentials = load_credentials(credentials_path, require_private=False)
    fingerprint = existing_credentials.fingerprint if existing_credentials else secrets.token_hex(16)
    existing_accounts = dict(existing_credentials.accounts) if existing_credentials else {}
    created_at = existing_credentials.created_at if existing_credentials and existing_credentials.created_at else _utc_now()
    recorded_run_id = existing_credentials.run_id if existing_credentials else ""
    if recorded_run_id and recorded_run_id != run_id:
        raise SeedError("凭据文件的 run_id 与本次不一致；拒绝复用，请换用对应 run_id 或新凭据文件")

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
                # 记录 ID 对应账号仍存在，但邮箱已被用户改掉；保留不重置。
                preserved.append(identity.key)
                continue

            if account is not None and (account.email != identity.email or account.role != identity.role):
                raise SeedError(
                    f"凭据文件与本次 canonical 身份定义不一致（{identity.key}）；拒绝接管"
                )

            if user is None:
                if account is not None:
                    # 同名记录存在但数据库账号已不存在：不静默重建，交人工处理。
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
                    f"发现同名非 seed 账号（{identity.key}），拒绝接管；凭据文件缺失或不是本 seed 创建"
                )

            # 既有账号：所有字段与密码哈希都必须与凭据文件一致，才视为未变更。
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
                # 不更新数据库、不重写密码/邮箱/昵称/状态；只保留记录。
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
                raise SeedError("数据库表未迁移（缺少 users 表）；请先运行迁移") from None
            raise SeedError(f"seed 写入 test 数据库失败（{type(exc).__name__}）") from None

    # 只在新账号或首次创建时写文件；既有账号不变时不重写密码。
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
            os.chmod(credentials_path, 0o600)
        except OSError:
            raise SeedError("无法将凭据文件权限修正为 0600；请人工检查") from None

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
        raise GuardError("验收 seed 需要本轮隔离环境；拒绝写入共享数据库")
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
        description="创建/校验 .env.dev test 库中的 canonical 验收身份（不输出密码）。",
    )
    from app.devtools._support import new_run_id
    parser.add_argument("--run-id", default=new_run_id(), help="本轮唯一运行标识")
    parser.add_argument("--credentials-file", default=None, help="可选私有凭据路径（默认按 run_id）")
    parser.add_argument("--check", action="store_true", help="只校验目标与账号状态，不写库")
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
        print("seed: 拒绝外部凭据路径；凭据仅保存在一次性隔离目录", file=sys.stderr)
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
                raise SeedError("一次性身份校验未通过")
        print(f"seed: run_id={args.run_id} created={len(summary.created)} would_create={len(summary.would_create)}")
        result = 1 if args.check and not summary.ready else 0
    except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
        print(f"seed: 失败：{type(exc).__name__}", file=sys.stderr)
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
                    print("seed: 一次性身份和隔离资源已清理")
            except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
                print(f"seed: cleanup failed: {type(exc).__name__}; manifest={sandbox.manifest}", file=sys.stderr)
                result = 2
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, previous_int)
    return result


run = main


if __name__ == "__main__":
    raise SystemExit(main())

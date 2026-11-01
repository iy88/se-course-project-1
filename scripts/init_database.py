"""Provision fresh PostgreSQL resources, then apply the existing migration chain."""
from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import hashlib
import hmac
import os
import secrets
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.core.config import (
    load_migration_settings,
    resolve_env_file,
    validate_migration_context,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


class InitializationError(Exception):
    pass


def identifier(value):
    if not value or '\x00' in value or len(value.encode('utf-8')) > 63:
        raise InitializationError('Invalid or overlength PostgreSQL identifier')
    return '"' + value.replace('"', '""') + '"'


def scram(password):
    # Send a verifier rather than a plaintext application password in role DDL.
    import unicodedata
    from stringprep import in_table_b1, in_table_c12
    normalized = unicodedata.ucd_3_2_0.normalize('NFKC', ''.join(
        ' ' if in_table_c12(c) else c for c in password if not in_table_b1(c)))
    # PostgreSQL uses raw UTF-8 for passwords that fail SASLprep.
    from stringprep import (
        in_table_a1,
        in_table_c3,
        in_table_c4,
        in_table_c5,
        in_table_c6,
        in_table_c7,
        in_table_c8,
        in_table_c9,
        in_table_c21,
        in_table_c22,
        in_table_d1,
        in_table_d2,
    )
    prohibited = (in_table_a1, in_table_c21, in_table_c22, in_table_c3, in_table_c4,
                  in_table_c5, in_table_c6, in_table_c7, in_table_c8, in_table_c9)
    invalid = not normalized or any(test(c) for c in normalized for test in prohibited)
    if any(in_table_d1(c) for c in normalized):
        invalid |= any(in_table_d2(c) for c in normalized) or not (
            in_table_d1(normalized[0]) and in_table_d1(normalized[-1]))
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac('sha256', (password if invalid else normalized).encode(), salt, 4096)
    stored = hashlib.sha256(hmac.digest(salted, b'Client Key', 'sha256')).digest()
    server = hmac.digest(salted, b'Server Key', 'sha256')
    def encode(value: bytes) -> str:
        return base64.b64encode(value).decode('ascii')
    return f'SCRAM-SHA-256$4096:{encode(salt)}${encode(stored)}:{encode(server)}'


async def provision(settings, admin, password, maintenance):
    app = make_url(settings.database_url)
    migration = make_url(settings.migration_database_url)
    owner, migrator, application = settings.migration_owner_role, migration.username, app.username
    names = [owner, migrator, application]
    database, schema = app.database, settings.database_schema
    for value in [*names, database, schema, maintenance]:
        identifier(value)
    if database in {'postgres', 'template0', 'template1'}:
        raise InitializationError('System databases cannot be initialization targets')
    if admin in names or maintenance == database:
        raise InitializationError('Administrator/maintenance database must be separate from application resources')
    # Keep URL query parameters (including TLS) from the selected migration target.
    url = migration.set(username=admin, password=password, database=maintenance)
    engine = create_async_engine(url, isolation_level='AUTOCOMMIT', hide_parameters=True)
    try:
        async with engine.connect() as connection:
            existing = await connection.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=:name)'), {'name': database})
            roles = await connection.execute(text('SELECT rolname FROM pg_roles WHERE rolname IN (:a,:b,:c)'), dict(zip(('a','b','c'), names)))
            if existing or roles.first():
                raise InitializationError('Target database or role already exists; stopped without modifying existing resources')
            async with _transaction(connection):
                for name, login in ((owner, 'NOLOGIN'), (migrator, 'LOGIN NOINHERIT'), (application, 'LOGIN NOINHERIT')):
                    verifier = '' if name == owner else " PASSWORD '" + scram(migration.password if name == migrator else app.password) + "'"
                    await connection.exec_driver_sql(f'CREATE ROLE {identifier(name)} {login} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS{verifier}')
                await connection.exec_driver_sql(f'GRANT {identifier(owner)} TO {identifier(migrator)}')
            await connection.exec_driver_sql(f"CREATE DATABASE {identifier(database)} OWNER {identifier(owner)} TEMPLATE template0 ENCODING 'UTF8'")
            await connection.exec_driver_sql(f'REVOKE ALL ON DATABASE {identifier(database)} FROM PUBLIC')
            await connection.exec_driver_sql(f'GRANT CONNECT ON DATABASE {identifier(database)} TO {identifier(migrator)}, {identifier(application)}')
    finally:
        await engine.dispose()
    engine = create_async_engine(url.set(database=database), hide_parameters=True)
    try:
        async with engine.begin() as connection:
            qschema, qapp, qowner = map(identifier, (schema, application, owner))
            await connection.exec_driver_sql('REVOKE ALL ON SCHEMA public FROM PUBLIC')
            await connection.exec_driver_sql(f'CREATE SCHEMA {qschema} AUTHORIZATION {qowner}')
            for role in (application, migrator):
                await connection.exec_driver_sql(f'ALTER ROLE {identifier(role)} IN DATABASE {identifier(database)} SET search_path = {qschema}')
            await connection.exec_driver_sql(f"ALTER ROLE {qapp} IN DATABASE {identifier(database)} SET timezone = 'UTC'")
            await connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA {qschema} TO {qapp}')
            await connection.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES FOR ROLE {qowner} IN SCHEMA {qschema} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {qapp}')
            await connection.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES FOR ROLE {qowner} IN SCHEMA {qschema} GRANT USAGE, SELECT ON SEQUENCES TO {qapp}')
    finally:
        await engine.dispose()


class _transaction:
    # Explicit SQL transaction on the autocommit connection; CREATE DATABASE stays outside.
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        await self.connection.exec_driver_sql('BEGIN')

    async def __aexit__(self, kind, value, traceback):
        await self.connection.exec_driver_sql('ROLLBACK' if kind else 'COMMIT')



def failure_detail(error: Exception) -> str:
    """Return only fixed diagnostics; never emit driver messages or input bytes."""
    if isinstance(error, InitializationError):
        return str(error)
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        state = getattr(current, 'sqlstate', None)
        if state is None:
            state = getattr(current, 'pgcode', None)
        if state in {'28P01', '28000'}:
            return 'PostgreSQL authentication rejected; use a PostgreSQL login role, not the Windows/WSL account, and verify its password and pg_hba.conf'
        if state == '42501':
            return 'PostgreSQL permission denied; the database administrator needs permission to create databases and roles'
        if state == '3D000':
            return 'PostgreSQL maintenance database does not exist; check --maintenance-db'
        if isinstance(current, UnicodeDecodeError):
            frames = traceback.extract_tb(current.__traceback__)
            if any(Path(frame.filename).name == 'configparser.py' for frame in frames):
                return 'Local INI configuration could not be decoded; read the configuration as UTF-8 (not a database authentication error)'
            # A localized server error may fail inside the driver before SQLSTATE
            # becomes available. Classify known text without printing raw content.
            for encoding in ('utf-8', 'gb18030', 'cp1252'):
                try:
                    message = current.object.decode(encoding).lower()
                except (UnicodeError, AttributeError):
                    continue
                if any(part in message for part in ('password authentication failed', '密码认证失败', '口令认证失败', '密码验证失败')):
                    return 'PostgreSQL authentication rejected (localized error); verify the PostgreSQL role and password'
            return 'Database response could not be decoded; verify the endpoint and PostgreSQL login role, and check the server authentication log and lc_messages (this is not necessarily a terminal encoding issue)'
        for nested in (getattr(current, 'orig', None), current.__cause__, current.__context__):
            if isinstance(nested, Exception):
                pending.append(nested)
    return type(error).__name__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True, help='dotenv file; relative paths follow backend configuration rules')
    parser.add_argument('--maintenance-db', default='postgres')
    parser.add_argument('--resume-migrations', action='store_true',
                        help='resume only versioned table migrations after resources were created; never create or alter database roles')
    args = parser.parse_args()
    try:
        path = resolve_env_file(args.env_file)
        settings = load_migration_settings(path)
        validate_migration_context(settings)
        if not args.resume_migrations and not sys.stdin.isatty():
            raise InitializationError('An interactive terminal is required for administrator credentials')
        target = make_url(settings.database_url)
        print(f'Target: {target.host}:{target.port or 5432}/{target.database}; schema={settings.database_schema}')
        if not args.resume_migrations:
            admin = input('PostgreSQL administrator username (not saved): ').strip()
            password = getpass.getpass('PostgreSQL administrator password (not saved): ')
            if not admin or not password:
                raise InitializationError('Administrator username and password are required')
            try:
                asyncio.run(provision(settings, admin, password, args.maintenance_db))
            finally:
                admin = password = None
            print('Database resources created. Applying versioned migrations...')
        else:
            print('Resuming versioned migrations using the configured migrator; resource creation is skipped.')
        os.environ['APP_ENV_FILE'] = str(path)
        from app.manage import run_migrate
        run_migrate('head')
        print('Versioned tables initialized. Run app.manage seed for the application administrator.')
        return 0
    except (KeyboardInterrupt, EOFError):
        print('Cancelled. Completed provisioning steps are not automatically removed.', file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - redact credentials from all driver/DDL failures
        # Never print connection/SQL exceptions: these may contain administrator identity or verifiers.
        detail = failure_detail(exc)
        if exc.__traceback__ is not None:
            frames = traceback.extract_tb(exc.__traceback__)
            frame = frames[-1]
            print(f'Failure location: {Path(frame.filename).name}:{frame.lineno} ({frame.name})', file=sys.stderr)
        print(f'Initialization stopped: {detail}. Check existing resources before retrying; no automatic DROP is performed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

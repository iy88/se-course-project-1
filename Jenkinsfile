pipeline {
    agent any

    tools {
        nodejs 'node-latest'
    }

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        UV_CACHE_DIR = "${WORKSPACE}/.cache/uv"
        NPM_CONFIG_CACHE = "${WORKSPACE}/.cache/npm"
    }

    stages {
        stage('Checkout project1') {
            steps {
                dir('source') {
                    deleteDir()

                    sshagent(credentials: ['gitea-deploy-readonly']) {
                        sh '''
                            set -eu

                            export GIT_SSH_COMMAND='ssh \
                                -p 22 \
                                -o BatchMode=yes \
                                -o StrictHostKeyChecking=yes \
                                -o HostKeyAlgorithms=ssh-ed25519 \
                                -o ConnectTimeout=10 \
                                -o ServerAliveInterval=15 \
                                -o ServerAliveCountMax=2'

                            git clone \
                                --branch main \
                                --single-branch \
                                git@192.168.3.223:iy88/se-course-project-1.git \
                                .

                            echo '=== Checked-out revision ==='
                            git log -1 --format='%h %s'
                            git branch --show-current
                        '''
                    }
                }
            }
        }

        stage('Verify Project Structure') {
            steps {
                dir('source') {
                    sh '''
                        set -eu

                        test -f backend/pyproject.toml
                        test -f backend/uv.lock
                        test -f backend/app/main.py
                        test -f backend/.env.prod.example

                        test -f frontend/mobile/package.json
                        test -f frontend/mobile/package-lock.json

                        test -f frontend/admin/package.json
                        test -f frontend/admin/package-lock.json

                        test -f frontend/config.mjs

                        node -e '
                            if (process.versions.node !== "26.12.1") {
                                throw new Error(
                                    "Expected Node.js 26.12.1, got " +
                                    process.versions.node
                                );
                            }
                        '
                    '''
                }
            }
        }

        stage('Install Backend Dependencies') {
            steps {
                dir('source/backend') {
                    sh '''
                        set -eu

                        /usr/local/bin/uv sync \
                            --locked \
                            --managed-python \
                            --python 3.13

                        .venv/bin/python --version
                        .venv/bin/python -m pip --version \
                            2>/dev/null || true

                        # 只检查依赖导入，不加载项目生产配置
                        .venv/bin/python -c '
import fastapi
import uvicorn
import sqlalchemy
import asyncpg

print("Backend dependency imports passed.")
'
                    '''
                }
            }
        }

        stage('Backend Acceptance - SQLite Local') {
            steps {
                dir('source/backend') {
                    sh '''
                        set -eu
                        umask 077

                        # 当前任务每次重新检出 source，测试配置只在此工作区生成。
                        # 如果已有配置则拒绝覆盖。
                        if [ -e .env.dev ] || [ -L .env.dev ]; then
                            echo 'Refusing to overwrite existing backend/.env.dev'
                            exit 1
                        fi

                        .venv/bin/python - <<'PY'
from pathlib import Path
import os
import secrets

backend = Path.cwd()
root = backend.parent
local_root = root / "var" / "ci-local-base"
local_root.mkdir(parents=True, exist_ok=True)

values = {
    "APP_NAME": "Project1 CI",
    "ENVIRONMENT": "test",
    "DATABASE_URL": "sqlite+aiosqlite:///" + str(local_root / "test.db"),
    "DATABASE_SCHEMA": "app",
    "DB_AUTO_CREATE": "false",
    "AUDIT_TRUSTED_PROXIES": "none",
    "STORAGE_LOCAL_ROOT": str(local_root / "storage"),
    "JWT_SECRET": secrets.token_urlsafe(48),
    "JWT_ALGORITHM": "HS256",
    "FILE_URL_SECRET": secrets.token_urlsafe(48),
    "SMTP_SECURITY": "ssl",
}

# 原验收入口要求使用 backend/.env.dev。
# 邮件捕获及每轮隔离资源由 runner 生成，不填写生产凭据。
with open(".env.dev", "x", encoding="utf-8") as handle:
    for key, value in values.items():
        handle.write(f"{key}='{value}'\\n")

os.chmod(".env.dev", 0o600)
print("Private SQLite/local CI configuration created.")
PY

                        # 成功或失败后均删除本轮生成的基础配置。
                        trap 'rm -f .env.dev' EXIT

                        # 使用现有业务验收入口，由 runner 启动并清理隔离测试服务。
                        APP_ENV_FILE=.env.dev \
                            .venv/bin/python -m tests.acceptance_real.runner \
                            --port 8101
                    '''
                }
            }

            post {
                always {
                    archiveArtifacts(
                        artifacts: 'source/var/acceptance-real/acceptance-*.json,source/var/acceptance-real/acceptance-*.md',
                        allowEmptyArchive: true
                    )
                }
            }
        }

        stage('Install Mobile Dependencies') {
            steps {
                dir('source/frontend/mobile') {
                    sh '''
                        set -eu

                        npm ci --no-audit --no-fund

                        test -x node_modules/.bin/vite
                        echo 'Mobile dependencies installed.'
                    '''
                }
            }
        }

        stage('Install Admin Dependencies') {
            steps {
                dir('source/frontend/admin') {
                    sh '''
                        set -eu

                        npm ci --no-audit --no-fund

                        test -x node_modules/.bin/vite
                        echo 'Admin dependencies installed.'
                    '''
                }
            }
        }

        stage('Build Mobile Frontend') {
            steps {
                dir('source/frontend/mobile') {
                    sh '''
                        set -eu

                        PROJECT1_FRONTEND_CONFIG=public npm run build

                        test -s dist/index.html
                        test -s dist/manifest.webmanifest
                        test -s dist/sw.js
                    '''
                }
            }
        }

        stage('Build Admin Frontend') {
            steps {
                dir('source/frontend/admin') {
                    sh '''
                        set -eu

                        PROJECT1_FRONTEND_CONFIG=public npm run build

                        test -s dist/index.html
                    '''
                }
            }
        }

        stage('Verify Lockfiles Unchanged') {
            steps {
                dir('source') {
                    sh '''
                        set -eu

                        git diff --exit-code -- \
                            backend/pyproject.toml \
                            backend/uv.lock \
                            frontend/mobile/package.json \
                            frontend/mobile/package-lock.json \
                            frontend/admin/package.json \
                            frontend/admin/package-lock.json

                        echo 'Dependency manifests and lockfiles unchanged.'
                    '''
                }
            }
        }

        stage('Package Release') {
            steps {
                dir('source') {
                    sh '''
                        set -eu

                        REVISION="$(git rev-parse HEAD)"
                        RELEASE_ID="${REVISION}-${BUILD_NUMBER}"
                        OUTPUT_DIR="${WORKSPACE}/release-artifacts"

                        # 只清理本任务专用的发布包目录。
                        mkdir -p "${OUTPUT_DIR}"
                        find "${OUTPUT_DIR}" -maxdepth 1 -type f -delete

                        # 后端仅打包此提交中已追踪的 backend 文件。
                        # 不包含工作区的 .venv、测试运行数据或未追踪配置。
                        git archive \
                            --format=tar.gz \
                            --output="${OUTPUT_DIR}/backend-${RELEASE_ID}.tar.gz" \
                            HEAD backend

                        # 前端使用本次 CI 已生成的构建产物。
                        tar -C frontend/mobile/dist \
                            -czf "${OUTPUT_DIR}/mobile-${RELEASE_ID}.tar.gz" .

                        tar -C frontend/admin/dist \
                            -czf "${OUTPUT_DIR}/admin-${RELEASE_ID}.tar.gz" .

                        printf 'revision=%s\\nbuild_number=%s\\nrelease_id=%s\\n' \
                            "${REVISION}" \
                            "${BUILD_NUMBER}" \
                            "${RELEASE_ID}" \
                            > "${OUTPUT_DIR}/release.txt"

                        (
                            cd "${OUTPUT_DIR}"

                            sha256sum \
                                "backend-${RELEASE_ID}.tar.gz" \
                                "mobile-${RELEASE_ID}.tar.gz" \
                                "admin-${RELEASE_ID}.tar.gz" \
                                release.txt \
                                > SHA256SUMS

                            sha256sum --check SHA256SUMS
                        )

                        echo "Release packaged: ${RELEASE_ID}"
                    '''
                }

                archiveArtifacts(
                    artifacts: 'release-artifacts/*',
                    fingerprint: true,
                    allowEmptyArchive: false
                )
            }
        }

        stage('Upload Release') {
            steps {
                sshagent(credentials: ['production-deploy-ssh']) {
                    sh '''
                        set -eu

                        OUTPUT_DIR="${WORKSPACE}/release-artifacts"

                        # 从已打包的发布信息读取版本，而不是重新拉取代码。
                        RELEASE_ID="$(sed -n 's/^release_id=//p' "${OUTPUT_DIR}/release.txt")"

                        # 后续会将版本号用于远端路径，先严格限制格式。
                        printf '%s\\n' "${RELEASE_ID}" |
                            grep -Eq '^[0-9a-f]{40}-[0-9]+$'

                        REMOTE_DIR="/srv/se-course-project1/releases/${RELEASE_ID}"

                        # 上传前再次检查本地发布包。
                        (
                            cd "${OUTPUT_DIR}"
                            sha256sum --check SHA256SUMS
                        )

                        # 统一使用已核对的主机公钥进行 SSH 连接。
                        ssh_prod() {
                            ssh \
                                -p 22 \
                                -o BatchMode=yes \
                                -o StrictHostKeyChecking=yes \
                                -o HostKeyAlgorithms=ssh-ed25519 \
                                -o ConnectTimeout=10 \
                                -o ServerAliveInterval=15 \
                                -o ServerAliveCountMax=2 \
                                deploy@192.168.3.221 \
                                "$@"
                        }

                        # 每次构建使用独立目录；若已存在则停止，避免覆盖。
                        ssh_prod "mkdir -- '${REMOTE_DIR}'"

                        scp \
                            -P 22 \
                            -o BatchMode=yes \
                            -o StrictHostKeyChecking=yes \
                            -o HostKeyAlgorithms=ssh-ed25519 \
                            -o ConnectTimeout=10 \
                            -o ServerAliveInterval=15 \
                            -o ServerAliveCountMax=2 \
                            "${OUTPUT_DIR}/backend-${RELEASE_ID}.tar.gz" \
                            "${OUTPUT_DIR}/mobile-${RELEASE_ID}.tar.gz" \
                            "${OUTPUT_DIR}/admin-${RELEASE_ID}.tar.gz" \
                            "${OUTPUT_DIR}/release.txt" \
                            "${OUTPUT_DIR}/SHA256SUMS" \
                            "deploy@192.168.3.221:${REMOTE_DIR}/"

                        # 在生产机校验上传后的文件。
                        ssh_prod \
                            "set -eu
                             cd '${REMOTE_DIR}'
                             sha256sum --check SHA256SUMS
                             echo 'Release upload and checksum verification passed.'
                             pwd"
                    '''
                }
            }
        }

        stage('Prepare Production Release') {
            steps {
                sshagent(credentials: ['production-deploy-ssh']) {
                    sh '''
                        set -eu

                        OUTPUT_DIR="${WORKSPACE}/release-artifacts"
                        RELEASE_ID="$(sed -n 's/^release_id=//p' "${OUTPUT_DIR}/release.txt")"

                        printf '%s\\n' "${RELEASE_ID}" |
                            grep -Eq '^[0-9a-f]{40}-[0-9]+$'

                        ssh \
                            -p 22 \
                            -o BatchMode=yes \
                            -o StrictHostKeyChecking=yes \
                            -o HostKeyAlgorithms=ssh-ed25519 \
                            -o ConnectTimeout=10 \
                            -o ServerAliveInterval=15 \
                            -o ServerAliveCountMax=2 \
                            deploy@192.168.3.221 \
                            bash -s -- "${RELEASE_ID}" <<'REMOTE'
set -euo pipefail

release_id="$1"
release_dir="/srv/se-course-project1/releases/$release_id"
shared_config=/srv/se-course-project1/shared/.env.prod

cd "$release_dir"
sha256sum --check SHA256SUMS
test -r "$shared_config"

for path in backend mobile admin; do
    if [ -e "$path" ] || [ -L "$path" ]; then
        echo "Refusing to overwrite existing release contents: $path"
        exit 1
    fi
done

umask 022

tar -xzf "backend-${release_id}.tar.gz"

mkdir mobile admin
tar -xzf "mobile-${release_id}.tar.gz" -C mobile
tar -xzf "admin-${release_id}.tar.gz" -C admin

test -f backend/app/main.py
test -s mobile/index.html
test -s mobile/sw.js
test -s admin/index.html

umask 077
install -m 0600 "$shared_config" backend/.env.prod

cd backend

/usr/local/bin/uv sync \
    --locked \
    --no-dev \
    --managed-python \
    --python 3.13.15

APP_ENV_FILE=.env.prod .venv/bin/python - <<'PY'
import sys

from app.core.config import (
    load_settings,
    load_migration_settings,
    validate_migration_context,
)

if sys.version_info[:3] != (3, 13, 15):
    raise RuntimeError("Expected Python 3.13.15")

settings = load_settings()
migration = load_migration_settings()
validate_migration_context(migration)

if settings.environment != "prod":
    raise RuntimeError("Expected production environment")

if settings.database_schema != "app" or settings.db_auto_create:
    raise RuntimeError("Unexpected production database settings")

if settings.storage_backend != "oss":
    raise RuntimeError("Expected OSS storage")

print("Production application and migration configuration checks passed.")
PY

printf 'prepared_at=%s\\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$release_dir/PREPARED"

echo "Production release prepared: $release_id"
REMOTE
                    '''
                }
            }
        }

        stage('Backup Production Data') {
            options {
                timeout(time: 10, unit: 'MINUTES')
            }

            steps {
                sshagent(credentials: ['production-deploy-ssh']) {
                    script {
                        String output = sh(
                            script: '''
                                set -eu

                                ssh \
                                    -p 22 \
                                    -o BatchMode=yes \
                                    -o StrictHostKeyChecking=yes \
                                    -o HostKeyAlgorithms=ssh-ed25519 \
                                    -o ConnectTimeout=10 \
                                    -o ServerAliveInterval=15 \
                                    -o ServerAliveCountMax=2 \
                                    deploy@192.168.3.221 \
                                    'sudo -n /usr/local/sbin/se-course-project1-backup'
                            ''',
                            returnStdout: true
                        ).trim()

                        echo output

                        def completed = output.readLines().findAll {
                            it.startsWith('BACKUP_COMPLETE=')
                        }

                        if (completed.size() != 1) {
                            error('生产备份未返回唯一的完成标记，停止流水线。')
                        }

                        String backupPath = completed[0].substring('BACKUP_COMPLETE='.length()).trim()

                        if (!(backupPath ==~ '^/var/backups/se-course-project1/predeploy-[A-Za-z0-9-]+$')) {
                            error('生产备份返回的目录格式不符合预期，停止流水线。')
                        }

                        env.PRODUCTION_BACKUP_DIR = backupPath

                        currentBuild.description = "生产备份：${backupPath}"

                        echo "生产 PostgreSQL 与 Redis 备份完成：${backupPath}"
                    }
                }
            }
        }

        stage('Migrate Production Database') {
            steps {
                sshagent(credentials: ['production-deploy-ssh']) {
                    sh '''
                        set -eu

                        # 必须由本次流水线的备份阶段取得完成标记。
                        test -n "${PRODUCTION_BACKUP_DIR:-}"

                        OUTPUT_DIR="${WORKSPACE}/release-artifacts"
                        RELEASE_ID="$(sed -n 's/^release_id=//p' "${OUTPUT_DIR}/release.txt")"

                        printf '%s\\n' "${RELEASE_ID}" |
                            grep -Eq '^[0-9a-f]{40}-[0-9]+$'

                        ssh \
                            -p 22 \
                            -o BatchMode=yes \
                            -o StrictHostKeyChecking=yes \
                            -o HostKeyAlgorithms=ssh-ed25519 \
                            -o ConnectTimeout=10 \
                            -o ServerAliveInterval=15 \
                            -o ServerAliveCountMax=2 \
                            deploy@192.168.3.221 \
                            bash -s -- \
                            "${RELEASE_ID}" \
                            "${PRODUCTION_BACKUP_DIR}" <<'REMOTE'
set -euo pipefail
umask 077

release_id="$1"
backup_dir="$2"
release_dir="/srv/se-course-project1/releases/$release_id"

test -s "$release_dir/PREPARED"
test -n "$backup_dir"

cd "$release_dir/backend"

echo '=== Apply production migrations ==='

APP_ENV_FILE=.env.prod \
    .venv/bin/python -m app.manage migrate

echo '=== Verify database revision ==='

APP_ENV_FILE=.env.prod .venv/bin/python - <<'PY'
import asyncio
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import (
    load_migration_settings,
    validate_migration_context,
)

async def main():
    settings = load_migration_settings()
    validate_migration_context(settings)

    config = Config("alembic.ini")
    config.set_main_option(
        "script_location", str(Path("alembic").resolve())
    )
    expected = set(ScriptDirectory.from_config(config).get_heads())

    engine = create_async_engine(
        settings.migration_database_url,
        connect_args={"timeout": 10, "command_timeout": 10},
    )

    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(f'SET LOCAL ROLE "{settings.migration_owner_role}"')
            )

            actual = set(await conn.run_sync(
                lambda connection: MigrationContext.configure(
                    connection,
                    opts={"version_table_schema": settings.database_schema},
                ).get_current_heads()
            ))

            if actual != expected:
                raise RuntimeError(
                    f"Migration revision mismatch: "
                    f"expected={sorted(expected)}, actual={sorted(actual)}"
                )

            await conn.rollback()
            print("Production database revision verified:", ", ".join(sorted(actual)))
    finally:
        await engine.dispose()

asyncio.run(main())
PY

{
    printf 'release_id=%s\\n' "$release_id"
    printf 'backup_dir=%s\\n' "$backup_dir"
    printf 'migrated_at=%s\\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$release_dir/MIGRATED"

echo "Production migration completed: $release_id"
REMOTE
                    '''
                }
            }
        }

        stage('Activate Production Release') {
            steps {
                sshagent(credentials: ['production-deploy-ssh']) {
                    sh '''
                        set -eu

                        test -n "${PRODUCTION_BACKUP_DIR:-}"

                        OUTPUT_DIR="${WORKSPACE}/release-artifacts"
                        RELEASE_ID="$(sed -n 's/^release_id=//p' "${OUTPUT_DIR}/release.txt")"

                        printf '%s\\n' "${RELEASE_ID}" |
                            grep -Eq '^[0-9a-f]{40}-[0-9]+$'

                        ssh \
                            -p 22 \
                            -o BatchMode=yes \
                            -o StrictHostKeyChecking=yes \
                            -o HostKeyAlgorithms=ssh-ed25519 \
                            -o ConnectTimeout=10 \
                            -o ServerAliveInterval=15 \
                            -o ServerAliveCountMax=2 \
                            deploy@192.168.3.221 \
                            bash -s -- \
                            "${RELEASE_ID}" \
                            "${PRODUCTION_BACKUP_DIR}" <<'REMOTE'
set -euo pipefail
umask 077

release_id="$1"
backup_dir="$2"

deploy_root=/srv/se-course-project1
release_dir="$deploy_root/releases/$release_id"
current="$deploy_root/current"
service=se-course-project1-backend.service

test -s "$release_dir/PREPARED"
test -s "$release_dir/MIGRATED"
test -x "$release_dir/backend/.venv/bin/python"
test -s "$release_dir/mobile/index.html"
test -s "$release_dir/admin/index.html"

# 确认迁移标记属于本次发布及本次备份。
grep -Fxq "release_id=$release_id" "$release_dir/MIGRATED"
grep -Fxq "backup_dir=$backup_dir" "$release_dir/MIGRATED"

# 防止多个激活操作同时修改 current。
exec 9>"$deploy_root/.activation.lock"
flock -n 9 || {
    echo 'Another release activation is running.'
    exit 1
}

# 当前已经有手动验证通过的版本，因此必须保留可回退目标。
test -L "$current"
previous="$(readlink -f "$current")"

previous_id="${previous##*/}"
[[ "$previous_id" =~ ^[0-9a-f]{40}-[0-9]+$ ]]
test "$previous" = "$deploy_root/releases/$previous_id"
test -x "$previous/backend/.venv/bin/python"

if [ "$previous" = "$release_dir" ]; then
    echo 'Target release is already current; refusing duplicate activation.'
    exit 1
fi

# 在各自 release/backend 内读取配置，所有监听参数来自 .env.prod。
listener() (
    cd "$1/backend"

    APP_ENV_FILE=.env.prod .venv/bin/python - <<'PY'
from app.core.config import load_settings

settings = load_settings()
if settings.api_host != "127.0.0.1":
    raise RuntimeError("Expected loopback API host")

print(f"{settings.api_host}:{settings.api_port}")
PY
)

old_listener="$(listener "$previous")"
new_listener="$(listener "$release_dir")"

# Nginx upstream 当前固定指向 127.0.0.1:8001。
# 监听地址变化需要单独更新 Nginx，不能只重启应用。
if [ "$old_listener" != "$new_listener" ]; then
    echo 'API listener changed; update Nginx upstream before activation.'
    exit 1
fi

if [ "$new_listener" != "127.0.0.1:8001" ]; then
    echo 'API listener does not match the configured Nginx upstream.'
    exit 1
fi

# 临时目录与 current 位于同一文件系统，mv -T 原子替换软链接。
switch_dir="$(mktemp -d "$deploy_root/.activate-XXXXXXXX")"
switched=0
committed=0

switch_to() {
    ln -s -- "$1" "$switch_dir/next"
    mv -Tf -- "$switch_dir/next" "$current"
}

# 除了检查 HTTP，还确认 systemd 主进程运行在目标 release。
check_health() (
    cd "$1/backend"

    APP_ENV_FILE=.env.prod .venv/bin/python - "$1" <<'PY'
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from app.core.config import load_settings

expected_backend = (Path(sys.argv[1]) / "backend").resolve()
settings = load_settings()
url = f"http://{settings.api_host}:{settings.api_port}/api/health"
opener = build_opener(ProxyHandler({}))

for attempt in range(30):
    try:
        result = subprocess.run(
            [
                "/usr/bin/systemctl", "show",
                "se-course-project1-backend.service",
                "--property=MainPID", "--value",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        pid = int(result.stdout.strip())
        if pid <= 0:
            raise RuntimeError("Service has no main process")

        process_backend = Path(f"/proc/{pid}/cwd").resolve(strict=True)
        if process_backend != expected_backend:
            raise RuntimeError("Service is running a different release")

        with opener.open(url, timeout=2) as response:
            body = json.load(response)
            if response.status != 200 or body.get("status") != "ok":
                raise RuntimeError("Unexpected health response")

        print("Backend process and HTTP health checks passed.")
        print("Health URL:", url)
        sys.exit(0)
    except Exception:
        time.sleep(1)

print("Backend process or HTTP health check failed.", file=sys.stderr)
sys.exit(1)
PY
)

finish() {
    result=$?
    trap - EXIT HUP INT TERM

    if [ "$switched" -eq 1 ] && [ "$committed" -ne 1 ]; then
        echo '=== Activation failed; restore previous code release ==='

        if switch_to "$previous" &&
           sudo -n /usr/bin/systemctl restart "$service" &&
           check_health "$previous"; then
            echo "ROLLBACK_COMPLETE=$previous"
        else
            echo 'ROLLBACK_FAILED: inspect the production service immediately.'
        fi

        # 发布失败，即使回退成功，也不能让 Jenkins 标记为成功。
        result=1
    fi

    rm -f -- "$switch_dir/next"
    rmdir -- "$switch_dir" || true
    exit "$result"
}

trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

printf 'Previous release: %s\\n' "$previous"
printf 'Target release: %s\\n' "$release_dir"

# 先设置标记，确保切换命令异常退出时也尝试恢复旧链接。
switched=1
switch_to "$release_dir"

sudo -n /usr/bin/systemctl restart "$service"
check_health "$release_dir"

{
    printf 'release_id=%s\\n' "$release_id"
    printf 'previous_release=%s\\n' "$previous"
    printf 'backup_dir=%s\\n' "$backup_dir"
    printf 'activated_at=%s\\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$release_dir/ACTIVATED"

committed=1

echo "ACTIVATION_COMPLETE=$release_dir"
REMOTE
                    '''
                }
            }
        }
    }

    post {
        success {
            archiveArtifacts(
                artifacts: 'source/frontend/mobile/dist/**,source/frontend/admin/dist/**',
                fingerprint: true,
                allowEmptyArchive: false
            )

            echo '自动化验收、前端构建、生产备份、数据库迁移及版本激活通过。'
        }

        failure {
            echo '流水线失败，请查看第一个失败阶段；若已进入激活阶段，请同时检查回退结果。'
        }

        always {
            echo "Build result: ${currentBuild.currentResult}"
        }
    }
}

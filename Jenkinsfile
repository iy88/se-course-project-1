def sendBuildNotification() {
    // Notification errors must not hide the original deployment result.
    catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE', catchInterruptions: false) {
        timeout(time: 2, unit: 'MINUTES') {
            emailext(
                to: '$DEFAULT_RECIPIENTS',
                subject: '$DEFAULT_SUBJECT',
                body: '$DEFAULT_CONTENT',
                attachLog: false
            )
        }
    }
}

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
        DEPLOY_MODE = 'split'
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

        stage('Build Frontends') {
            failFast true
            parallel {
                stage('Mobile Frontend') {
                    steps {
                        dir('source/frontend/mobile') {
                            sh '''
                                set -eu
                                npm ci --no-audit --no-fund
                                PROJECT1_FRONTEND_CONFIG=public npm run build
                                test -s dist/index.html
                                test -s dist/manifest.webmanifest
                                test -s dist/sw.js
                            '''
                        }
                    }
                }
                stage('Admin Frontend') {
                    steps {
                        dir('source/frontend/admin') {
                            sh '''
                                set -eu
                                npm ci --no-audit --no-fund
                                PROJECT1_FRONTEND_CONFIG=public npm run build
                                test -s dist/index.html
                            '''
                        }
                    }
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

                        # Fixed-purpose deployment assets (systemd/nginx/sudoers,
                        # preflight and activation) travel with the release.
                        # Stage both deployment assets and the dotenv migration
                        # helper; its parent lookup works in release/deploy/.
                        DEPLOY_BUNDLE="${OUTPUT_DIR}/deploy-bundle"
                        mkdir -p "${DEPLOY_BUNDLE}"
                        git archive --format=tar HEAD \
                            scripts/deploy scripts/migrate_runtime_env.py | \
                            tar -x -C "${DEPLOY_BUNDLE}" --strip-components=1
                        mv "${DEPLOY_BUNDLE}/migrate_runtime_env.py" "${DEPLOY_BUNDLE}/deploy/"
                        tar -C "${DEPLOY_BUNDLE}" \
                            -czf "${OUTPUT_DIR}/deploy-${RELEASE_ID}.tar.gz" deploy
                        rm -rf "${DEPLOY_BUNDLE}"

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
                                "deploy-${RELEASE_ID}.tar.gz" \
                                release.txt \
                                > SHA256SUMS

                            sha256sum --check SHA256SUMS
                        )

                        echo "Release packaged: ${RELEASE_ID}"
                    '''
                }

                archiveArtifacts(
                    artifacts: 'release-artifacts/*,source/scripts/deploy/**',
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
                            "${OUTPUT_DIR}/deploy-${RELEASE_ID}.tar.gz" \
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
                            bash -s -- "${RELEASE_ID}" "${DEPLOY_MODE}" <<'REMOTE'
set -euo pipefail

release_id="$1"
mode="$2"
case "$mode" in split) ;; *) echo "Invalid deploy mode: $mode"; exit 1 ;; esac
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
tar -xzf "deploy-${release_id}.tar.gz"

test -f deploy/activate.py
test -f deploy/preflight.py
test -f deploy/systemd/se-course-project1-api.service
test -f deploy/systemd/se-course-project1-ws.service
test -f deploy/systemd/se-course-project1-worker.service
test -f deploy/systemd/se-course-project1-scheduler.service
test -f deploy/nginx/se-course-project1-http.conf
test -f deploy/nginx/se-course-project1-routes.conf

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

# Strict production preflight: all roles, budgets, DB/Redis connectivity.
APP_ENV_FILE=.env.prod .venv/bin/python ../deploy/preflight.py --mode "$mode" --connect

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
                        OUTPUT_DIR="${WORKSPACE}/release-artifacts"
                        RELEASE_ID="$(sed -n 's/^release_id=//p' "${OUTPUT_DIR}/release.txt")"
                        printf '%s\n' "${RELEASE_ID}" | grep -Eq '^[0-9a-f]{40}-[0-9]+$'
                        test -n "${PRODUCTION_BACKUP_DIR:-}"
                        printf '%s\n' "${PRODUCTION_BACKUP_DIR}" | grep -Eq '^/var/backups/se-course-project1/predeploy-[A-Za-z0-9-]+$'
                        case "${DEPLOY_MODE}" in split) ;; *) exit 1 ;; esac
                        ssh -p 22 -o BatchMode=yes -o StrictHostKeyChecking=yes \
                            -o HostKeyAlgorithms=ssh-ed25519 -o ConnectTimeout=10 \
                            -o ServerAliveInterval=15 -o ServerAliveCountMax=2 \
                            deploy@192.168.3.221 \
                            bash -s -- "${RELEASE_ID}" "${PRODUCTION_BACKUP_DIR}" "${DEPLOY_MODE}" <<'REMOTE'
set -euo pipefail
release_id="$1"
backup_dir="$2"
mode="$3"
[[ "$release_id" =~ ^[0-9a-f]{40}-[0-9]+$ ]]
[[ "$backup_dir" =~ ^/var/backups/se-course-project1/predeploy-[A-Za-z0-9-]+$ ]]
case "$mode" in split) ;; *) exit 1 ;; esac

# Run this release's reviewed activator as deploy. Only exact service actions
# inside it use sudo; no root-owned executable runs project Python code.
cd "/srv/se-course-project1/releases/$release_id/backend"
APP_ENV_FILE=.env.prod .venv/bin/python ../deploy/activate.py \
    --sudo --verify-process \
    --release-id "$release_id" --backup-dir "$backup_dir" --mode "$mode"
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

            echo '前端构建、生产备份、数据库迁移及版本激活通过。'
        }

        failure {
            echo '流水线失败，请查看第一个失败阶段；若已进入激活阶段，请同时检查回退结果。'
            script {
                sendBuildNotification()
            }
        }

        fixed {
            script {
                sendBuildNotification()
            }
        }

        always {
            echo "Build result: ${currentBuild.currentResult}"
        }
    }
}

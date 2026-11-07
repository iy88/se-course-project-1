<!--
Version: 0.2.4
Version-Datetime: 2026-11-07T18:29:39+08:00
-->

# 开发与人工测试指南

本指南合并环境约定、资源准备、服务托管、数据操作与验收入口，命令均从项目根目录或指定目录执行。应用默认读取 `backend/.env.dev`，通过 `APP_ENV_FILE` 选择环境文件。

## 环境文件与选择约定

负责人在后端工作目录将 `.env.dev.example`、`.env.prod.example` 分别复制为 `.env.dev`、`.env.prod` 并自行填值；两份实际配置均不提交，模板只使用 `REPLACE_*` 占位符，不写真实库名、角色名、bucket 或凭据。

```bash
cp -n backend/.env.dev.example backend/.env.dev
cp -n backend/.env.prod.example backend/.env.prod
chmod 600 backend/.env.dev backend/.env.prod
```

- `APP_ENV_FILE` 是唯一文件选择器，默认指向后端目录 `.env.dev`，不受启动 cwd 影响；除该选择器外，应用不读取继承的设置环境变量，系统环境变量不覆盖文件值。
- 文件缺失、必填项缺失或空白、字段格式错误均在启动时报告字段并终止，任何已写出字段不允许为空，配置或连接失败不回退其他文件。
- `ENVIRONMENT` 区分 dev/prod；`DATABASE_URL` 为应用连接，`MIGRATION_DATABASE_URL` 与 `MIGRATION_OWNER_ROLE` 仅用于单独迁移进程，不传入常驻服务。
- 密钥生成：`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`；`JWT_SECRET` 与 `FILE_URL_SECRET` 分别生成至少 32 字节随机值，两环境独立。连接 URL 中的密码含 `@`、`:`、`/`、`#`、`%` 等字符时必须 percent-encoding 用户名/密码部分，不编码整个 URL、不在报告中打印 URL。
- HTTP 验收客户端、WebSocket 本机连接及 OSS SDK 不读取隐式环境代理，OSS SDK 不读取 netrc 认证，避免终端配置改变既定连接目标。

## PostgreSQL 资源准备

优先使用跨平台交互式初始化器（Linux／macOS／Git Bash 用 `bash scripts/init_database.sh --env-file .env.dev`，Windows 用 `scripts\init_database.ps1`，CMD 用 `init_database.bat`）。初始化器从指定 dotenv 读取应用、迁移、owner 角色、数据库与 schema，实例管理员用户名和隐藏密码只在交互终端输入；按下方权限规则创建全新资源并调用正式 Alembic 迁移，业务管理员仍由独立 seed 初始化。迁移中断后修复原因，用同一入口追加 `--resume-migrations` 仅继续建表。遇到同名数据库或角色立即停止，不接管已有资源、不重置密码。

手动准备（psql）要点：每环境建 owner（NOLOGIN）、migrator（LOGIN NOINHERIT）、app（LOGIN NOINHERIT）三个角色，`GRANT owner TO migrator`；`CREATE DATABASE … OWNER <owner> TEMPLATE template0 ENCODING 'UTF8'` 并 `REVOKE ALL ON DATABASE … FROM PUBLIC`；库内 `REVOKE ALL ON SCHEMA public FROM PUBLIC`、`CREATE SCHEMA app AUTHORIZATION <owner>`，app 角色 `GRANT USAGE ON SCHEMA app`，并由 owner 的默认权限授予表 DML 与序列 USAGE；`ALTER ROLE … IN DATABASE … SET search_path = app` 与 `timezone = 'UTC'`。口令用 `\password` 交互输入，`SET password_encryption = 'scram-sha-256'`；`CREATE DATABASE` 不放进事务，`\connect` 单独执行。迁移自动对审计表授 SELECT/INSERT 并撤销 UPDATE/DELETE/TRUNCATE，对对象登记表撤销 DELETE/TRUNCATE；迁移后应核对实际授权。生产 PostgreSQL 18 实测过该角色模型；远程生产连接使用受信 CA 的 TLS。

验证：`psql -U <app> -d <db> -c 'SELECT current_user, current_database(), current_schema();'` 预期 schema 为 app；test 与 prod 用户互连应被拒绝。资源交接只提供版本、host/port、库名、角色名与连通结果，密码由负责人填写本地配置。

## 数据库迁移与初始化

```bash
(cd backend && .venv/bin/python -m app.manage migrate)   # 建立与升级结构，保留已有数据
(cd backend && .venv/bin/python -m app.manage seed)      # 交互初始化部署管理员与可选分类
```

`seed` 交互输入管理员邮箱与初始密码；已有正常管理员沿用，邮箱对应其他角色或受限账户时输出状态提示并结束。可用参数显式指定：`--admin-email admin@example.com --category '书籍教材' --category '数码产品'`，已有同名分类或别名时沿用。需要第二名管理员时用 `--admin-email` 再次运行。部署管理员及参考数据持久保留，不由自动化清理。

演示数据按[演示数据与操作路线](demo-seed.md)执行 `app.manage demo-seed`；随后用 `app.manage demo-verify` 做只读校验。

## 服务托管

```bash
./scripts/dev.sh start     # 后台启动三端
./scripts/dev.sh restart   # 停止后按启动流程重启，加载最新后端代码与配置
./scripts/dev.sh status    # 查看托管阶段、环境文件、各服务 PID 与日志路径
./scripts/dev.sh stop      # 联动停止全部服务，保留数据
```

| 服务 | 地址 |
|---|---|
| 后端 API 文档 | http://127.0.0.1:8000/docs |
| 移动端 | http://localhost:5173 |
| 管理端 | http://localhost:5174 |

首次启动前先 `migrate`、`seed`。脚本每次 `uv sync --frozen`；仅当前端 Vite 不存在时 `npm ci`，前端锁文件变化需先停服手动 `npm ci`。启动等待约 5 秒后可能仅提示 preparing，用 status／日志观察，不重复 start；status 是进程检查，停止时返回 1 不等于异常。日志 `var/log/dev-services.log`，状态 `var/run/dev-services.json`。托管入口不管理单独启动的服务，不要两套并行。后端代码修改经 `restart` 加载；修改 dotenv 后需 stop/start，前端由 Vite 热更新，改代理或依赖需重启 Vite。运行后检查 `/api/health` 与实际页面。

### 分层角色与实时协议

`dev.sh` 托管 API、WS、worker、scheduler 和两套前端。Vite 的 `/api` 与 `/ws` 分别代理到 API、WS 监听端口。手动启动时，从后端目录将以下四条启动命令分别在独立终端运行，再启动两个前端。

```bash
APP_RUNTIME_ROLE=api       .venv/bin/python -m app.manage serve-api
APP_RUNTIME_ROLE=ws        .venv/bin/python -m app.manage serve-ws
APP_RUNTIME_ROLE=worker    .venv/bin/python -m app.manage taskiq-worker
APP_RUNTIME_ROLE=scheduler .venv/bin/python -m app.manage taskiq-scheduler
APP_ENV_FILE=.env.dev .venv/bin/python -m app.manage health --role worker
APP_ENV_FILE=.env.dev .venv/bin/python -m app.manage health --role scheduler
```

split 必须有共享 Redis 与显式 `ALLOWED_ORIGINS`；`ALLOW_QUERY_TOKEN` 仅是非生产过渡。worker readiness 会真实入队 probe，scheduler readiness 读 Redis 调度心跳；两者无 HTTP 端口。移动端先 `POST /api/v1/realtime/ticket` 再连 `/ws?ticket=...`；事件按 `user_seq` 连续应用并 ACK，断线补拉，超期 resync。连接预算按 `API/WS/JOBS_DB_POOL_SIZE`、`TASKIQ_WORKER_PROCESSES` 与 `REDIS_CONTROL_MAX_CONNECTIONS_*`/`TASKIQ_BROKER_MAX_CONNECTIONS` 计算，设置 `DB_CONNECTION_BUDGET`/`REDIS_CONNECTION_BUDGET` 后启动即校验。真实 PostgreSQL+Redis 门禁：

```bash
(cd backend && CI_REALTIME_APPROVED=1 CI_REALTIME_PG_ADMIN_URL=... CI_REALTIME_REDIS_URL=... .venv/bin/python -m tests.integration_real.runner)
backend/.venv/bin/python -m pytest -q scripts/deploy/tests
```

缺少 CI 前置条件时 runner 失败，不 skip；普通离线 pytest 不加载该真实入口。部署/回退与一次性管理员步骤见[部署说明](部署说明.md)和[实时分层实施记录](realtime-layers-implementation.md)。

## 重置测试数据

先停止服务和测试进程，再预览目标：

```bash
./scripts/dev.sh stop
(cd backend && .venv/bin/python -m app.devtools.reset)
```

命令读取 `backend/.env.dev`，校验 dev/test 环境及所选数据库、缓存和存储的有效配置与资源范围并显示资源目标；预览通过后填写显示的数据库名执行：

```bash
(cd backend && .venv/bin/python -m app.devtools.reset --execute --confirm <数据库名>)
```

执行顺序：删除两个 OSS 桶 `STORAGE_KEY_PREFIX` 下的当前对象（测试图片与证据）→ 删除应用 schema 内全部 PostgreSQL 表（含业务数据与审计，保留 schema 及默认授权）→ 删除 `REDIS_KEY_PREFIX` 下的 Redis 键 → 正式迁移重建结构。桶、版本历史、未完成分片及其他前缀对象保留。重置后执行 `seed`、`start`，清除浏览器登录状态重新登录。OSS 前缀为空时预览显示 `[整个桶]`，确认两桶均为测试专用后追加 `--whole-buckets` 清理整桶。配置错误输出说明，底层执行错误隐藏敏感异常。

按配置组合：SQLite 删除库文件及 WAL/SHM/journal 后重建；local 清理并重建 `STORAGE_LOCAL_ROOT` 目录（SQLite 文件在对象目录之外）；memory 在停止时释放、启动时重建。

### 生产环境重置与重新生成演示数据

生产用同一入口，必须显式 `--env-file .env.prod --allow-production`，默认仅预览；执行要求数据库名确认，空 OSS 前缀另要求 `--whole-buckets`。先暂停发布、完成 PostgreSQL/Redis 备份并停止后端（备份脚本不含 OSS）。生产机以 deploy 身份进入当前 release 的 backend 执行，删除范围含管理员、业务记录、审计与迁移表并自动迁移重建；不删 schema 或数据库本身，跨服务无整体事务，失败保持停止、核对已完成阶段后重试。该工具不停止服务、不自动备份、不清理 OSS 历史版本、不修改 shared 配置。

旧演示 manifest 在重置后不再适用，先归档 `/srv/se-course-project1/shared/demo-manifest.json` 再执行：

```bash
.venv/bin/python -m app.manage demo-seed --env-file .env.prod \
  --manifest /srv/se-course-project1/shared/demo-manifest.json
```

成功后启动后端服务并核对健康接口与演示账号登录；命令仅在包含本次 reset 更新的 release 中可用。

## 关键配置矩阵

| 配置 | `.env.dev` | `.env.prod` | 集成配置 |
|---|---|---|---|
| ENVIRONMENT | `dev` | `prod` | `test` |
| DATABASE_URL | 必填：SQLite 或 PostgreSQL URL | 必填：PostgreSQL URL | 必填：PostgreSQL URL |
| DATABASE_SCHEMA | `app` | `app` | `app`；自动化 runner 每轮生成随机 schema |
| OSS_MEDIA_BUCKET / OSS_EVIDENCE_BUCKET | local 时不需要；OSS 时必填 | 必填 | 必填 |
| OSS_ENDPOINT / OSS_REGION / OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET | OSS 时必填（单 RAM 用户 AK） | 必填 | 必填 |
| STORAGE_LOCAL_ROOT | 全无 OSS 字段时必填 | — | — |
| SMTP_HOST / SMTP_PORT / SMTP_SECURITY / SMTP_USERNAME / SMTP_PASSWORD / SMTP_FROM_EMAIL / SMTP_FROM_NAME | 必填（端口默认 465，安全模式 `ssl` 或 `starttls`；超时默认 10 秒） | 必填 | 自动化用隔离 capture outbox，不连接真实 SMTP |
| REDIS_URL / REDIS_KEY_PREFIX | 用 Redis 时必填，前缀 `dev:` | 必填，前缀 `prod:` | Redis 模式必填，自动化用每轮随机前缀 |
| AUDIT_TRUSTED_PROXIES | 必填：`none` 或 IP/CIDR 列表 | 必填 | 必填 |
| DB_AUTO_CREATE | 必填 | 必填：`false` | 必填：`false` |
| API_HOST / API_PORT | 可选，默认 `127.0.0.1:8000` | 必填（生产为 `127.0.0.1:8001`） | — |

配置推断规则：`DATABASE_URL` 协议决定数据库类型；配 `REDIS_URL` 时必须配非空 `REDIS_KEY_PREFIX`，两项均省略用内存 KV；任一 OSS 字段存在必须配齐 OSS 字段，全无则必须配 `STORAGE_LOCAL_ROOT`，OSS 模式失败不静默退回 local。SMTP 各项缺失或仍为占位值拒绝启动。前端从同一 dotenv 仅读取 `VITE_API_BASE_URL`、`VITE_API_TIMEOUT_MS`、`API_PROXY_TARGET`（默认 `/api/v1`、15000ms、`http://127.0.0.1:8000`），构建经后端集中加载器校验，Vite 自身 dotenv 加载已禁用。

## 图片直传与读取配置

移动端先经带登录态的 API 创建短期上传租约（文件名、MIME、字节数、浏览器计算的 SHA-256），再按租约返回的 method、URL 与签名 headers 直传对象存储，不发送应用 Bearer token；上传完成后调用完成接口，后端核对 HEAD 元信息后有界读取实际对象校验 SHA256 与 Pillow 完整性，确认后才可用于业务引用。过期或失败的租约不复用，重试重新申请。

图片读取使用私有桶短期签名 GET 直链，链接有效期与 `FILE_URL_EXPIRE_SECONDS` 一致，进程内复用未到期链接；签名链接按敏感数据处理，不写日志或验收报告。对象存储 CORS 需为实际前端 origin 显式配置 `PUT` 及 `Content-Type`、`x-oss-meta-sha256`、`x-oss-forbid-overwrite` 请求头，不启用任意 origin 或凭据共享；跨域直传须按浏览器实测。

## 自动化验收与目标隔离

数据库、存储与 KV 后端由所选 dotenv 明确配置；迁移、持久化初始化、服务与自动化验收是不同入口，测试与 seed 不使用 `--profile`。

```bash
(cd backend && RUN_REAL_ACCEPTANCE=1 .venv/bin/python -m pytest -q)
# 同一套测试的 CLI 入口（指定端口）
(cd backend && .venv/bin/python -m tests.acceptance_real.runner --port 8107)
```

runner 内置自动化 seed，每轮生成随机 schema、私有临时 dotenv、OSS prefix（或本地临时目录）与 Redis prefix，成功与失败路径均清理本轮全部资源，不删除共享数据。自动化身份仅由 runner 临时 seed 创建；持久化管理员由 `seed` 独立建立；普通测试角色经注册流程产生。生产配置不得意外用于开发验收，命令不会自动创建生产资源。上传租约签发即登记 staged，完成前及失败后禁止业务引用；租约有效期内不物理回收对象。全量结果、覆盖率与清理复验状态见[整体验收](整体验收.md)；浏览器人工流程要点同文件。测试通过时不保留测试报告；未通过时仅生成 `var/acceptance-real/acceptance-failure-<run_id>.log`（只含未通过项与调试信息），覆盖率产物为 `var/acceptance-real/code-coverage/<hash>/` 下的 coverage 原生 HTML／JSON／XML／TXT。

## 对象运维、举报证据与审计

上传中断留下的暂存对象用 `(cd backend && .venv/bin/python -m app.devtools.objects --delete)` 回收，回收器按租约到期与实时业务引用核验后删除，默认不带 `--delete` 只列出。

举报列表提供概要；认领管理员在事项详情查看初次证据、补充说明及补充证据，举报人从本人举报记录查看已提交材料。举报及补充表单复用本次会话已上传图片的 key，提交失败重试沿用成功上传对象；关闭表单或移除图片后释放前端缓存。证据桶暂存对象遵循证据保护策略，租约到期后由明确的保留与回收策略管理。

审计留存可归属到用户 ID 的操作及标记为 system 的任务；未识别操作人的请求经访问日志排查。迁移清理历史匿名审计，保留账户事件与系统任务事件。审计页默认展示最近 7 天分类数量、结果概览与每日趋势，可切换 30 天；点击分类填入筛选后查询分页明细，重置回到待查询状态，概览经数据库聚合接口读取。

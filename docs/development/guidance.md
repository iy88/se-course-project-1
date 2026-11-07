<!--
Version: 0.2.5
Version-Datetime: 2026-11-08T00:11:20+08:00
-->

# 开发指南

## 环境准备

支持 macOS、Linux 和 Windows 11。开发需要 Python 3.12 或以上、uv、Node.js、npm、PostgreSQL、Redis 8.2 或以上，以及 OSS 媒体桶、证据桶和 SMTP 服务。以下 sh 命令从仓库根目录执行；Windows 使用对应的 PowerShell 或 CMD 包装入口。

```bash
(cd backend && uv sync --frozen)
(cd frontend/mobile && npm ci)
(cd frontend/admin && npm ci)
cp -n backend/.env.dev.example backend/.env.dev
chmod 600 backend/.env.dev
```

编辑 `backend/.env.dev` 填写开发资源。`APP_ENV_FILE` 选择环境文件，相对路径按后端目录解析，默认使用 `.env.dev`。

| 配置项 | 用途与填写方式 |
|---|---|
| `ENVIRONMENT`、`DATABASE_SCHEMA`、`DB_AUTO_CREATE` | 使用 `dev`、`app`、`false` |
| `DATABASE_URL` | PostgreSQL 应用连接，协议为 `postgresql+asyncpg://` |
| `MIGRATION_DATABASE_URL`、`MIGRATION_OWNER_ROLE` | 同一数据库的迁移连接与所有者角色 |
| `REDIS_URL`、`REDIS_KEY_PREFIX` | Redis 地址与开发专用非空前缀 |
| `OSS_*` | 私有媒体桶、证据桶、地域、HTTPS endpoint 与访问凭据 |
| `JWT_SECRET`、`FILE_URL_SECRET` | 分别生成的随机密钥 |
| `SMTP_*` | SMTP 主机、端口、安全模式、登录凭据和发件人 |
| `ALLOWED_ORIGINS` | 实际前端来源，如 `http://localhost:5173` |
| `AUDIT_TRUSTED_PROXIES` | 可信直连代理 IP/CIDR；直连开发使用 `none` |

密钥可通过 `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` 生成。数据库连接中的用户名、密码按 URL 用户信息规则编码。实际配置文件采用仅当前用户可读写的权限。

## 数据库初始化

首次使用时，初始化器根据配置创建数据库、owner、migrator 和 app 角色，再执行 Alembic 迁移；PostgreSQL 管理账号及密码通过终端交互输入。

| 平台 | 初始化命令 |
|---|---|
| macOS / Linux | `bash scripts/init_database.sh --env-file .env.dev` |
| Windows PowerShell | `.\scripts\init_database.ps1 --env-file .env.dev` |
| Windows CMD | `scripts\init_database.bat --env-file .env.dev` |

后续结构升级与管理员初始化在后端目录执行：

```bash
(cd backend && .venv/bin/python -m app.manage migrate)
(cd backend && .venv/bin/python -m app.manage seed)
```

`seed` 交互输入管理员邮箱和初始密码。`--admin-email` 指定管理员邮箱，重复的 `--category` 参数创建初始分类，例如 `--category '书籍教材' --category '数码产品'`。管理员及参考数据持久保存在所选数据库中。

## 启动与日常操作

```bash
./scripts/dev.sh start
./scripts/dev.sh status
./scripts/dev.sh restart
./scripts/dev.sh stop
```

PowerShell 使用 `.\scripts\dev.ps1`，CMD 使用 `scripts\dev.bat`，子命令相同。启动器管理 API、WS、Taskiq worker、单实例 scheduler 和两个 Vite 前端。

| 服务 | 默认入口 |
|---|---|
| API | `http://127.0.0.1:8000` |
| API 交互文档 | `http://127.0.0.1:8000/docs` |
| WS | `ws://127.0.0.1:8002/ws` |
| 移动端 | `http://localhost:5173` |
| 管理端 | `http://localhost:5174` |

Vite 将 `/api` 和 `/ws` 分别代理到 API 与 WS。启动器状态位于 `var/run/dev-services.json`，托管日志位于 `var/log/dev-services.log`。后端代码或配置变更后重启服务；前端界面由 Vite 热更新，依赖或代理配置变更后重启前端。

需要分别启动角色时，在 `backend/` 的独立终端执行：

```bash
.venv/bin/python -m app.manage serve-api
.venv/bin/python -m app.manage serve-ws
.venv/bin/python -m app.manage taskiq-worker
.venv/bin/python -m app.manage taskiq-scheduler
```

## 演示数据

`demo-seed` 向所选环境添加演示账号、商品、交易、举报、事项、消息和图片。场景定义与素材由 `backend/app/devtools/demo_scenarios/` 统一维护。

```bash
(cd backend && .venv/bin/python -m app.manage demo-seed \
  --env-file .env.dev --manifest ../var/demo/manifest.json)
```

清单 `accounts` 包含账号与密码，`objects` 和 `object_kinds` 包含对象 ID 及类型，`scenarios` 列出可演示场景。清单采用私有文件权限；每个新批次使用新的清单路径。中断后用同一路径继续，命令会检查已登记对象并补全创建过程。

| 演示入口 | 账号与操作 |
|---|---|
| 商品浏览与互动 | `buyer` 浏览、搜索、收藏、评论；`seller` 发布和维护商品 |
| 审核与分类 | `admin` 认领审核、形成结论、处理标签与维护分类；`admin2` 展示多管理员协作 |
| 请求与交易 | 买卖双方推进购买请求、交付约定、完成确认及取消流程 |
| 争议与异常 | 对应买卖双方与管理员展示争议、冻结、超时处理和状态调整 |
| 举报与申辩 | 举报人提交材料，认领管理员问询和形成结论，被处置方查看与申辩 |
| 消息与通知 | 普通会话、交易分支、事项沟通及通知按各自入口查看 |

演示按“公开浏览 → 商品审核 → 交易推进 → 争议与举报 → 通知、统计和分类”展开。各分支使用清单内对应的独立对象；服务启动后，超时任务按业务规则推进已到期交易。验证码流程使用实际可收件邮箱和 SMTP 配置。

## 重置开发数据

先停止托管服务及其他访问该环境的进程，再预览所选资源：

```bash
./scripts/dev.sh stop
(cd backend && .venv/bin/python -m app.devtools.reset --env-file .env.dev)
```

核对预览中的数据库、Redis 前缀和存储范围，把输出的确认值填入执行命令：

```bash
(cd backend && .venv/bin/python -m app.devtools.reset \
  --env-file .env.dev --execute --confirm '<预览中的确认值>')
```

执行顺序为存储当前对象、应用 schema 表、Redis 命名空间清理，再运行迁移重建结构。OSS 采用前缀范围；专用整桶重置通过 `--whole-buckets` 显式选择。随后重新执行 `seed`，为演示数据使用新的 manifest，再启动服务并重新登录。

## 暂存对象管理

在后端目录运行 `.venv/bin/python -m app.devtools.objects` 查看回收候选，添加 `--delete` 执行回收。回收器检查租约到期、对象登记和实时业务引用；举报证据按证据保护策略保存。

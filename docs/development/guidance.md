<!--
Version: 0.1.0
Version-Datetime: 2026-10-30T22:36:10+08:00
-->

# 开发与人工测试指南

以下命令从项目根目录执行。应用默认读取 `backend/.env.dev`；通过 `APP_ENV_FILE` 选择环境文件。准备好 PostgreSQL、Redis、OSS 配置并启动 PostgreSQL、Redis 后，按需执行以下命令。

## migrate：建立与升级数据库结构

```bash
(cd backend && .venv/bin/python -m app.manage migrate)
```

PostgreSQL 使用迁移账户切换到 owner 角色，将配置的应用 schema 升级到最新版本，保留已有业务数据。SQLite 创建表并补充兼容结构。

## seed：初始化管理员与分类

```bash
(cd backend && .venv/bin/python -m app.manage seed)
```

交互输入管理员邮箱；新管理员继续输入并确认初始密码。已有正常管理员沿用原账户。邮箱对应其他角色或受限账户时，命令输出账户状态提示并结束。

使用参数指定邮箱与分类：

```bash
(cd backend && .venv/bin/python -m app.manage seed \
  --admin-email admin@example.com \
  --category '书籍教材' --category '数码产品')
```

每个 `--category` 添加一个分类；已有有效同名分类或别名时沿用现有记录。成功后输出管理员 ID 和分类处理数量。

## start：后台启动三端服务

```bash
./scripts/dev.sh start
```

同步 Python 锁定依赖，按需安装前端依赖，在后台启动并托管三个服务：

| 服务 | 地址 |
|---|---|
| 后端 API 文档 | http://127.0.0.1:8000/docs |
| 移动端 | http://localhost:5173 |
| 管理端 | http://localhost:5174 |

首次启动前执行 `migrate`、`seed`。服务运行期间由后台管理进程跟踪子进程；任一服务退出时联动停止其余服务。

## status：查看托管进程状态

```bash
./scripts/dev.sh status
```

显示后台管理进程的运行阶段、环境文件、各服务进程状态与 PID，以及日志路径。结果用于检查进程运行情况。

## stop：停止托管服务

```bash
./scripts/dev.sh stop
```

通知后台管理进程退出，联动停止本次托管的后端、管理端和移动端，保留数据库、缓存与存储数据。

## reset：重置人工测试数据

先停止服务和测试进程，再预览目标：

```bash
./scripts/dev.sh stop
(cd backend && .venv/bin/python -m app.devtools.reset)
```

命令读取 `backend/.env.dev`，校验 dev/test 环境及所选数据库、缓存和存储的有效配置与资源范围，显示资源目标。预览通过后填写显示的数据库名执行：

```bash
(cd backend && .venv/bin/python -m app.devtools.reset \
  --execute --confirm <数据库名>)
```

执行顺序与范围：

1. 删除媒体桶、证据桶中 `STORAGE_KEY_PREFIX` 下的当前 OSS 对象，包括测试图片与证据。
2. 删除应用 schema 内全部 PostgreSQL 表，包括账户、业务数据和审计记录，保留 schema 及其默认授权。
3. 删除 `REDIS_KEY_PREFIX` 下的 Redis 键。
4. 执行正式数据库迁移，重建最新表结构。

OSS 桶、版本历史、未完成分片上传及其他前缀的对象继续保留。各服务按顺序独立执行；发生错误时输出完整异常，修复原因后重新运行。

重置完成后执行 `seed`、`start`，清除浏览器原登录状态并重新登录，开始新一轮人工测试。

OSS 前缀为空时，预览显示 `[整个桶]`。确认两个配置桶均为测试专用后，使用以下命令清理整桶当前对象并重置数据库与 Redis：

```bash
(cd backend && .venv/bin/python -m app.devtools.reset \
  --execute --confirm <数据库名> --whole-buckets)
```

### SQLite、本地文件与内存缓存

`reset` 按配置组合执行：PostgreSQL 或 SQLite、Redis 或 memory、OSS 或 local。

- SQLite：删除数据库文件及其 WAL、SHM、journal 文件，再通过 `migrate` 建立最新表结构。`--confirm` 填写预览中 `Confirmation` 显示的数据库文件名。
- local：清理 `STORAGE_LOCAL_ROOT` 对应的本地存储目录并重新创建空目录。SQLite 文件存放在对象目录之外。
- memory：停止服务时释放进程内缓存，重新启动时创建空缓存。

本地组合示例：

```bash
(cd backend && .venv/bin/python -m app.devtools.reset)
(cd backend && .venv/bin/python -m app.devtools.reset --execute --confirm test.db)
```

## oss dangling
上传中断后留下的暂存对象通过 `(cd backend && .venv/bin/python -m app.devtools.objects --delete)` 回收，回收器按租约到期时间和实时业务引用核验后执行删除。
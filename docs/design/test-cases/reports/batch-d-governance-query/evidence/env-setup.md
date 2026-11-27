# 批次 D 环境准备证据（D-RUN-01 前置）

记录时间：2026-11-26T21:5x +08:00（系统时钟在本会话内出现过跳变，构建与探针以日志内时间为准）。

## 代码与构建

| 项目 | 实际值 |
|---|---|
| 分支 | `test/evidence-governance-query-sourmoon`（自 `origin/main` `5bbe4f0e` 建立；Issue 基线 `23d89def`，中间仅叠加文档与前端小改动） |
| 工具链 | OpenJDK 27（`C:\tools\jdk-27`）、Maven 3.10.1（`C:\tools\apache-maven-3.10.1`）、Node 26.13.1 |
| 构建命令 | `mvn -f backend/pom.xml -DskipTests install` |
| 构建结果 | BUILD SUCCESS，`backend-app-0.0.1-SNAPSHOT.jar` 82 MiB（可执行 fat jar） |
| 构建阻塞与处理 | ① 沙箱禁止写 `~/.m2`，首次构建在父 POM 解析时失败 → 以完整访问权限重试；② 旧 API 进程（PID 34204）锁定旧 jar 导致 `repackage` 失败 → 结束该进程后重跑 |

## 数据库与 Redis

| 项目 | 实际值 |
|---|---|
| 目标 | PostgreSQL 18.7 `127.0.0.1:5432/project1_s1`；Redis `127.0.0.1:6379` db=0，命名空间 `project1:s1:local` |
| 重置原因 | 迁移历史与 `main` 不一致（仅 7 条、版本 5.75/7 混排，缺 V5.77 及 V8—V24），`db migrate` 与 `db validate` 均因 `FlywayValidateException` 失败 |
| 重置命令 | `db reset --env-file=backend/.env.dev`（预览令牌 `2af5ff739052d57e`），随后 `--confirm` 执行 |
| 重置结果 | PostgreSQL 重建并应用 25 条迁移，`now at version v25.147`；Redis 清除 0 个键（此前无键） |
| 影响 | 数据库与 Redis 中的既有开发数据被清空；OSS 未执行 reset（对象保留） |

## 依赖探针（`--spring.profiles.active=dependency-probe`）

| 依赖 | 结果 | 依据 |
|---|---|---|
| PostgreSQL | 通过 | `PostgreSQL schema validation and JPA query passed (probe row ID 1)` |
| Redis | 通过 | `Redis probe read, write and cleanup passed` |
| OSS | 通过 | `OSS private bucket, versioning, object write, read and cleanup passed`（真实阿里云私有桶） |
| SMTP | **失败** | `IllegalStateException: SMTP probe failed (MailSendException)`；`.env.dev` 中 `SMTP_HOST=smtp.example.com`、`SMTP_FROM=<redacted-email>` 为占位值 |

结论：批次 D 的真实依赖中 SMTP 未就绪，阻断「真实邮件注册」；其余依赖可用。

## 配置同步

本地 `backend/.env.dev` 停留在 S2 时期，缺 36 个 `main` 必需的配置键（账户策略、交易策略、分页、商品与评论限制、邮件投递、`ACCOUNT_ENTRY_SIGNING_KEY` 等），导致首次启动报 `ACCOUNT_ENTRY_SIGNING_KEY must contain at least 32 bytes`。已按 `backend/.env.dev.example` 补齐缺失键，签名密钥随机生成；数据库/Redis/OSS/SMTP 的既有值保持不变。`.env.dev` 由 `.gitignore` 排除，未提交。

## 运行中的服务

| 服务 | 端口/PID | 状态 |
|---|---|---|
| API | 8080（PID 15848） | `/actuator/health` 200；启动日志 `Started BackendAppApplication` |
| 用户端 | 3000（PID 45504） | rsbuild dev server 就绪 |
| 管理端 | 3001 | 同上 |
| scheduler / worker-1 / worker-2 | PID 48844 / 45884 / 32824 | 由 `scripts/dev.ps1` supervisor（PID 45704）管理 |

## 测试驱动（本机，未提交）

- `var/batch-d/lib/api.mjs`：Node HTTP 驱动，按账户持久化 Cookie（含 Secure Cookie 显式回放）、自动 `X-CSRF-Token` 与 `Idempotency-Key`，请求记录写入 `var/batch-d/evidence/http.log`（密码与验证码字段已脱敏）。
- `var/dbtool/DbQ.java`：只读 JDBC 查询工具（`DbQ <env-file> "<sql>" [owner]`），用于对账 SQL 与历史记录核对（本机无 `psql`）。
- 已验证：`GET /api/v1/account/entry-context` 返回 200 与 `csrf_token`，驱动可正常保存 entry Cookie。

## 待补前置

1. 真实 SMTP 配置（`SMTP_HOST`／`SMTP_PORT`／`SMTP_TLS_MODE`／`SMTP_USERNAME`／`SMTP_PASSWORD`／`SMTP_FROM`）。
2. 两个管理员账户：`account create-manager` 必须由真实终端输入密码，需在交互终端执行（`<redacted-email>`、`<redacted-email>`）。
3. 6 个普通账户（`qa-seller`、`qa-buyer-a`、`qa-buyer-b`、`qa-outsider`）通过真实邮件验证码注册。

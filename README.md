<!--
Version: 0.1.39
Version-Datetime: 2026-11-19T13:03:27+08:00
-->

# 校园二手交易与物品流转平台

## GitHub Actions 检查

向 `main` 提交 PR 或推送到 `main` 时，CI 在 Linux 上并行运行后端与前端检查。后端使用 OpenJDK 27 和 Maven Wrapper 执行 `verify`。前端使用 Node.js 26.13.1 和 pnpm 12.5.1，按锁文件安装依赖，核对 OpenAPI 生成类型、lint 和格式，再对用户端和管理端分别做类型检查与构建。

## 一键启动开发环境

在 macOS 或 Linux 上，从仓库根目录执行。首次运行或后端代码更新后重新构建 JAR，前端锁文件更新后重新安装依赖。

```bash
mvn -f backend/pom.xml verify
pnpm --dir frontend install --frozen-lockfile
python3 scripts/dev.py start
python3 scripts/dev.py status
python3 scripts/dev.py restart
python3 scripts/dev.py stop
```

脚本默认读取 `backend/.env.dev`，在后台启动后端、用户端 `http://127.0.0.1:3000` 和管理端 `http://127.0.0.1:3001`。先按下文配置并初始化 PostgreSQL 和 Redis。使用其他配置文件时，给 `start` 或 `restart` 加上 `--env-file <路径>`。Rsbuild 默认代理到本地 8080，后端使用其他地址时，设置 `API_PROXY_TARGET` 覆盖。

PID 记录在 `var/dev/dev.pid`，日志写入 `var/dev/dev.log`，可用 `tail -f var/dev/dev.log` 查看。`status` 显示托管进程状态，后端或任一前端进程退出时，脚本会停止本次启动的其他服务。

## 前端安装、启停与构建

前端使用 Node.js 26.13.1、pnpm 12.5.1、Vue 3、TypeScript 和 Rsbuild（Rspack）。Node.js 版本记录在 `frontend/.nvmrc`，pnpm 版本记录在 `frontend/package.json`。两个应用共用 `frontend/pnpm-lock.yaml`。首次安装或锁文件更新后，在 `frontend/` 运行 `pnpm install --frozen-lockfile`。

先按下节启动后端。另开终端，在 `frontend/` 用以下任一命令启动。

```bash
pnpm dev         # 同时启动两端
pnpm dev user    # 仅启动用户端
pnpm dev admin   # 仅启动管理端
```

两端共用 `frontend/shared/rsbuild.ts` 的开发代理，默认将 `/api/v1` 转发到 `http://127.0.0.1:8080`。后端使用其他地址时，可通过环境变量 `API_PROXY_TARGET` 覆盖 Rsbuild 的代理目标。

在浏览器打开用户端 `http://127.0.0.1:3000` 或管理端 `http://127.0.0.1:3001`。两个页面都通过 Axios XHR 请求同源的 `/api/v1/hello`，看到 `Hello, Project1!` 即可确认接口连通。用户端采用移动优先布局，适配桌面浏览器。在启动终端按 `Ctrl+C` 停止本次启动的服务。

```bash
pnpm lint                      # Oxlint
pnpm run format:check          # Oxfmt 检查
pnpm format                    # Oxfmt 格式化
pnpm typecheck                 # 两个应用的 Vue / TypeScript 类型检查
pnpm build                     # 构建两个应用
pnpm --filter user-web build   # 仅构建用户端
pnpm --filter admin-web build  # 仅构建管理端
```

更新 `frontend/shared/openapi.json` 中的接口契约后，在 `frontend/` 执行 `pnpm run generate:api` 来重新生成共享 TypeScript 类型。构建产物分别输出到两个应用的 `dist/`。部署时由 Nginx 提供各端的静态文件，并在同一站点代理 `/api/v1/`。

## 后端编译与启停

后端使用 OpenJDK 27、Spring Boot 4.1.2 和 Maven 3.10.1。从仓库根目录进入 `backend/`，使用本机 Maven 或仓库的 `./mvnw`（Windows 使用 `mvnw.cmd`）。本机 Maven 可通过 `~/.m2/settings.xml` 使用已配置的下载镜像。

```bash
cd backend
mvn verify                         # 构建并测试所有模块，生成可执行 JAR
mvn -pl backend-app -am test         # 只测试启动模块及其 Maven 依赖模块
java -jar backend-app/target/backend-app-0.0.1-SNAPSHOT.jar --env-file=.env.dev
```

应用监听 `.env.dev` 中的 `HTTP_BIND_HOST` 和 `HTTP_BIND_PORT`。例如配置为本机 8080 时，可用 `curl -fsS http://127.0.0.1:8080/api/v1/hello` 和 `curl -fsS http://127.0.0.1:8080/actuator/health` 检查。服务在前台运行，在启动终端按 `Ctrl+C` 停止。

### 安装内部模块到本机 Maven 仓库

在 `backend/` 下运行 `mvn install`，按依赖顺序构建所有模块，执行测试和验证，并把生成的 JAR 和 POM 安装到本机 Maven 仓库（默认 `~/.m2/repository`）。IDE 或独立构建的子模块可以从这里解析项目内部依赖。

```bash
mvn install
```

只需要后端应用、维护工具及它们依赖的模块时，可以按需安装：

```bash
mvn -pl backend-app,maintenance -am install
```

整仓或 CI 构建检查用 `mvn verify` 即可。同一次多模块构建会直接解析参与构建的内部模块。

### 后端模块与包

`BackendAppApplication` 放在 `io.github.iy88.project1` 根包。启动期的参数、环境加载和校验集中在 `backend-app` 的 `bootstrap` 包。将 Maven 模块加入应用依赖后，根包下的 Spring 组件以及 JPA 实体和 Repository 可由 Spring Boot 按类型扫描。业务服务和项目自有适配器用组件注解和构造器注入。SDK 客户端等需要显式装配的对象由对应模块的配置类注册。

`backend-app` 使用 Lombok 的 `@RequiredArgsConstructor` 为 Spring 组件的 `final` 依赖字段生成构造器。Maven 显式配置注解处理器。配置值通过 `@ConfigurationProperties` 绑定和校验。

| 位置 | 职责 |
| --- | --- |
| `backend-app` 的 `api.<业务>` | Controller、HTTP 请求和响应 DTO，负责参数校验和传输映射 |
| 业务模块的 `application` | 用例服务及跨模块使用的命令、查询和具名输入输出 |
| 业务模块的 `domain` | 业务规则、状态和领域对象 |
| 业务模块的 `persistence` | JPA 实体、Spring Data Repository、必要的显式 SQL |

按实际需要建立包。跨模块协作由应用层调用各模块公开服务，传递 ID 和具名输入输出。持久化实体与 Repository 由其所属模块管理。文件服务按同一规则组织，作为首个正式基础设施服务接入。

## S1 开发环境与依赖探针

从 `backend/` 复制配置样例，然后在本地编辑。Git 已忽略 `.env.dev`。文件使用 Java properties 语法，值直接写在等号后，避免加引号，反斜杠写成两个反斜杠。

`.env.example` 中的值用于示范格式。复制后请在 `.env.dev` 中填入实际的依赖地址、资源名和凭据。`DATABASE_URL` 必须包含数据库名。应用和维护工具会在连接前报出缺少的配置项。

```bash
cd backend
(umask 077 && cp -n .env.example .env.dev)
chmod 600 .env.dev
```

用下面的命令生成 URL-safe 密码。PostgreSQL 的 `app`、`owner` 和 Redis ACL 用户分别生成一次。输出可直接用作 `.env.dev` 的密码值，也可放入 `REDIS_URL` 的密码部分。

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

| 资源 | 配置与权限 |
| --- | --- |
| PostgreSQL | 填写 `DATABASE_URL=jdbc:postgresql://主机:5432/project1_dev`、应用账号的 `DATABASE_USERNAME` 和 `DATABASE_PASSWORD`，以及迁移账号的 `DATABASE_OWNER_USERNAME` 和 `DATABASE_OWNER_PASSWORD`。维护工具按配置创建数据库和缺失角色。 |
| Redis | 设置 `REDIS_URL` 和独立的 `REDIS_NAMESPACE`，例如 `project1:dev:iy88`。ACL 用户连接串示例为 `rediss://project1_dev:URL编码后的密码@主机:6380/0`，无 TLS 的本地实例用 `redis://`。ACL 将键限制到 `~project1:dev:iy88:*`。探针使用 `GET`、`SET`、`DEL`，Spring Boot 的健康检查还需要 `INFO`。下方有单机 Redis 的 ACL 示例。 |
| OSS | 使用独立开发 Bucket，设置为私有，保持版本控制从未开启。开发 RAM 用户绑定下方的自定义策略。填写 `OSS_REGION`（如 `cn-hangzhou`）、对应 HTTPS `OSS_ENDPOINT`、`OSS_BUCKET`、`OSS_PREFIX` 和该 RAM 用户的 AccessKey。 |
| SMTP | 填写服务商提供的 `SMTP_HOST` 和 `SMTP_PORT`，`SMTP_TLS_MODE=starttls` 用于要求 STARTTLS 的端口（常见 587），`ssl` 用于隐式 TLS（常见 465）。`SMTP_USERNAME` 填发送账号，`SMTP_PASSWORD` 填服务商的 SMTP 授权码，`SMTP_FROM` 填获授权的发件地址，可带显示名，例如 `CampusMarket-V2 Dev <example@example.com>`。 |

### OSS Bucket ACL、RAM 和 CORS

后端探针和维护工具共用阿里云 OSS Java SDK 2.0（`com.aliyun:alibabacloud-oss-v2`）。[官方 SDK 文档](https://help.aliyun.com/zh/oss/developer-reference/oss-sdk-for-java-2-0/)

在 OSS 控制台将 Bucket ACL 设为 **私有**，启用阻止公共访问，版本控制保持从未启用。以下策略用于独立开发 Bucket。把 `YOUR-DEV-BUCKET` 换为你的 Bucket 名。第一项授权查询 Bucket ACL、版本状态和列举对象。第二项授权读取、写入和删除该 Bucket 中的所有对象。ARN 中的账号字段可填写 Bucket 所有者的阿里云账号 ID。

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:GetBucketAcl", "oss:GetBucketVersioning", "oss:ListObjects"],
      "Resource": ["acs:oss:*:*:YOUR-DEV-BUCKET"]
    },
    {
      "Effect": "Allow",
      "Action": ["oss:PutObject", "oss:GetObject", "oss:DeleteObject"],
      "Resource": ["acs:oss:*:*:YOUR-DEV-BUCKET/*"]
    }
  ]
}
```

探针直接由后端调用 OSS。浏览器直传接入时，再像 legacy 一样登记实际用户端和管理端 Origin（包含协议和端口）。v2 的签名表单用 `POST`，浏览器直读确实需要时再添加 `GET` 或 `HEAD`。允许头按浏览器实际预检填写，可暴露 `ETag`、`x-oss-request-id`。v2 的禁止覆盖和 ACL 约束由签名表单字段承载。[阿里云 OSS RAM 目录级授权](https://www.alibabacloud.com/help/en/oss/user-guide/access-control-base-on-ram-policy)

### Redis ACL

由管理员在 Redis 交互式客户端执行下例，将密码占位值和键前缀替换为开发环境的值。Redis URL 使用该用户，键模式中的前缀须与 `REDIS_NAMESPACE` 一致。示例适用于 Redis 7.2 及以上版本，使用 Redis 7.0 或 6 时去掉 `+client|setinfo`。托管服务可在控制台应用同等的 ACL。

```text
ACL SETUSER project1_dev reset on >替换为随机密码 ~project1:dev:iy88:* -@all +ping +info +get +set +del +hello +select +client|setinfo +client|setname
```

### 运行方式

从 `backend/` 运行。后端自动启用 `infrastructure` profile，通过必填参数 `--env-file` 指定配置文件，支持绝对路径和相对于当前目录的路径。首次启动前先执行下文的 `db init`，并在 `.env.dev` 中填写 `HTTP_BIND_HOST` 和 `HTTP_BIND_PORT`。核对相应地址上的 HTTP 接口，按 `Ctrl+C` 停止服务。

```bash
java -jar backend-app/target/backend-app-0.0.1-SNAPSHOT.jar \
  --env-file="$PWD/.env.dev"
```

运行一次性探针时，通过 `--smtp-probe-to` 指定一个测试收件地址。替换下面命令中的示例地址即可。探针在启动时校验收件地址，再检查 PostgreSQL 和 Redis、核对 OSS Bucket 并验证探针对象的写入、读回和删除，最后发送一封邮件。进程完成后退出，失败返回非零状态。SMTP 日志显示服务器接收结果和邮件 ID，在收件箱查找同 ID 的 `[Project1 S1] SMTP probe` 邮件以验证投递。

```bash
java -jar backend-app/target/backend-app-0.0.1-SNAPSHOT.jar \
  --spring.profiles.active=dependency-probe \
  --env-file="$PWD/.env.dev" \
  --smtp-probe-to=you@example.com
```

### 初始化与全量重置

从 `backend/` 构建独立维护 JAR。维护工具执行 Flyway，应用启动时由 Hibernate 校验表结构。维护工具通过 `APP_ENV_FILE` 指定项目 `.env` 路径。

`--admin-user` 填目标 PostgreSQL 实例上**已有的管理员登录名**。该账号需要能创建角色和数据库，并将新库的所有权授予 `DATABASE_OWNER_USERNAME`。执行重置时，还需要删除目标库的权限。工具使用该账号连接同一实例的 `postgres` 维护库。`postgres` 是这里的数据库名，管理员登录名由你的实例配置决定。

```bash
mvn -pl maintenance -am verify
export APP_ENV_FILE="$PWD/.env.dev"
printf '%s' '请输入 PostgreSQL 实例的管理员登录名：'
IFS= read -r DB_ADMIN_USER
java -jar maintenance/target/maintenance-0.0.1-SNAPSHOT.jar db init --admin-user "$DB_ADMIN_USER"
```

`db init` 按 `.env.dev` 配置创建缺失的 `owner`、`app` 角色及数据库。管理员、`owner` 和 `app` 使用不同的登录名。管理员密码按终端提示输入，输入时无回显。已有角色沿用现有密码。

`owner` 持有数据库及迁移创建的对象，维护工具从 `DATABASE_OWNER_USERNAME` 和 `DATABASE_OWNER_PASSWORD` 读取凭据执行 Flyway。`app` 只有数据库连接、`public` schema 使用、业务表读写和序列权限，后端使用 `DATABASE_USERNAME` 和 `DATABASE_PASSWORD` 连接。部署新版本先执行 `db migrate`，再启动应用。Jenkins 可将 `APP_ENV_FILE` 指向包含上述数据库配置的维护凭据文件。

```bash
java -jar maintenance/target/maintenance-0.0.1-SNAPSHOT.jar db migrate
```

执行重置前停止所有写入所选环境的应用进程和任务。以下命令只预览。核对打印的环境、服务器和范围后，将输出的 `--confirm TOKEN` 加到对应命令末尾执行。执行 `db reset` 时同时加 `--admin-user "$DB_ADMIN_USER"`，使用上面输入的管理员登录名，并按终端提示输入密码。早期由应用账号持有的测试库可通过确认后的 `db reset` 重建为两角色结构。

```bash
java -jar maintenance/target/maintenance-0.0.1-SNAPSHOT.jar db reset
java -jar maintenance/target/maintenance-0.0.1-SNAPSHOT.jar oss reset
```

- `db reset` 先检查 Redis 能否扫描指定命名空间，再删除并重建 PostgreSQL 目标库、运行 Flyway，最后清空 `REDIS_NAMESPACE:*`。PostgreSQL 有活动连接时拒绝删除。Redis 的维护凭据需具备 `SCAN` 及命名空间内的 `DEL` 权限，在当前 ACL 示例基础上加 `+scan`。
- `oss reset` 清空 `OSS_BUCKET` 内的所有对象，每次批量删除最多 1,000 个。预览显示 `scope=ALL_OBJECTS`。工具从清单中取对象并分批删除，直至清单为空。探针仍使用 `OSS_PREFIX` 生成测试对象键。
- 两个命令分别报告执行结果。重置中途失败时，保持写入停止，修复报错后重新预览并执行对应的完整命令。数据库重置会按同一版本的 Flyway 迁移重建示例数据。

## docs 目录结构

```text
docs/
├── 需求规格说明书.md                   # requirements 章节整合产物
├── 需求分析质量验证报告.md
├── AI智能体使用验证报告.md
├── requirements/                     # 01—08 需求章节源文件
├── appendices/
│   ├── user-stories/                  # 用户故事
│   ├── use-cases/                     # 用例
│   ├── class-analysis/                # 领域类分析
│   ├── scenarios/                     # 场景
│   ├── models/                        # 可编辑模型源文件
│   ├── rendered/                      # 模型 PNG 与摘要记录
│   ├── prototype/                     # HTML 原型
│   ├── evidence/                      # 需求决定及验证依据
│   └── ai-usage/                      # 需求阶段 AI 记录
├── 软件架构设计方案_讨论稿.md          # 架构章节整合产物
├── 软件架构设计方案_基线版.md          # 基线占位
├── 架构确认与决策记录.md               # Q／ADR 整合产物
├── 接口与关键设计说明书.md             # 共享及模块设计整合产物
├── 分阶段实现与测试计划.md             # 计划章节整合产物
└── design/
    ├── 基线索引.md                    # 设计材料入口
    ├── 拼合清单.json                  # 整合文档的源文件顺序
    ├── architecture/                  # 架构章节
    ├── decisions/                     # 决策索引、questions、adr
    ├── detailed-design/               # 共享约定、interfaces、key-designs
    ├── implementation-plan/           # 阶段与测试计划
    ├── tasks/                         # 四人任务与 Issue 草案
    ├── test-cases/                    # 测试预期与案例
    ├── reviews/                       # 审查与检查记录
    ├── acceptance/                    # 准入、阶段及部署验收
    ├── changes/                       # 变更记录
    ├── evidence/                      # 精选验证及 AI 纠错证据
    └── 运行与部署说明.md
```

入口：[设计基线索引](docs/design/基线索引.md)、[四人任务](docs/design/tasks/索引.md)、[需求基线](docs/requirements/08-需求基线.md)。

## scripts 命令

在仓库根目录运行，完整参数及依赖见 [scripts 使用说明](scripts/README.md)。

| 命令 | 功能 |
|---|---|
| `python3 scripts/cli.py report --documents design` | 按清单生成四份设计整合文档，检查本地引用 |
| `python3 scripts/cli.py check --documents design` | 只读核对设计生成一致性与本地引用 |
| `python3 scripts/cli.py report --documents requirements` | 同步需求摘录及需求规格说明书 |
| `python3 scripts/cli.py check --documents requirements` | 核对需求生成内容、模型摘要及本地引用 |
| `python3 scripts/cli.py report` | 生成需求与设计文档，默认 `--documents all` |
| `python3 scripts/cli.py render` | 增量渲染模型 PNG，默认 200 DPI |
| `python3 scripts/cli.py render --force --dpi 200` | 重新渲染全部模型并更新摘要 |
| `python3 scripts/cli.py build` | 渲染模型并生成需求与设计文档 |
| `python3 scripts/cli.py check` | 只读核对模型、全部生成文档及本地引用 |

PDF 输出到 `docs-pdf/`，保持文档目录结构：

```bash
python3 scripts/cli.py pdf
python3 scripts/cli.py pdf --only docs/design
python3 scripts/cli.py pdf --check --pdf-link-check on
```

文档工具检查与帮助：

```bash
PYTHONPATH=scripts python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 scripts/cli.py --help
python3 scripts/cli.py pdf --help
```

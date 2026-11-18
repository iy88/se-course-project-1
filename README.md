<!--
Version: 0.1.29
Version-Datetime: 2026-11-19T00:07:25+08:00
-->

# 校园二手交易与物品流转平台

## 后端编译与启停

后端使用 OpenJDK 27、Spring Boot 4.1.2 和 Maven 3.10.1。从仓库根目录进入 `backend/`，使用本机 Maven 或仓库的 `./mvnw`（Windows 使用 `mvnw.cmd`）。本机 Maven 可通过 `~/.m2/settings.xml` 使用已配置的下载镜像。

```bash
cd backend
mvn verify                         # 构建并测试所有模块，生成可执行 JAR
mvn -pl backend-app -am test         # 只测试启动模块及其 Maven 依赖模块
java -jar backend-app/target/backend-app-0.0.1-SNAPSHOT.jar --server.address=127.0.0.1
```

应用默认监听本机 8080，可加 `--server.port=8081` 调整。另开一个终端检查 `curl -fsS http://127.0.0.1:8080/api/v1/hello` 和 `curl -fsS http://127.0.0.1:8080/actuator/health`。服务在前台运行，在启动终端按 `Ctrl+C` 停止。默认模式只运行 Hello World 和健康端点。

## S1 开发环境与依赖探针

从 `backend/` 复制配置样例，然后在本地编辑。Git 已忽略 `.env.dev`。文件使用 Java properties 语法，值直接写在等号后，避免加引号，反斜杠写成两个反斜杠。

```bash
cd backend
(umask 077 && cp -n .env.example .env.dev)
chmod 600 .env.dev
```

| 资源 | 配置与权限 |
| --- | --- |
| PostgreSQL | 由数据库管理员创建专用开发登录角色和空库，让该角色拥有此库，Flyway 需要在目标 schema 内创建表。可用 `createuser --pwprompt project1_dev` 和 `createdb --owner=project1_dev project1_dev`。填写 `DATABASE_URL=jdbc:postgresql://主机:5432/project1_dev`、`DATABASE_USERNAME` 和 `DATABASE_PASSWORD`。 |
| Redis | 设置 `REDIS_URL` 和独立的 `REDIS_NAMESPACE`，例如 `project1:dev:iy88`。ACL 用户连接串示例为 `rediss://project1_dev:URL编码后的密码@主机:6380/0`，无 TLS 的本地实例用 `redis://`。ACL 将键限制到 `~project1:dev:iy88:*`。探针使用 `GET`、`SET`、`DEL`，Spring Boot 的健康检查还需要 `INFO`。下方有单机 Redis 的 ACL 示例。 |
| OSS | 使用独立开发 Bucket，设置为私有，保持版本控制从未开启。开发 RAM 用户绑定下方的自定义策略。填写 `OSS_REGION`（如 `cn-hangzhou`）、对应 HTTPS `OSS_ENDPOINT`、`OSS_BUCKET`、`OSS_PREFIX` 和该 RAM 用户的 AccessKey。 |
| SMTP | 填写服务商提供的 `SMTP_HOST` 和 `SMTP_PORT`，`SMTP_TLS_MODE=starttls` 用于要求 STARTTLS 的端口（常见 587），`ssl` 用于隐式 TLS（常见 465）。`SMTP_USERNAME` 填发送账号，`SMTP_PASSWORD` 填服务商的 SMTP 授权码，`SMTP_FROM` 填该账号获授权的发件地址，`SMTP_PROBE_TO` 填你要检查的测试收件箱。 |

### OSS Bucket ACL、RAM 和 CORS

在 OSS 控制台将 Bucket ACL 设为 **私有**，启用阻止公共访问，版本控制保持从未启用。以下策略用于独立的开发 RAM 用户。把 `YOUR-DEV-BUCKET` 换为你的 Bucket 名，路径 `project1/dev` 换为 `OSS_PREFIX` 的值。第一项授权在 Bucket 上读取 ACL 和版本控制状态，第二项只允许对探针前缀做实际对象读写。ARN 中的账号字段可填写 Bucket 所有者的阿里云账号 ID。

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:GetBucketAcl", "oss:GetBucketVersioning"],
      "Resource": ["acs:oss:*:*:YOUR-DEV-BUCKET"]
    },
    {
      "Effect": "Allow",
      "Action": ["oss:PutObject", "oss:GetObject", "oss:DeleteObject"],
      "Resource": ["acs:oss:*:*:YOUR-DEV-BUCKET/project1/dev/probe/*"]
    }
  ]
}
```

探针直接由后端调用 OSS。浏览器直传接入时，再像 legacy 一样登记实际用户端和管理端 Origin（包含协议和端口）。v2 的签名表单用 `POST`，浏览器直读确实需要时再添加 `GET` 或 `HEAD`。允许头按浏览器实际预检填写，可暴露 `ETag`、`x-oss-request-id`。v2 的禁止覆盖和 ACL 约束由签名表单字段承载。后续维护工具若需列举对象，`oss:ListObjects` 使用 Bucket ARN，配合 `oss:Prefix` 限制到约定的前缀。[阿里云 OSS RAM 目录级授权](https://www.alibabacloud.com/help/en/oss/user-guide/access-control-base-on-ram-policy)

### Redis ACL

由管理员在 Redis 交互式客户端执行下例，将密码占位值和键前缀替换为开发环境的值。Redis URL 使用该用户，键模式中的前缀须与 `REDIS_NAMESPACE` 一致。示例适用于 Redis 7.2 及以上版本，使用 Redis 7.0 或 6 时去掉 `+client|setinfo`。托管服务可在控制台应用同等的 ACL。

```text
ACL SETUSER project1_dev reset on >替换为随机密码 ~project1:dev:iy88:* -@all +ping +info +get +set +del +hello +select +client|setinfo +client|setname
```

### 运行方式

从 `backend/` 运行，`APP_ENV_FILE` 支持绝对路径。常驻开发服务使用 `infrastructure` profile，按前面的方式检查 HTTP 接口并用 `Ctrl+C` 停止。

```bash
APP_ENV_FILE="$PWD/.env.dev" java -jar backend-app/target/backend-app-0.0.1-SNAPSHOT.jar \
  --spring.profiles.active=infrastructure --server.address=127.0.0.1
```

一次性探针先检查 PostgreSQL 和 Redis，再核对 OSS Bucket 和探针对象的写入、读回、删除，最后向测试收件箱发送一封邮件。进程完成后退出，失败返回非零状态。SMTP 日志显示服务器接收结果和邮件 ID，在收件箱查找同 ID 的 `[Project1 S1] SMTP probe` 邮件以验证投递。

```bash
APP_ENV_FILE="$PWD/.env.dev" java -jar backend-app/target/backend-app-0.0.1-SNAPSHOT.jar \
  --spring.profiles.active=dependency-probe
```

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

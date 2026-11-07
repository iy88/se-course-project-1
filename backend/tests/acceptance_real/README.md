<!--
Version: 0.2.2
Version-Datetime: 2026-11-08T00:28:40+08:00
-->

# 真实业务验收

本套件使用真实 HTTP/WS，按 `backend/.env.dev` 中的显式配置选择数据库、对象存储和 KV 后端；基础环境仅允许 `dev` 或 `test`，不读取生产配置，并拒绝继承的连接及密钥覆盖。数据库连接身份和迁移目标必须与配置一致。运行期间为隔离 schema 和子进程生成权限为 0600 的临时 dotenv，清理时删除。不同后端使用同一命令。

```bash
cd backend
RUN_REAL_ACCEPTANCE=1 .venv/bin/python -m pytest -q
```

本机HTTP客户端禁用环境代理，WebSocket连接显式`proxy=None`；OSS SDK的Session也禁用环境代理和netrc覆盖。

默认端口 8101；可设置 `ACCEPTANCE_PORT`。测试启动和停止自己的服务，不复用日常服务，端口已占用时拒绝启动。pytest 通过 `RUN_REAL_ACCEPTANCE=1` 启用 HTTP/WS 验收，日常运行时跳过该入口。CLI 等价入口是 `.venv/bin/python -m tests.acceptance_real.runner`；`--port` 可指定独立端口。

每轮使用随机隔离 schema 或临时 SQLite 文件、独立存储前缀或目录以及 Redis 前缀。PostgreSQL 使用测试迁移角色应用真实 Alembic 迁移。运行前后只读比较共享 app schema 的表清单和指定表计数；该哨兵不是全部数据的逐行校验。结束或异常时先停本轮服务，再清理本轮资源；清理失败时非零退出并保留私有 ownership 清单和必要的对象写前日志。`SIGKILL`、网络长期不可用等情况下自动清理不能保证，服务停止后可对保留清单执行：

```bash
.venv/bin/python -m tests.acceptance_real.runner --recover /绝对路径/ownership.json
```

恢复只接受本轮受控目录、随机名称、原测试目标及匹配的 schema 所有权标记；若原服务仍可能运行则拒绝。OSS 清理由写前日志逐项删除并 HEAD 验证；日志写入失败时拒绝上传。若凭据不允许列桶，清理结果会说明无法列举前缀，逐项验证不得表述为前缀列举为空。

一次性身份 seed 的独立入口如下，它在隔离数据库创建并校验 8 个身份后立即清理，包括凭据文件；自动套件直接调用相同 helper，不需要先运行此命令：

```bash
.venv/bin/python -m tests.acceptance_real.seed
```

浏览器人工测试需要持久账号，应按部署初始化命令创建管理员并通过应用注册用户，不能依赖一次性 seed。失败日志中的请求摘要会过滤密码、连接串、JWT、AK 和签名 URL。

验收直接执行账户、分类、文件与商品、交易、治理、即时消息和通知等业务检查，使用 HTTP 响应、WebSocket 事件、数据库状态和捕获邮件进行断言。OpenAPI JSON 用于识别请求路由。执行所需输入来自环境配置和结构化运行数据。

全部已执行检查通过且本轮资源清理成功时，命令返回 0；检查失败、跳过、未执行任何检查或清理失败时返回非零。终端输出检查计数和清理结果，失败诊断保存在 `var/acceptance-real/acceptance-failure-<run_id>.log`，包含未通过检查、请求摘要和清理信息。

## 验证码邮件隔离

普通启动固定使用SMTP并须填妥SMTP参数，缺项、空白或占位符会终止启动；接口不返回验证码。验收命令仍仅读取.env.dev，允许基准文件保留SMTP占位符，但仅在创建本轮沙箱前跳过SMTP专属校验。runner仅在私有子进程配置写入本轮邮箱路径，由该内部路径选择capture，验证码仅写入本轮0700目录内的0600私有mailbox.jsonl，测试按用途和收件人读取；SMTP账号和密码不传入子进程。capture只能在匹配随机schema的私有验收目录生效，不能用作普通服务配置。收尾及异常路径删除捕获文件，无需真实收信。

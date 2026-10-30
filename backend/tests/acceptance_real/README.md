<!--
Version: 0.2.0
Version-Datetime: 2026-10-30T14:05:00+08:00
-->

# 唯一全量真实验收套件

本套件使用真实 HTTP/WS，按 `backend/.env.dev` 中的显式配置选择数据库、对象存储和 KV 后端；基础环境仅允许 `dev` 或 `test`，不读取生产配置，并拒绝继承的连接及密钥覆盖。数据库连接身份和迁移目标必须与配置一致。运行期间为隔离 schema 和子进程生成权限为 0600 的临时 dotenv，清理时删除。不同后端使用同一命令。

```bash
cd backend
RUN_REAL_ACCEPTANCE=1 .venv/bin/python -m pytest -q
```

本机HTTP客户端禁用环境代理，WebSocket连接显式`proxy=None`；OSS SDK的Session也禁用环境代理和netrc覆盖。测试不依赖终端是否开启代理，无效WS token校验保留真实连接异常用于诊断。

默认端口 8101；可设置 `ACCEPTANCE_PORT`。测试启动和停止自己的服务，不复用日常服务，端口已占用时拒绝启动。未设置 `RUN_REAL_ACCEPTANCE=1` 时唯一测试明确失败。CLI 等价入口是 `.venv/bin/python -m tests.acceptance_real.runner`；`--port` 可指定独立端口。

每轮使用随机隔离 schema 或临时 SQLite 文件、独立存储前缀或目录以及 Redis 前缀。PostgreSQL 使用测试迁移角色应用真实 Alembic 迁移。运行前后只读比较共享 app schema 的表清单和指定表计数；该哨兵不是全部数据的逐行校验。结束或异常时先停本轮服务，再清理本轮资源；清理失败时非零退出并保留私有 ownership 清单和必要的对象写前日志。`SIGKILL`、网络长期不可用等情况下自动清理不能保证，服务停止后可对保留清单执行：

```bash
.venv/bin/python -m tests.acceptance_real.runner --recover /绝对路径/ownership.json
```

恢复只接受本轮受控目录、随机名称、原测试目标及匹配的 schema 所有权标记；若原服务仍可能运行则拒绝。OSS 清理由写前日志逐项删除并 HEAD 验证；日志写入失败时拒绝上传。若凭据不允许列桶，报告会明确说明无法列举前缀，逐项验证不得表述为前缀列举为空。

一次性身份 seed 的独立入口如下，它在隔离数据库创建并校验 8 个身份后立即清理，包括凭据文件；自动套件直接调用相同 helper，不需要先运行此命令：

```bash
.venv/bin/python -m tests.acceptance_real.seed
```

浏览器人工测试需要持久账号，应按部署初始化命令创建管理员并通过应用注册用户，不能依赖一次性 seed。自动报告不记录密码、连接串、JWT、AK 或签名 URL。

清单来自 US、UC、SC 源文档，映射 51 项检查、105 AC、109 SC、14 主用例与 66 子用例；浏览器人工通道 6 项单独标注，不以 API 测试替代。离线检查和导出命令：

```bash
.venv/bin/python -m tests.acceptance_real.catalog --check
.venv/bin/python -m tests.acceptance_real.catalog --output tests/acceptance_real/coverage.json
```

## 应用代码覆盖率

同一pytest/CLI入口默认采集代码行与分支覆盖率，无需增加`--cov`参数。coverage.py分别追踪验收驱动与真实API子进程，服务停止、隔离资源清理后合并数据；配置启用thread/greenlet，以追踪SQLAlchemy异步调用跨greenlet切换的执行。采集范围为完整`backend/app`，包括未执行文件；测试驱动源码、第三方库、Alembic脚本和前端不计入分母。不同配置的每次运行独立出报告，不自动混合历史数据。

验收JSON/Markdown报告的`code_coverage`包含行/分支计数、独立百分比和产物路径；HTML逐行报告、JSON、Cobertura XML、文本表及原始进程数据保存在`var/acceptance-real/code-coverage/<本轮随机标识>/`。输出目录独立于待删除的测试资源目录，因此资源回滚后仍可查看报告。coverage工具的综合百分比同时计入行和分支，与单独行覆盖率不同。

真实API子进程必须提供有效的行/分支数据；采集或报告生成失败会让验收返回非零。业务或清理失败时，已有覆盖率标记`complete_acceptance=false`，不能当作完整验收的结果。当前没有人为设置最低覆盖率门槛，也不通过排除低覆盖文件抬高结果。默认pytest会捕获输出，可在验收报告中查看产物路径，或使用同一CLI入口查看终端摘要。

## 验证码邮件隔离

普通启动固定使用SMTP并须填妥SMTP参数，缺项、空白或占位符会终止启动；接口不返回验证码。验收命令仍仅读取.env.dev，允许基准文件保留SMTP占位符，但仅在创建本轮沙箱前跳过SMTP专属校验。runner仅在私有子进程配置写入本轮邮箱路径，由该内部路径选择capture，验证码仅写入本轮0700目录内的0600私有mailbox.jsonl，测试按用途和收件人读取；SMTP账号和密码不传入子进程。capture只能在匹配随机schema的私有验收目录生效，不能用作普通服务配置。收尾及异常路径删除捕获文件，无需真实收信。

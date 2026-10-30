# DSH headless 开发执行计划

本文是历史执行计划，所列阶段状态、seed 命令和验收数字描述当时的工作与保留策略，不是当前运行指令。尤其旧 P4 的资源保留方式已被本轮自动化按运行隔离并清理的要求取代，相关历史结果不证明新清理策略通过。当前配置、持久化初始化与测试命令见[开发文档](../docs/development/README.md)。


临时开发任务与执行指令，供实现分工和交接参考。当前配置、命令与验收事实以[开发文档](../docs/development/README.md)为准。

## 执行门槛

2026-10-30负责人已要求开始实际实现并并行分发DSH任务。test 资源连接与实现验证已完成：PostgreSQL 18.6；test 库、app/migrator 连接、owner 切换、Alembic 四项迁移（含标签决定原因）、条件索引与审计权限通过；test OSS 双桶小对象 Put/Get/Head/Delete、上传登记与真实 HTTP smoke 通过。生产资源仅确认可连通，本轮禁止读取 `.env.prod`、执行生产迁移或使用生产资源；production 配置由负责人自行维护。实际开发只使用 `.env.dev`；三类应用测试账号由测试seed创建。用户已允许项目代码（包括脚本）发送 DeepSeek API；不因此上传 .env、AK、密码、数据库内容或无关私人材料。

本地检查凭据可由命令在进程内使用，DSH 不得 cat/env/print/model_dump 实际配置或把 HTTP token、签名 URL、数据库 URL 写到工具输出。缺少凭据只报告字段名。不得将秘密拼入命令行参数。配置加载器、测试命令直接读取文件，输出脱敏资源名与检查结果。

## 实施状态（2026-10-30）

| 阶段 | 状态 | 已实际验证 / 未验证 |
|---|---|---|
| P0 配置选择 | 已完成（test） | `.env.dev` 默认、`APP_ENV_FILE` 显式、生产危险配置拒绝；prod 未运行 |
| P1 PostgreSQL/迁移 | 已完成（test） | 四项迁移、条件索引、循环外键、JSONB、owner/app 权限；prod 未迁移 |
| P2 OSS 双桶 | 已完成（test） | test 两桶 Put/Get/Head/Delete、文件 API 与线程池、上传登记/补偿；prod 桶未使用 |
| P3 审计 | 已完成（test） | 同事务成功、独立失败事务、管理员查询、app 无 UPDATE/DELETE/TRUNCATE；生产保留期限未定 |
| P4 测试/冒烟 | 已完成（test） | 离线 pytest、隔离 schema PG 集成、真实 HTTP smoke、103 业务 API／105 AC／109 SC 全量真实验收；生产 smoke 未运行 |
| P5 文档/交接 | 本轮完成 | 开发文档、README、bits 与结果文件已更新；生产部署文档仍需另行确认 |

最终独立验收结果、源码摘要与复现见[整体验收](../docs/development/整体验收.md)。

## 阶段与完成标准

### P0 基线、配置选择和兼容矩阵

阅读当前 HEAD、工作区、现有规则；保留他人修改。以开发文档中的设计和配置模板为输入，不沿用历史“OSS/生产接入不在本期”的过时开发范围。先实现集中设置加载器：固定后端目录解析 APP_ENV_FILE，默认 .env.dev，独立 .env.prod 显式选择，原 .env 的使用仅允许用户明确迁移决定，禁止自动 fallback。同步服务脚本的 start/status/stop 环境标识，拒绝同一 PID/端口混跑环境，不自动创建生产文件。服务命令和迁移/seed/测试共享解析逻辑，禁止 import 时提前载入生产设置。为配置优先级、缺文件、占位秘密、缓存重载和 cwd 无关编写测试。

### P1 PostgreSQL 与版本化迁移

增加 asyncpg 和 Alembic，更新锁文件；SQLite/aiosqlite 保留。生产关闭 lifespan create_all，使用单独迁移命令，支持 owner SET ROLE、app schema、Alembic version table。迁移账号只能在迁移进程读取；不将其 URL 传入服务配置。SQLite 原有增量加列逻辑继续兼容旧开发数据，新迁移不要 drop/rebuild 已有库。

逐个审查条件唯一索引：交易锁单、同买方待接受请求、普通会话、交易分支、活跃分类/别名、当前完成确认。补 postgresql_where，保留 sqlite_where；布尔表达式不能把 is_current = 1 原样用于 PostgreSQL boolean。缺少 PG 条件会形成无条件唯一索引并阻止正常历史记录，必须通过真实 PG 集成测试证明已结束交易后可新建交易，多个历史确认可保留。

审查外键循环（交易 ↔ 当前约定、商品 ↔ 处置事项）、DDL 顺序、命名约束、BIGINT 自增/序列、UTC 时区、JSON→JSONB 的方言变体，以及按约束名/SQLSTATE识别唯一冲突而非只匹配 SQLite 错误文本。不得把所有 IntegrityError 转成同一个409。比较全套 metadata 编译和新库实际迁移结果。

并发回归至少包括两个接受争同商品、同买方重复请求、事项认领、多轮约定和双方完成确认。采用数据库条件更新/行锁/约束保持业务语义；不要默认 SQLite 的串行写行为等于 PostgreSQL 安全。现有SQLite回归必须保持通过。迁移旧 SQLite 数据另行规划，不默认读取或搬迁本地数据库。

### P2 私有 OSS 双桶适配

选择并固定官方 Python SDK 版本，按官方文档核对 region、HTTPS endpoint、AK 加载及错误码；先写 StorageBackend 合约测试。report 前缀路由 evidence，其余已允许前缀路由 media；未知前缀拒绝。保持逻辑 key 及后端 HMAC 访问入口，私有 bucket 不公开、不返回永久直链、不放 AK 到前端。

保留 LocalStorage，测试夹具默认本地；OSS 模式失败不得悄悄写 local。同步 OSS I/O 放在线程池或明确异步适配，设置超时、有限重试和响应流关闭；GET/HEAD/PUT/DELETE 区分不存在、拒绝授权、连接错误。校验真实文件内容与大小，key 防目录穿越；审查上传后的数据库失败补偿、共享对象引用及生产证据禁止自动过期。验收包括两个桶均可上传/读回/exists、错误权限与过期签名拒绝、本次对象可回收；不请求额外 bucket 管理权限。

### P3 审计落库与权限

按[审计设计](../docs/development/资源与审计设计.md)补迁移、事件矩阵和服务接口。成功写操作同事务审计，失败登录独立事务；处理请求ID、匿名主体、系统扫描、结果原因码、敏感字段脱敏。app 对审计表无UPDATE/DELETE/TRUNCATE权限；真实PG角色验收，不只做ORM单元测试。现有交易转移等业务历史继续保留，审计通过对象/事件关联，不复制全部聊天内容。给查询接口加管理员资格、分页与字段限制；保留期限未决定时不实现定时删除。

### P4 测试、冒烟与验收

先跑离线 SQLite、本地对象存储测试及 Ruff/Pyright；再显式运行 test PG 迁移、隔离 schema 集成回归；最后获得资源确认后运行基于真实 HTTP 的 smoke。既有 e2e_runner 默认会读取本地SQLite和操作时间字段，不可未经审查直接用于PG；新 smoke 不用 SQLite 时间修改工具。

smoke 由专用入口加载 .env.dev，阻止环境继承污染并校验目标指纹。显式测试seed先创建专用测试用户，smoke读取本地受限凭据并通过HTTP登录；建商品/媒体上传与读回→管理员认领审核→买方请求→卖方接受→约定提议/变更拒绝保持原有效约定→双方确认→完成/评价；另走举报证据上传、问询/处置及冻结解除。核对test PG业务历史、审计成功/失败事件、test两个桶实际落点。权限拒绝、重复操作与并发不得产生多余记录。通过HTTP清理允许清理的本轮对象，保留不可删除的历史与审计。

输出脱敏 smoke JSON/文本报告至被忽略运行目录：run_id、环境指纹、步骤PASS/FAIL/SKIP、耗时、非敏感对象ID、未清理项目及原因。不能以状态200、测试编号出现或外部模型完成陈述代替语义验收。缺少资源时静态/离线阶段继续，真实集成明确未开展。

### P5 文档与交接

更新开发文档中当前能力、旧技术笔记和根README运行入口，区分仍未实现的真实邮件、多实例广播和备份恢复演练。不要重写需求分析报告或伪造生产验收。保留 SQLite/local 最短启动和测试路径；README说明采用生产配置之前必须显式迁移。未获授权不 commit/push，不操作 main，不建新线程或委派其他智能体。

## 命令接口（已实现）

以下命令已在 test 目标实际执行（生产迁移命令仅保留入口，本轮未执行）：

```bash
# 后端工作目录；真实配置由程序读取，不在命令中展开秘密。
APP_ENV_FILE=.env.dev uv run python -m app.manage migrate
APP_ENV_FILE=.env.dev uv run python -m app.manage seed-test-users
APP_ENV_FILE=.env.dev uv run python -m app.manage serve --host 127.0.0.1 --port 8000
APP_ENV_FILE=.env.dev SMOKE_ENABLED=true \
  uv run python -m app.manage smoke --allow-test-writes
# 可选：--base-url 默认 http://127.0.0.1:8000；--keep-objects 保留本轮全部对象；
# --run-id、--timeout 可覆盖默认。缺少 --allow-test-writes 只做预检并返回 2。
APP_ENV_FILE=.env.dev uv run python -m app.devtools.objects          # 只列出
APP_ENV_FILE=.env.dev uv run python -m app.devtools.objects --delete # 显式清理
# 生产仅由负责人显式触发；smoke/seed 模块拒绝该文件。
APP_ENV_FILE=.env.prod uv run python -m app.manage migrate
```

`stored_objects` 回收默认只列出无引用 staged 对象，显式 `--delete` 才删除；不设证据 TTL、无定时任务，已 committed 或仍被业务表引用的对象一律保留。删除路径与业务 `mark_committed` 对同一登记行加 PostgreSQL 行锁，业务在引用事务内发现 `deleted` 会失败回滚；证据对象默认保留（`evidence_protected`），dry-run 不加锁；OSS 删除后数据库提交失败的窗口不能由数据库事务消除，重跑以对象不存在补记。smoke 默认只删除本轮未引用对象，历史附件 retained 并核验 OSS 存在性；审计表缺失/字段不兼容直接 FAIL，不能降级为 SKIP。

`seed-test-users` 只允许 .env.dev 的已确认 test 目标，创建管理员/买方/卖方专用账号；生成随机密码后只保存在被忽略运行目录的0600凭据文件，smoke在本地进程读取并通过HTTP登录，不要求额外SMOKE用户配置。账号按专用标识幂等，拒绝接管其他账号，不静默重置已有用户密码/角色；生产管理员另走显式bootstrap，不执行演示seed。migrate只建立结构，不播种演示账号；smoke不自动创建数据库/bucket/权限。`SMOKE_ENABLED=true` 可作进程级显式 opt-in，不需要重复 SMOKE 数据库/桶/用户/base URL 配置。

## 可交给 DSH 的任务正文

```text
在当前开发分支完成 PostgreSQL + 阿里云 OSS 双桶 + 登录/变更审计接入。
先阅读开发文档目录的资源设计、建库权限、环境协议、本执行计划以及仓库规范。
只在负责人已确认资源且填好 .env.dev 后执行真实资源操作；未满足时只完成离线实现并报告缺项。
保持SQLite+本地对象存储兼容。所有测试只允许.env.dev；禁止加载.env.prod、误用生产连接或扩大RAM权限。
项目代码可发送DeepSeek API，但.env/凭据/令牌/真实数据库及对象内容不能发送模型或输出日志。
按P0—P5顺序执行，阶段检查通过后继续；发现业务决定缺口时仅暂停依赖部分，不改既定业务规则。
先写资源目标校验与防误操作，再实施真实HTTP smoke；不能直接运行旧SQLite专用生命周期时间修改代码。
不得commit/push/切换main/创建新线程或子代理；保留现有修改。开发不新增AI usage，不要求确认负责人、模型、harness及逐文件归属。
给出实际差异、独立复验命令、离线/PG/OSS/HTTP各层结果与未覆盖事项，不输出秘密，不把测试通过写为生产上线。
```

由主助手在确认执行时将此正文传给 `dsh headless -`；不把 .env 内容拼到 prompt。DSH 命令可由主助手将任务正文保存到本地临时文本后执行 `dsh headless - < 任务文本`，也可使用 here-document 传入正文；不要将凭据放进任务文本。主助手复核实际 diff 和命令结果，尤其是条件索引、对象鉴权、审计事务及测试环境隔离，再按授权决定提交。

## 并行任务边界

|任务|负责范围|集成约定|
|---|---|---|
|A 配置与数据库|配置加载、模型方言、Alembic、管理CLI、服务启动|统一依赖锁；注册AuditEvent；迁移权限；连接B/C/D接口|
|B 对象存储|StorageBackend及OSS/local实现、文件API、存储合约测试|配置字段由A提供；report→evidence，其余允许前缀→media|
|C 审计|audit_events模型、事件服务、认证与变更审计、查询与安装函数|提供install_audit供A接入；不修改A的启动或模型注册文件|
|D seed与冒烟|测试用户seed、真实HTTP smoke、资源保护测试|管理CLI延迟调用devtools模块；默认本机8000，CLI可覆盖|

各任务保留已有修改，禁止提交、推送、切main及读取生产配置。主助手核对接口、事务与权限、整合后运行分层复验。任务启动不代表功能已完成。

<!--
Version: 0.1.1
Version-Datetime: 2026-11-07T18:29:39+08:00
-->

# Redis、可靠实时投递与服务分层实施设计

> 本文保留 realtime 初版设计与实施记录。当前启动与发布方式以 [部署说明](部署说明.md) 为准。

关联 [issue #36](https://github.com/iy88/se-course-project-1/issues/36)。单 worker 性能基线由 [PR #35](https://github.com/iy88/se-course-project-1/pull/35) 独立交付；本方案基于其提交 `7d40bcf`，在独立 feat 分支实现。PR #35 squash 合并后，该分支对齐到 `dev@d068333`（与原基线文件树相同）。本文是设计与验收合同，列出的目标行为不表示已经实现或生产验证；实现状态由同目录实施记录说明。

## 已确认的队列选型

用户确认：WS 连接内采用 AnyIO 有界内存流；跨网关采用 Redis Streams 官方客户端；后台采用 Taskiq 0.13.0 及官方 taskiq-redis 1.2.4 的 `RedisStreamBroker`、worker 和 scheduler。PostgreSQL outbox 保留业务原子性与 Redis 故障补偿，任务框架负责通用消费、执行后 ACK、失败重试与排程。手写 dispatcher 常驻循环、自制指数退避和单 `jobs` 角色已不再是最终实现；新的 split 角色为 `api / ws / worker / scheduler`，`jobs` 仅作旧 3 角色 release 的过渡/回退边界。

## 1. 输入、范围与部署约束

源码核查：WS 连接表在进程内；消息及通知在调用者提交前直接等待 socket 发送；鉴权完成已经立即关闭 SQL 会话；每个应用 lifespan 启动超时扫描。RedisKV 未覆盖基类 get/set 计数，因此频控自增不是跨进程原子操作。SQLAlchemy 引擎和 Uvicorn 启动尚无显式池/worker 参数。交易、上传确认、发布已有行锁、唯一约束与审计，优化不能削弱。

负责人提供的部署交接文档记录的是 2026-10-31 构建 #19 后状态，作为环境输入而非指令：Gitea main push 触发 Jenkins；按 release 打包、备份、迁移、切换 current；生产后端 systemd 单服务、本机 API 8001；Nginx 的 /api 与 /ws 共用 upstream；PostgreSQL 18、本机 Redis 独立实例；Redis 当时无认证、无 AOF。shared dotenv 复制到每个 release，重启不会自动刷新副本。系统服务、Nginx、sudoers、备份与保留脚本由管理员安装，Git 发布不会自动更新它们。当前仓库 Jenkinsfile 仍只重启和校验一个后端服务，CI 功能验收使用 SQLite/local。交接中的分支、版本、代理 IP 判断可能滞后，不能代替现场核查。

本次修改项目代码、示例配置、测试、仓库内部署资产、CI 与开发文档。禁止访问/修改生产、推送 Gitea main、自动 merge、修改真实 dotenv、清理既有测试库/Redis/OSS。DeepSeek 可接收项目源码；真实凭据、私有 manifest、生产数据与原始私有日志不发送、不提交。管理员操作和生产性能验证作为明确的发布步骤留给负责人。

## 2. 运行拓扑与兼容边界

同代码库提供 `combined`、`api`、`ws`、`worker`、`scheduler` 五种运行角色（`jobs` 为旧 3 角色 release 的过渡入口）。combined 用 `manage serve`，保持单 worker 开发/旧发布入口；split 的 API、WS 使用 `serve-api`/`serve-ws`，worker 与 scheduler 使用 `taskiq-worker`/`taskiq-scheduler`（内部调用官方 Taskiq CLI 参数，参数全部从 dotenv 构建）。combined 以进程内官方 `Receiver`/`SchedulerLoop` + InMemoryBroker 运行任务；`jobs` 以同一框架 Receiver/SchedulerLoop + 真实 Redis broker 运行；api 不启动任务；ws 不装载业务写路由；worker 只消费任务；scheduler 只排程并通过 Redis 心跳。所有角色在本进程事件循环创建并关闭自己的 engine、Redis 池、broker 和任务，不能跨 fork/loop 复用连接。

生产 split 拓扑：Nginx `/api` → API:8001，`/ws` → WS:8002；Taskiq worker 与单实例 scheduler 为独立 systemd 服务。四个角色共用相同 release、协议版本和选定 dotenv。先同机部署，后续按测量独立迁移。API/WS 使用 HTTP readiness；worker 的受控 CLI readiness 要求本 release 的 SQL 心跳 + 最近实际任务成功，并额外入队一个真实 probe 任务等待执行；scheduler 的 CLI readiness 要求本 release 的 Redis 心跳持续推进且最近成功派发过任务。不能用 PID、独立心跳或 HTTP 200 冒充任务消费成功；worker 缺席时 readiness 必须失败。

既有 HTTP 业务写入保留。移动端升级 WS 协议，但保持原 message/notification 业务回调字段，避免 Chat 展示回归；Rust 驱动同步支持 ticket、事件 ACK 与新连接握手。兼容 query JWT 只作可配置过渡，默认生产关闭；敏感 query 在应用及代理日志中脱敏。旧前端、旧后端和新协议的兼容矩阵必须写入实施记录，不能让新前端遇到旧后端后无限重连。

## 3. 持久事件与事务语义

业务消息、通知、审计与 durable realtime event/outbox 在同一 PostgreSQL 事务内写入。事务提交前不调用 Redis 或 socket；回滚不产生事件。事件包括 event_id、recipient_user_id、user_seq、type、entity_id/version、必要且有大小上限的 payload、created_at；投递状态、lease owner/expiry、attempts、next_retry_at 可同表或独立 outbox 表，但不得丢失 durable inbox。索引覆盖 pending claim、recipient+seq 唯一和保留清理。角色权限按现有 migrator/owner/app 约定显式授予，不能给审计表补授 UPDATE/DELETE。

每用户使用独立 counter 行分配连续提交游标；所有接收者按稳定 ID 顺序取得 counter 锁，并在同一业务事务最终阶段一次生成事件，避免与商品→交易的既有锁顺序倒置。counter 不能复用 User 业务行，也不能用全局自增 Message.id 当提交游标。counter 初始化并发、回滚、重试必须测试。客户端保留最后连续成功处理序号，事件可能因并行 dispatcher 乱序，不能把 Redis ID 或 outbox 扫描顺序当业务顺序。

outbox 由有限的 domain service（`OutboxService.dispatch_batch`/`run_bounded`）执行短事务 claim + 可回收 lease（PostgreSQL SKIP LOCKED），释放 SQL 连接后才做 Redis I/O，再用短事务条件确认。Taskiq 的 interval schedule 周期调用该批处理；每次运行有 batch 数与时间预算，避免任务风暴。失败只释放 lease 并记录稳定错误类别，由官方 `SmartRetryMiddleware` 按重试次数、指数退避、上限和 jitter 重新排程；`next_retry_at` 保留为兼容/人工恢复字段，claim 不再读取，避免 DB 退避和框架重试双重叠加。达到 `OUTBOX_MAX_ATTEMPTS` 后写 `dead_at` 终止重试并计入 readiness/degraded；人工恢复使用 `app.manage realtime-retry`，不清除未投递事件。发布成功后确认前崩溃会重复投递，合同为至少一次加幂等，不声称 exactly-once。lease 到期允许其他 worker 接管；同一事件重复不影响 UI。超时扫描使用共享 Redis lease，DB 状态锁仍是正确性底线，禁止只依赖 Redis 锁做抢单。

发消息/发布等 POST 的传输异常存在“已提交但响应丢失”歧义。提供兼容的幂等键：同用户、同操作、同键、同请求摘要复用结果；相同键不同摘要拒绝；键+业务结果同事务保存。并发同键只产生一份业务记录/审核/审计；默认未传键的旧行为保留。OSS 上传与 DB 仍无分布式事务，staged 回收继续保留。

## 4. Redis layer

### 4.1 职责与键空间

Redis 保存验证码/频控等短时共享状态、一次性 WS ticket、在线连接短时统计和实时分发 stream。业务、权限、交易状态、未读/已读与重放事件以 PostgreSQL 为准。第一阶段不缓存交易资格、权限或带个人态的商品详情；公开分类/列表如优化需另测命中率并设计提交后失效，不能缓存签名 URL 或跨用户复用响应。

键全部位于所选环境 REDIS_KEY_PREFIX 下，分别使用 kv:、ratelimit:、ws:ticket:、realtime:v1:、jobs: 子域；兼容既有验证码键，不做全实例清理。持久事件不以 Redis TTL 为唯一保留依据。production 或多 worker/split 模式必须配置共享 Redis；缺失时启动失败，禁止悄悄退回各进程 MemoryKV。开发单进程的 memory 仅覆盖离线/功能测试，不代表跨实例可靠性通过。

### 4.2 原子性、池与连接预算

RedisKV 覆盖 incr_with_ttl，Lua 原子 INCR + 首次 EXPIRE，实现固定窗口，后续命中不延长 TTL；GET 后 SET 不合格。一次性 ticket 用 GETDEL 或等价 Lua 原子消费，多个网关并发只有一个成功。分布式 lease 需比较 owner token 释放，不能裸 DEL 删掉他人 lease。Redis 时间窗口、连接数和脚本错误有受控失败与测试。

各进程显式设置最大连接、获取等待、连接/读取超时及重试边界。阻塞 XREAD 使用独立连接/池，不能耗尽验证码和 ticket 的控制池；XREAD 的 BLOCK 与 socket_timeout 相容，关闭能够及时取消。非幂等控制操作不能盲目自动重试。监控 pool wait/exhaustion、命令延迟、重连、错误和 stream lag。全部角色池上限之和（含新旧版本并存）不超过 Redis maxclients 与 FD/内存预算。

### 4.3 跨网关分发与故障补偿

初期一个有界 stream，dispatcher XADD，所有 WS gateway 各自独立 XREAD cursor，然后按本地用户连接过滤。禁止全部 gateway 共用一个分摊消息的 consumer group，否则事件可能只交给没有接收者连接的 gateway。gateway 数量增多后再做用户分片；记录广播读取放大。

stream 是短时加速通道，MAXLEN 与 payload 字节上限共同限制规模；初始 50,000 条仅为测量起点，不承诺固定小时数。PostgreSQL 事件保留默认 72 小时，同时保留 counter 高水位与已清理低水位；清理不得删掉尚未安全投递/仍持 lease 的事件。重放分页限额与客户端限流必须存在，防止重连风暴打满数据库。

Redis 故障、重启丢 stream、trim 超过读取位置、事件最后一条丢失（后面没有新事件暴露 gap）均通过 PostgreSQL 水位核对和受控周期补拉修复；不能只等下一个事件发现缺口。Redis 不可用时 API 可提交到 outbox 并报告实时降级；ticket/频控等安全相关操作 fail closed。积压年龄/数量/磁盘超过预算时有明确准入策略与告警，不能无限接受且声称实时达标。恢复期间限制补投与补拉速率，保留新事件公平性。

### 4.4 生产 Redis 前置条件

交接记录的无认证、无 AOF 不应原样作为新方案的生产基线。管理员核实监听/防火墙、独立 ACL 用户与最小键/命令权限、认证和 secret 管理；跨主机使用 TLS 或受保护链路。建议为实时/控制使用独立实例或至少专用 ACL/资源预算，逻辑 DB/前缀不提供内存和驱逐隔离。安全状态与 stream 不应受普通缓存 LRU 驱逐，采用预算明确的 noeviction 并处理 OOM；配置 maxmemory、预留 fork/AOF 内存，启用 AOF everysec 并做重启恢复演练。AOF 仍不能代替 outbox，已提交业务由 PostgreSQL 恢复。现有 Redis 全实例备份可能包含其他项目，不能自动 restore 全实例。

## 5. WS 协议、背压与安全

客户端通过认证 HTTP POST 获取 30 秒一次性 ticket，再 WSS 连接；ticket 只含服务端引用、不含长期 JWT，消费绑定用户、授权有效期与必要 audience，校验 Origin。浏览器跨站请求不能仅靠 query token 被接受；非浏览器无 Origin 的可信压测策略明确配置。密码/退出仍是现行 JWT 语义，若新增全端撤销需要独立持久 auth version 与测试，不能谎称旧 JWT 已可撤销。

服务端注册连接并开始缓冲，再取得持久高水位 H，完成客户端游标到 H 的补拉，再按 user_seq 排序交付缓冲事件。每条 event 可重复，客户端仅在业务应用成功后推进连续游标并 ACK；ACK 是设备投递进度，不修改已读。游标按用户隔离且退出清除，禁止不同账户继承。落后于清理低水位发 resync_required，客户端重新获取授权业务快照，按水位衔接增量；不能直接跳到最新导致静默遗漏。

每连接一个 AnyIO `create_memory_object_stream` 有界流和一个 writer，所有业务事件、pong、控制帧统一经该 writer 发送。容量按 `WS_EFFECTIVE_QUEUE_CAPACITY = max(1, min(WS_QUEUE_MAX_MESSAGES, WS_QUEUE_MAX_BYTES // WS_MAX_FRAME_BYTES))` 保守推导：每个合法帧不超过 `WS_MAX_FRAME_BYTES`，因此槽位数乘帧上限不超过字节预算，不需要手写加权字节队列；writer 另可能持有一个已出队 inflight 帧，作为 +1 帧余量记录。启动拒绝 `WS_QUEUE_MAX_BYTES < WS_MAX_FRAME_BYTES`。实时 fanout 用 `send_nowait`，满则立即以 1013 关闭该连接，不等待、不拖累其他用户；历史/补拉用有界 `await send` 并受 `WS_SEND_TIMEOUT_SECONDS` 限制。关闭时关闭流的收发端即可丢弃旧帧并唤醒等待 sender，不塞 sentinel、不手写清队列；WebSocket 只由 writer 关闭。限制单用户连接数、IP 连接/握手速率、帧大小、入站消息类型和速率；跨 gateway 限额使用 Redis 原子计数与 TTL/lease。已有封禁用户只读接收规则保留。

心跳初始 20 秒、失联 60 秒、send timeout 5 秒；有 jitter 的 0.5–30 秒重连。保持代理链各跳 WS Upgrade 和超时兼容，现有 300 秒代理超时不必为方案无故缩短。排空先停止接新连接/标记不就绪，再通知并关闭旧连接；graceful timeout 小于 systemd TimeoutStopSec。连接和订阅数、queue bytes、慢客户端关闭、重放/去重/gap、投递与 ACK 延迟可观测，日志不含 JWT、ticket、签名 URL 或消息正文。

## 6. 数据库与 Web 并行优化计划

共同入口先做 request ID 与耗时分解：pool checkout wait/hold、SQL 次数及耗时、事务时长、外部 I/O、CPU、事件循环延迟、outbox 年龄、commit→gateway→ACK。指标不得带 SQL 参数、连接串、token 或用户文本；request ID 继续关联审计。

数据库线：先按测量缩短持锁/持连接时间，把 OSS 等网络操作尽可能移出业务锁事务并在提交前复核；不在同一 AsyncSession 上并行 execute。列表/搜索用投影/批量加载，确认 SQL 数量后再说 N+1；保留 response schema 和签名读取权限。通过真实 PG EXPLAIN(ANALYZE,BUFFERS) 决定索引，substring ILIKE 评估 trigram，不因猜测加入索引。保持商品→交易及 StoredObject 排序锁，补幂等请求，避免全局 Redis 锁替代 SQL 事务。

Web 线：API worker 做 1/2/4 对照；WS 和 jobs 各自独立扩容；测量序列化、ORM 对象和签名/散列 CPU。先固定总 SQL 连接预算比较 worker，再固定 worker 扫 pool 4/8/12；同机 API/WS 与独立进程对照保持总资源预算相同。不使用 CPU*2+1 公式，也不因开发机有 18 逻辑 CPU 直接开 18 个 worker。SQL CPU/IO、Redis 延迟、发压机与反向代理都要同时监控。

## 7. dotenv 配置合同与预算

仍只从 APP_ENV_FILE 选定文件加载，继承的 WEB_CONCURRENCY、UVICORN_*、DATABASE_URL 不覆盖业务配置。以下是起始候选；combined 默认保持一个 worker；split 参数须显式启用并验证，不暗中改变基线。示例只含占位 secrets，真实文件不修改。生产池参数修改需按角色重启，不承诺热更新。

| 配置族 | 初始候选 / 约束 |
|---|---|
| API_WORKERS / WS_WORKERS | 4 / 2；结合生产 CPU 配额与连接预算测量 |
| API_HOST/API_PORT、WS_HOST/WS_PORT | loopback / 8001、loopback / 8002；端口不冲突 |
| API_DB_POOL_SIZE/MAX_OVERFLOW | 8 / 0，每个 API 进程 |
| WS_DB_POOL_SIZE/MAX_OVERFLOW | 2 / 0，每个 WS 进程 |
| JOBS_DB_POOL_SIZE/MAX_OVERFLOW | 4 / 0，每个 worker 进程一个 engine；scheduler 为 0 |
| TASKIQ_WORKER_PROCESSES / MAX_ASYNC_TASKS / MAX_PREFETCH | 2 / 16 / 8；SQL 预算按 worker 进程数乘 jobs 池 |
| TASKIQ_BROKER_MAX_CONNECTIONS / SCHEDULE_MAX_CONNECTIONS / HEARTBEAT_MAX_CONNECTIONS | 4 / 2 / 1；每个 worker 进程独立池，scheduler 不建 SQL 池 |
| TASKIQ_RETRY_MAX_RETRIES / DELAY / MAX_DELAY / JITTER | 3 / 2s / 60s / true；官方 SmartRetryMiddleware |
| TASKIQ_OUTBOX_INTERVAL_SECONDS / TASK_TIMEOUT / RECLAIM_IDLE_MS | 1 / 60 / 300000；批处理与 reclaim |
| OUTBOX_MAX_ATTEMPTS / MAX_BATCHES_PER_RUN / RUN_TIME_BUDGET_SECONDS | 8 / 5 / 10；终态 `dead_at` 与人工恢复 |
| DB_POOL_TIMEOUT_SECONDS / PRE_PING / RECYCLE_SECONDS | 1 / true / 1800；有限正值 |
| DB_LOCK_TIMEOUT_MS / STATEMENT_TIMEOUT_MS / IDLE_IN_TRANSACTION_TIMEOUT_MS | 500 / 2000 / 10000，在线连接局部设置，迁移/seed 单独预算 |
| REDIS_CONTROL_MAX_CONNECTIONS | API 16、WS 8、jobs/worker 8；scheduler 健康控制池固定 1（redis-py 的 0 表示无界，禁止） |
| REDIS_STREAM_MAX_CONNECTIONS | 每 WS 进程 1 个专用阻塞 reader；dispatcher 普通池 |
| REDIS_CONNECT_TIMEOUT_SECONDS / SOCKET_TIMEOUT_SECONDS | 1 / 2；阻塞 reader 单独设定并大于 BLOCK |
| REDIS_CONTROL_POOL_TIMEOUT_SECONDS / PUBLISH_POOL_TIMEOUT / READER_POOL_TIMEOUT | 1 / 1 / 1；有界获取，超时 fail closed |
| REDIS_PUBLISH_MAX_CONNECTIONS | 2；dispatcher 发布池，与控制/reader 分开计数 |
| REALTIME_STREAM_MAXLEN / PAYLOAD_MAX_BYTES | 50000 / 16384（payload 应优先小于此上限） |
| REALTIME_EVENT_RETENTION_HOURS / REPLAY_BATCH_SIZE | 72 / 200；pending 保留与过期重同步有边界 |
| OUTBOX_BATCH_SIZE / POLL_INTERVAL_MS / LEASE_SECONDS | 100 / 50 / 30；支持失败退避和过期接管 |
| REALTIME_OUTBOX_MAX_PENDING / MAX_AGE_SECONDS / ADMISSION_CACHE_SECONDS | 20000 / 3600 / 1；软准入阈值+短缓存；0 缓存表示每次 COUNT |
| WS_TICKET_TTL_SECONDS / ALLOW_QUERY_TOKEN / ALLOWED_ORIGINS | 30 / prod false / 显式站点白名单 |
| WS_HEARTBEAT_SECONDS / HEARTBEAT_TIMEOUT_SECONDS / SEND_TIMEOUT_SECONDS | 20 / 60 / 5 |
| WS_QUEUE_MAX_MESSAGES / MAX_BYTES / MAX_FRAME_BYTES | 128 / 524288 / 32768（须大于 payload+envelope） |
| WS_MAX_CONNECTIONS_PER_USER / RECONCILE_SECONDS | 5 / 1（最终按负载预算验证） |
| GRACEFUL_SHUTDOWN_SECONDS | 20；systemd Stop 超时留余量 |

稳态 SQL 业务上限示例：4×8（API）+ 2×2（WS）+ 2×4（两个 worker 进程）= 44，scheduler 为 0；再加 monitor/migration/admin。全角色新旧并存时须预留发布重叠。必须小于服务器为本项目分配的连接预算，保留 PostgreSQL 系统/管理/其他应用资源，不能假设 max_connections=100。Redis 示例：API 4×16=64，WS 2×(8+1)=18，worker 2×(8+2+4+2+16)=64，scheduler 4+2+1+1=8，总计 154；再预留运维与发布重叠。queue slot 数 × 最大帧 × 最大连接数必须计入 WS 内存，不把 512KiB 当无成本默认。多条 SQL 各 2 秒不代表总请求 3 秒，整体 deadline、取消与幂等结果查询需独立验证。

## 8. CI/CD 与管理员一次性升级

### 8.1 CI 门禁

保留现有 SQLite/local 全业务验收和前端构建；新增真实 PostgreSQL + Redis 集成测试，资源必须来自 CI 专用配置/实例，随机 schema 和前缀，不接触 prod，也不拿 SQLite 测试声称行锁正确。门禁覆盖实际迁移及应用角色权限、两个独立 WS 进程和 API 进程、原子 KV、outbox rollback/claim/retry、Redis 故障恢复、重放与交易竞态。资源清理有 finally、明确所有权和失败报告，禁止 FLUSHDB/FLUSHALL。

集成测试入口应可在本地与 Jenkins 共用：支持提供 CI PostgreSQL/Redis 连接和严格测试环境标识，不把生产凭据加入 Jenkins。缺失前置条件时发布门禁必须失败并说明，不能 skip 后继续生产发布。在仓库提供管理员设置 CI 临时服务/凭据的说明，不能假定 Jenkins agent 有 docker/root。Rust 单元/Clippy 与必要 WS 客户端兼容测试加入检查；完整 400 强度容量测试独立执行，不在每次发布跑生产压测。

### 8.2 仓库发布改造

release 包继续只打包 tracked backend 和前端，新增仓库部署脚本需纳入归档校验。配置 preflight 验证角色、端口、pool 总预算、Redis 能力、协议和 systemd 模板版本；prepare 仍从 shared 复制配置，以权限 0600 保存。

迁移前备份仍保留，新增表采取 expand-only；迁移在 app/WS/jobs 之外只执行一次。新增 api/ws/worker/scheduler systemd 模板与固定用途的受限激活入口；`jobs` 仅保留为旧 3 角色 release 的回退/过渡 unit。不能给 deploy 任意 systemctl/sudo。health/readiness 包含 release ID、角色与协议版本；API HTTP 通了不能代表 WS/Taskiq 可用。worker/scheduler 没有 HTTP 监听，激活脚本对其调用受控 CLI readiness（worker 会执行真实 task probe）。ACTIVATED 记录 `roles=`、`services=`、`protocol=`、`previous_release=`、`previous_mode=`、`previous_services=`、`previous_protocol=`，回退按记录的原服务集合执行。

首次从单服务转换采用有计划的短维护窗口：管理员事先安装服务/固定用途 sudoers 和 Nginx 模板；校验后成套停止旧 combined 或旧 3 角色 split，切换 current，启动 scheduler→worker→WS→API，分别验证 readiness、真实 ticket→WS→持久事件→ACK 与真实 task probe，再开放流量。旧 scheduler 必须先停，避免新旧 scheduler 同时派发；任一 stop 失败不得假成功。失败时恢复旧 current、按 ACTIVATED 记录恢复旧服务集合与人工恢复代理路由，停止新角色，明确哪些步骤失败。不得在混用新旧协议的窗口让同一请求双推送。后续 split 升级也先采用成套停止/切换/启动的可验证方案，优雅断线重连补拉；没有双端口 upstream 与 release fencing 之前不宣称零停机滚动发布。

激活持有现有 activation lock，检查所有角色实际 cwd/release、jobs 心跳，成套成功才写 ACTIVATED；回退失败保留现场并让 Jenkins 失败。回退仅切代码/服务/路由，不自动回滚 PostgreSQL、Redis 或删 outbox；旧代码可忽略新增表，回退期间新事件可能停止产生，重新升级时要求快照 resync/版本水位边界，不能假定历史游标仍覆盖旧代码产生的所有变化。保留脚本要保护所有仍运行角色的 release（或激活严格保证只有 current 一套运行），避免删掉仍被 WS 使用的目录。

### 8.3 现场操作边界

管理员核实生产实际版本、PostgreSQL 连接预算、Redis ACL/AOF/maxmemory/maxclients、代理链 WS、文件描述符与内存；安装新服务、固定用途 sudoers、Nginx、健康脚本及 CI 专用依赖。安装前预览并备份相关文件，nginx -t/systemd-analyze verify 后才切换。这些是发布前提，本轮只提交可审阅资产和命令说明，不远程安装或触发 Jenkins。

## 9. 测试矩阵与完成条件

1. 事务：回滚无投递；业务/事件/审计原子；并发同幂等键只一份结果；counter 并发无已提交缺口；不改变交易/发布锁与状态约束。
2. 分发：API 与接收 WS 在不同进程；同用户多设备；dispatcher 发布后崩溃重复；lease 过期接管；并行乱序；最后事件丢失无后继也补偿。
3. 连接：慢客户端隔离、消息数/字节队列上限、单 writer、帧/频率/跨进程连接上限、心跳与优雅关闭；长连接不持 SQL 连接。
4. 安全与恢复：ticket 一次消费/过期/Origin、账户切换游标隔离、旧 token 兼容关闭；Redis 重启/断线/丢 stream、trim、PG 不可用、重放超期 resync。
5. 发布：缺 CI 服务失败、迁移角色权限、三角色 readiness/release、成套回退、配置副本语义、旧 combined→split→combined 操作演练（隔离测试或受控 fake systemctl，非生产）。
6. 性能：仍区分 single HTTP RPS 与 mixed 场景/秒，应用 HTTP 与 OSS PUT 独立；1/2/4 API workers、不同池、WS 连接数与重连负载对照，报告 P95/P99、错误、发压完整度、pool wait、SQL、Redis、CPU、event-loop lag、outbox age 和 ACK。普通 P95≤3 秒、IM≤2 秒，400 是探测上限，不是承诺通过。Taskiq 门禁还必须证明：独立 API + 两个 WS gateway + worker + scheduler 进程、真实框架 probe、杀 worker 后 XAUTOCLAIM 接管；重复事件/业务幂等分别验证、重试成功/最终失败可观测、scheduler 重启不重复注册静态 schedule、Redis 重启/连接丢失后 WS 从 PG 补扫。

离线、受控替身、真实 PG/Redis 集成、真实 OSS、生产链路和浏览器验收分别记录。只完成代码/单测不能标为 production-ready；全部适用门禁及现场演练通过后才作生产准入结论。

## 10. 参考依据

- [SQLAlchemy pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)：异步池、连接上限及等待。
- [Redis Pub/Sub](https://redis.io/docs/latest/develop/pubsub/) 与 [Streams](https://redis.io/docs/latest/develop/data-types/stream/)：分发语义、重放与消费方式。
- [Redis XREAD](https://redis.io/docs/latest/commands/xread/)：独立读取游标。
- [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) 与 [ACL](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)：持久化、安全与操作前提。
- [Uvicorn settings](https://uvicorn.dev/settings/)：显式 workers、WS 与资源/停止参数。
- [Taskiq CLI](https://taskiq-python.github.io/guide/cli.html)、[scheduling](https://taskiq-python.github.io/guide/scheduling-tasks.html)、[middlewares](https://taskiq-python.github.io/available-components/middlewares.html) 与 [taskiq-redis](https://github.com/taskiq-python/taskiq-redis)：worker/scheduler、SmartRetry 与 Redis Stream broker/schedule source。
- [AnyIO streams](https://anyio.readthedocs.io/en/stable/streams.html)：有界内存流、send/send_nowait、关闭唤醒与取消语义。
- [OWASP WebSocket security](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html)：Origin、身份、限流与资源约束。
- [现有部署说明](部署说明.md)、[压测基线](load-testing.md)。

## 11. 实现期修正（append-only）

以下为实现证据支持的设计补充，不改变前文业务目标与验收口径；详细记录见[实施记录](realtime-layers-implementation.md)。

1. **角色选择器**：split 四个角色共用一个 release/dotenv，无法在 dotenv 内表达不同角色。实现增加 `APP_RUNTIME_ROLE` 作为进程角色选择器（systemd `Environment=` 或 `serve-*` CLI），业务配置仍只来自 `APP_ENV_FILE` 所选文件；combined 仍是 `serve` 的兼容默认。
2. **保留低水位**：清理后的 `low_seq` 取“仍保留的最小 user_seq”；没有剩余事件时才取 counter 高水位 +1。不能简单用“已删除最大 seq+1”，否则乱序时间戳下可能把仍保留事件判为已清理。
3. **个性化通知事件**：同一次 `notify` 先按接收者排序一次性分配全部 counter，再逐条插入带各自 notification_id 的事件，避免逐个用户加锁造成并发顺序反转。
4. **旧服务身份**：combined 回退沿用既有 `se-course-project1-backend.service`；新 split 使用 api/ws/worker/scheduler unit，旧 3 角色 jobs/ws/api 仍可被识别并成套停止；激活脚本只控制固定服务枚举，不授予任意 systemctl。
5. **健康与降级**：WS readiness 区分“订阅循环不可用”（503）与“Redis stream 降级但 PG 回放可用”（degraded/200）；jobs readiness 读取持久心跳与 outbox 年龄，不以进程存在代替。
6. **客户端兼容边界**：新移动端只走 ticket；旧后端缺端点或协议版本 <2 时停止重连并发出 `protocol_incompatible`，避免无限重连。旧 query token 仅在非 prod 且显式开关时保留。
7. **内存 KV 边界**：MemoryKV 与 Redis 方法语义一致，仅用于离线/单进程开发；production 或任意 split 角色缺共享 Redis 在启动时失败，不存在静默回退。
8. **AnyIO 流容量语义**：`effective_capacity=min(messages, bytes//max_frame)` 以最大合法帧保守覆盖字节预算；writer 另有一个 inflight 帧余量，启动拒绝 bytes<max_frame。实时满队列关闭该连接，历史/补拉等待有超时；库负责唤醒和取消，不保留自写队列内部状态。
9. **Taskiq 任务隔离**：任务 stream/group 与 `realtime:v1:events` 分离；broker 不设 MAXLEN，避免裁剪未 ACK pending；Redis 8.2+ 使用 `XACKDEL ... REF_POLICY ACKED` 仅在全部 consumer group 确认后回收，旧版本在启动时失败并拒绝运行，不回退到弱 ACK 语义。Taskiq ACK 只是任务执行进度，不是设备已读。
10. **重试归属**：Taskiq `SmartRetryMiddleware` + 官方 Redis schedule source 负责延迟重试；outbox claim 不读 `next_retry_at`，周期 sweep 只兜底丢失任务；`dead_at` 为终态，`realtime-retry` 人工恢复。

Taskiq 官方 reclaim 锁使用 `autoclaim:<group>:<stream>` 派生键，ACL 必须额外覆盖仅由本环境 group/stream 构成的精确命名空间；不能只给应用前缀后误判 worker 已就绪，也不应开放全局 `autoclaim:*`。新增 WS reader 的 client name 需要连接命名权限。ACK 回收要求 Redis 8.2+ 的 [XACKDEL ACKED](https://redis.io/docs/latest/commands/xackdel/)，启动直接验证实际权限。

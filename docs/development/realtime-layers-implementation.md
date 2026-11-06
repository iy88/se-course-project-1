<!--
Version: 0.1.0
Version-Datetime: 2026-11-06T22:35:00+08:00
-->

# Redis、可靠实时投递与服务分层实施记录

关联 [issue #36](https://github.com/iy88/se-course-project-1/issues/36) 与[设计合同](realtime-layers-design.md)。本文记录实际实现、命令结果、证据边界和未完成项；设计目标以合同为准，本记录不替代生产验收。

## 1. 实施状态摘要

已在本工作区 `project1-realtime` 的 `feat/36-realtime-layers` 分支完成最终选型的代码、离线测试、真实 PostgreSQL/Redis 集成、前端协议测试/构建、Rust 测试/Clippy、仓库 CI/CD 资产及部署模板；未提交、未 push、未创建 PR/issue、未触发 Jenkins、未 SSH、未访问或修改生产、既有 PostgreSQL/Redis/OSS。真实生产 OSS、SMTP 收件箱、浏览器人工验收、400 混合压测和现场 systemd/Nginx 演练均未执行，不能把本记录当作生产准入。

最终选型：WS 连接内使用 AnyIO `create_memory_object_stream` 有界流；跨 gateway 使用 Redis Streams，各 gateway 独立 XREAD；后台使用 Taskiq 0.13.0 + 官方 taskiq-redis 1.2.4 `RedisStreamBroker`、`SmartRetryMiddleware`、`ListRedisScheduleSource` 与官方 scheduler；PostgreSQL outbox 保留业务原子性和故障补偿。旧的常驻 dispatcher 循环、自制退避和单 `jobs` 最终拓扑已移除/降级为过渡边界。

真实集成在本机隔离临时 PostgreSQL 18.6 与 Redis 8.10.2 上执行；服务进程、schema、角色、Redis 前缀均为本轮新建并在 `finally` 清理，未使用 `FLUSHDB/FLUSHALL`，未读取 `.env.dev/.env.prod`。托管 Redis 模式下测试先停 worker，再执行真实 `SHUTDOWN NOSAVE`；在 Redis 与 worker 都不可用期间提交事件并由 WS 从 PostgreSQL 补扫收到，之后才同端口重启 Redis、重启 worker 并执行真实 probe。external 模式只按本轮随机前缀的 `client_name` 精确断开自己的 WS reader 并删除自己的 stream，不执行 `CLIENT KILL TYPE normal`。

## 2. 运行拓扑与角色

| 角色 | CLI | 监听 | 职责 |
|---|---|---|---|
| combined | `app.manage serve` | API_HOST/PORT | 兼容单进程：HTTP + WS + 进程内官方 Taskiq InMemory Receiver/SchedulerLoop |
| api | `app.manage serve-api` | API_HOST/PORT | 仅业务 HTTP；不启动 WS/任务消费 |
| ws | `app.manage serve-ws` | WS_HOST/PORT | 仅 WS gateway；不装载业务写路由 |
| worker | `app.manage taskiq-worker` | 无 | 官方 Taskiq worker 进程组；outbox 批处理、超时扫描、retention、幂等清理、probe |
| scheduler | `app.manage taskiq-scheduler` | 无 | 单实例官方 Taskiq scheduler；静态 interval/cron + Redis 延迟重试源；Redis 心跳 |
| jobs（过渡） | `app.manage serve-jobs` | JOBS_HOST/PORT | 旧 3 角色 release 回退/本地全任务进程，仍使用官方 Receiver/SchedulerLoop + 真实 Redis broker |

角色由 `APP_RUNTIME_ROLE` 选择（systemd `Environment=` 或 `serve-*` CLI），业务配置仍只来自 `APP_ENV_FILE` 选定的 dotenv。`server`/`worker`/`scheduler` 各自在进程事件循环内创建并关闭 engine、Redis 池、broker 和任务。`combined` 强制一个 worker；`taskiq-worker` 的进程数、每进程 async 并发/prefetch、ACK 时机、reclaim、超时和重试均由 dotenv 构建，systemd 不重复框架参数。

健康检查：API/WS/combined/jobs 保留 `/health/live`、`/health/ready`。worker/scheduler 无 HTTP：`app.manage health --role worker` 先要求本 release 的 SQL 心跳和最近成功执行，再真实入队 probe 任务并等待正确 release 的 worker 执行（`task_probe`）；`health --role scheduler` 只读 Redis 心跳并要求调度计数和最近派发，不创建 SQL 池。worker 缺席时 probe 超时且 readiness 非零。

## 3. 代码模块与关键实现

### 3.1 配置与基础设施

- `backend/app/core/config.py`：角色与 CLI 选择器；API/WS/jobs 池；Taskiq worker/process、async/prefetch、broker/schedule/heartbeat 连接、reclaim、retry、超时、interval 与 probe 参数；`WS_EFFECTIVE_QUEUE_CAPACITY`；SQL/Redis 预算按 worker 进程数和 scheduler 零 SQL 池计算；prod/split 缺共享 Redis、prod 缺显式 Origin、prod 开启 query token、combined 多 worker、bytes<单帧、attempts<retries+1、非有限参数均启动前失败。
- `backend/app/db/session.py`：按角色计算 pool size/overflow，PG 设置 search_path/application_name/lock/statement/idle 超时；显式 `dispose_engine()`；SQL 监听只记录条数/耗时。
- `backend/app/runtime.py`：按角色装配路由、WS、InMemory/真实 Redis Taskiq runtime；lifespan 关闭任务、broker、KV 与 engine。
- `backend/app/observability.py`：请求 ID、HTTP/SQL/event-loop 计数、pool checkedout、慢请求分类；不记录 SQL 参数、token、URL、消息正文。
- `backend/app/jobs/`：`broker.py`（官方 broker/scheduler 与安全 ACK 回收）、`tasks.py`（版本化任务与静态 schedule）、`middleware.py`（执行心跳/终态失败）、`heartbeat.py`（scheduler Redis/SQL 心跳）、`runtime.py`（combined/jobs 的官方 Receiver/SchedulerLoop）、`probe.py`（真实任务探针）、`state.py`（进程级 outbox/stream 资源）。

### 3.2 Redis layer

- `app/kv/redis_kv.py`：Lua 固定窗口 `INCR + 首次 PEXPIRE`；Lua GETDEL ticket；owner-token acquire/renew/compare-and-delete lease；Lua sorted-set 跨进程连接槽；独立有界控制池。`MemoryKV` 提供相同方法语义并加进程内锁，但明确不是生产共享状态。
- `app/kv/base.py`：`reset_kv()`/`close()`；连接/命令错误转成不含 key/value/连接串的稳定 `KVError`。
- `app/kv/redis_pool.py`：控制/发布/reader 有界 `BlockingConnectionPool` 和各自获取等待；记录 acquire 时延/超时/耗尽/失败/取消；启动拒绝 URL 查询参数覆盖显式预算；指标不含 URL/key/token/payload。
- `app/realtime/stream.py`：XADD `MAXLEN ~`；每个 gateway 独立 `StreamReader`；Redis 客户端 `Retry(NoBackoff(), 0)`；outbox 使用进程级共享发布池，避免每任务新建池。
- `app/jobs/broker.py`：任务 namespace 默认 `jobs:v1:taskiq`，consumer group 与实时广播 stream 分离；consumer_id 为 `0-0`，消费组首次创建不会丢弃 `$` 之前保留的任务；broker 不设 MAXLEN；`ReclaimingRedisStreamBroker` 保留 Taskiq 官方消费/reclaim/retry，只覆盖 ACK 钩子为 `XACKDEL ... REF_POLICY ACKED`，仅在全部 group 确认后回收。startup 在消费组初始化后，用不可能存在的 stream ID `0-0` 执行 `XACKDEL ... ACKED`，验证实际命令及 ACL（不改变任何任务载荷），Redis <8.2 或权限不足直接失败，不回退弱 ACK。schedule source 使用 JSONSerializer，不用 pickle。

### 3.3 持久事件、outbox 与保留

- `app/models/realtime.py`：`realtime_events`（含 `dead_at`）、`user_event_counters`、`realtime_retention`、`idempotency_records`、`service_heartbeats`。
- `app/realtime/events.py`：intent 只登记到 `Session.info`；最外层 `before_commit` 统一 flush 业务行，按整个事务 recipients 排序逐个 counter `FOR UPDATE`，一次分配全部 `user_seq` 并插入事件；savepoint/rollback/close 和首 SQL 前回滚均有独立测试；无全局 counter 锁。
- `app/realtime/dispatcher.py`：`OutboxService` 只提供有限 batch domain service；claim 用 `FOR UPDATE SKIP LOCKED` + 可回收 lease，提交后 XADD，再按 owner token 条件确认；失败释放 lease、记录稳定类别，达到 `OUTBOX_MAX_ATTEMPTS` 写 `dead_at`；不读 `next_retry_at`、不写自制退避，Taskiq 拥有框架重试；`run_bounded` 有 batch/time 上限；`realtime-retry` 人工清 dead/attempts。
- `app/realtime/admission.py`：pending 数/年龄软准入在 intents 收齐后、counter 写入前检查；超预算整体回滚，API 503 + Retry-After；短缓存按 engine/schema/budget 隔离；不持全局锁。
- 迁移 `f3a4b5c6d7e8_realtime_layers.py`：expand-only 新表，含 `dead_at` 与索引；PG 显式给 app 角色所需权限，audit 仍只 SELECT/INSERT。

### 3.4 Taskiq 任务与重试

- 任务名/参数版本化：`project1.jobs.outbox_dispatch.v1`、`timeout_scan.v1`、`retention.v1`、`idempotency_cleanup.v1`、`probe.v1`；测试专用 slow/retry probe 只通过 `TASKIQ_EXTRA_TASK_MODULES` 在集成进程加载，生产默认不加载。
- 静态 schedule 用官方 `LabelScheduleSource`，显式固定 `schedule_id`（outbox 1s、timeout 按现配置、retention 300s、幂等清理 900s），scheduler 重启重建相同集合，不追加随机重复。
- 延迟重试用官方 `SmartRetryMiddleware` + `ListRedisScheduleSource`（JSON），只对 `RetryableJobError` 重试，按配置次数/指数/上限/jitter；默认 `ack_type="when_executed"`，收到消息不提前 ACK。
- worker 中间件在 startup/shutdown/pre_execute/post_execute/on_error 写 SQL 心跳与 `last_success_at`/successes/failures/terminal_failures；终态失败同时写 Redis `jobs:terminal-failure:<release>`。人工恢复：outbox 用 `realtime-retry`；框架任务无通用 DLQ，代码缺陷修复后由周期 sweep/重新触发恢复，终态记录用于定位。
- scheduler 的自定义 schedule source/scheduler 子类在 schedule 刷新、成功派发和关闭时写 Redis 心跳；`health --role scheduler` 检查 freshness、dispatch_count 和 last_dispatch_at。

### 3.5 WS gateway（AnyIO）

- `app/realtime/gateway.py`：每连接 `anyio.create_memory_object_stream(effective_capacity)`，移除 `asyncio.Queue`、`queued_bytes`、`space_available` 和手写等待唤醒。
- 实时 `_broadcast` 用 `send_nowait`，`WouldBlock` 立即 1013 关闭该连接；历史 `_catch_up`/`_fill`/`_fill_user` 用 `anyio.fail_after` 包裹 `await send`，超时关闭；close 关闭收发两端，丢弃旧帧并唤醒阻塞 sender；writer 独占 WebSocket close 并负责 drain/close。
- 保留先注册再读 high/low watermark、非零 `since`、连续 `user_seq`、gap 触发 PG fill、resync 后停止旧连接补发、每连接 delivery lock、每页 SQL 会话在发送前关闭、周期按用户合并 reconciliation、授权到期 reaper、连接/握手/帧限制、心跳与 drain。
- `app/ws/endpoint.py`：`?ticket=` 唯一默认凭据；`?token=` 仅 `ALLOW_QUERY_TOKEN=true` 且非 prod；鉴权后不持 SQL。日志过滤器与 Nginx 模板不记录 query。
- `app/api/v1/realtime.py`：`POST /realtime/ticket`、`GET /realtime/watermark`、`GET /realtime/events`。

### 3.6 客户端

- `frontend/mobile/src/api/realtimeProtocol.mjs` 与 `ws.js`：ticket、单例连接、user_seq/event_id 去重与连续游标、ACK、HTTP 补拉、`resync_required` 刷新、账户切换清理、心跳超时、0.5–30s jitter；`applySequenced` 等待 async 业务回调成功后才 commit/ACK。
- `Chat.vue`/`Layout.vue`：保留 `message`/`notification` 业务回调与已读语义；发送/发布可选 `Idempotency-Key`。
- `frontend/mobile/tests/realtimeProtocol.test.js` 覆盖连续、重复、gap、resync、游标重置、retention 边界与退避上下界。

### 3.7 幂等与数据库/Web 优化

- `app/api/idempotency.py`：未传 header 行为不变；PG 事务级 advisory lock + 同事务记录；SQLite 离线单进程锁 + 唯一约束；同键不同 body 409；`cleanup_expired` 改为 Taskiq 调用的有限 batch 清理。
- 发布只存 `product_id` 重建签名响应；IM 只存 message id。
- 会话列表批量投影，保留响应字段与签名图片读取权限；未凭猜测新增索引。请求 ID、SQL 耗时/条数、pool checkedout、event-loop lag、outbox pending/age/dead、准入、Redis acquire、WS 连接/拒绝/慢客户端/resync/ACK 已加入。

## 4. 协议兼容矩阵

| 客户端 | 新后端（ticket，prod） | 新后端（`ALLOW_QUERY_TOKEN=true`，仅 dev） | 旧后端 |
|---|---|---|---|
| 新移动端 | 支持：ticket→hello/replay→event/ACK | 不支持（客户端只走 ticket） | 明确失败：ticket 404/协议版本不足停止重连 |
| 旧移动端（query token） | 关闭：4401；生产必须升级 | 过渡可用（显式开关） | 保持旧行为 |
| 新 Rust loadtest | 支持：ticket、GET watermark 后 since=high_seq、hello/replay、ACK、事件去重/gap | 支持 | 明确失败：ticket 缺失/版本<2 |
| 旧 Rust loadtest | 失败 | 失败 | 旧行为 |

服务端事件 envelope 为 `type=event, event_id, user_seq, event_type, entity_type, entity_id, version, payload, created_at, recipient_user_id`；旧业务回调字段在 `payload` 内。ACK 是设备投递进度，不改变已读；已读仍由 `/conversations/{id}/read` 推进。

## 5. 实际命令与结果

均在 `project1-realtime` 工作区执行；Python 使用 `backend/.venv`。离线 pytest 使用本轮临时 `offline.env`（SQLite/local、假 SMTP、未追踪，运行后删除），没有读取真实 `.env.dev`；真实集成使用本轮临时 PG/Redis（已停止并删除 data 目录），没有使用既有实例。

| 命令 | 结果 |
|---|---|
| `backend/.venv/bin/python var/headless/root-offline-check.py -q --ignore=tests/acceptance_real`（本轮私有临时 helper，内部生成 SQLite/local dotenv；常规入口为选定测试 dotenv 后执行 pytest） | **135 passed, 1 skipped**（skip 为未加载真实集成的隔离入口） |
| 真实 PG/Redis 托管模式：`CI_REALTIME_APPROVED=1 CI_REALTIME_PG_ADMIN_URL=... CI_REALTIME_REDIS_MANAGED=1 .venv/bin/python -m tests.integration_real.runner` | **28 passed**：跨进程 API + 两个 WS + 原生 worker + scheduler、真实 probe、ticket、ACK、outbox 确认、杀 worker 后 XAUTOCLAIM 接管、重试成功/最终失败可见、scheduler 重启 schedule 不重复、停 worker 且 Redis `SHUTDOWN NOSAVE` 停机期间提交事件后 WS 从 PG 补扫、Redis 同端口重启与 worker 重启后 probe 成功、worker 缺席 readiness 失败、retention/ACK 回收、回滚无事件、counter 并发、lease 接管、无 SQL 持锁、低权限角色、幂等、准入、Redis 有界池 |
| `cd backend && .venv/bin/python -m tests.acceptance_real.runner --port 8123`（私有 SQLite/local 临时 dotenv） | **51/51 检查通过；115/115 路由、105 AC、109 SC、14 主用例、66 子用例通过**（含新增 realtime/health 语义调用；清理失败 0） |
| `backend/.venv/bin/python -m pytest -q scripts/deploy/tests` | **29 passed**：combined/split 4 角色激活、旧 3 角色成套停止、release/role 身份、health 失败回滚、启动失败回滚、rollback stop 失败上报、缺配置、preflight 路径/mode/新角色、sudoers 精确 unit、Nginx fragment、systemd 非 root |
| `cd loadtest && cargo test --locked` | **17 passed** |
| `cd loadtest && cargo clippy --locked --all-targets -- -D warnings` | 通过 |
| `cd frontend/mobile && npm test` | **52 passed** |
| `cd frontend/admin && npm test` | **6 passed** |
| `cd frontend/mobile && PROJECT1_FRONTEND_CONFIG=public npm run build` | 通过 |
| `cd frontend/admin && PROJECT1_FRONTEND_CONFIG=public npm run build` | 通过 |
| `uvx ruff check`（新增/修改 backend 与 scripts/deploy） | 通过 |
| `python3 scripts/cli.py check` | 通过（版本/引用检查；未跟踪新文档另行手工核对） |

真实集成证据：托管 Redis 由 runner 以随机端口、独立目录、`--save '' --appendonly no --maxmemory-policy noeviction` 启动；restart 门禁先停 worker，在 Redis 停机期间提交事件并确认 WS 仅靠 PG 补扫收到，再执行真实 `SHUTDOWN NOSAVE` 的同端口重启和 worker 重启。PostgreSQL 为独立 data 目录、端口 55432、trust 仅测试实例；runner 随机 schema/角色/前缀，测试后 drop schema/role、按前缀 SCAN+DEL，未清理其他资源。API 与两个 WS 使用真实 uvicorn 子进程；worker/scheduler 使用 `app.manage taskiq-worker`/`taskiq-scheduler` 的真实 Taskiq 进程；任务由 scheduler 投递、worker 执行，测试通过 broker 入队 probe 而非直接调用 task 函数。杀 worker 测试先等待 slow probe `started`，SIGKILL 进程组后重启，依赖 Taskiq 的 XAUTOCLAIM/`unacknowledged_batch_size` 取得未 ACK 消息；scheduler 持续派发 outbox 使读循环走到 reclaim 分支。重试测试第一次失败后由 SmartRetry + Redis schedule source 重新投递成功，最终失败写入 `jobs:terminal-failure:<release>` 和 SQL 心跳。

替身/离线证据：SQLite + MemoryKV + fake systemctl/health + InMemoryBroker 只证明代码路径和回滚逻辑，**不**证明真实 PG 行锁、Redis 共享状态、systemd/Nginx 或生产部署通过。combined 的 InMemoryBroker 明确不是 Redis 可靠性等价物；真实可靠性证据来自上面的 Redis 进程集成。

## 6. 第二轮独立审阅修复对照

| # | 状态 | 证据 / 剩余边界 |
|---|---|---|
| 1 | 已修 | outbox 使用真实 Redis stream；跨进程测试在关闭周期 reconciliation 时仍靠 stream 快速送达 |
| 2 | 已修 | event_wire 含 recipient_user_id；stream 解码合同与跨进程事件测试 |
| 3 | 已修 | 连接初始化 `sent_seq=ticket.since`；非零游标无/一条新事件测试 |
| 4 | 已修 | 每连接 delivery_lock 串行 gap/入队/游标；乱序不前进 |
| 5 | 已修 | `_fill` 用连续 sent_seq；resync 后停止 fill/reconcile，客户端 await 快照后才重连 |
| 6 | 已修 | reaper 到期 4401；每 IP 限额实际使用；握手按 TCP 直连地址计数 |
| 7 | 已修 | 移除全局 counter-order 锁；intents 在 before_commit 按全事务 recipients 排序锁独立 counter；真实 PG ABBA/反向/互不相关事务 |
| 8 | 已修 | 新增/修改查询统一 sqlmodel.select + col；无 hasattr 兜底 |
| 9 | 已修 | retention 只删连续已投递过期前缀；低水位单调；advisory 仅串行清理 |
| 10 | 已修 | outbox age 用事件 created_at；Taskiq 重试；`dead_at` 终态与 `realtime-retry`；中间件心跳不掩盖死任务 |
| 11 | 已修 | `_reconcile_ok` 只在 DB 成功后置真；heartbeat 过滤 release/stopping；启动/停机/旧 release 测试 |
| 12 | 已修 | timeout scanner 使用 `jobs:timeout-scan` owner-token lease；DB 锁兜底 |
| 13 | 已修 | Redis 客户端 `Retry(NoBackoff(),0)`；预算计入各 Taskiq broker/schedule 池、worker 进程数、scheduler 心跳 |
| 14 | 已修 | release_id 只从 release.txt 按 key 解析并校验 40hex-build |
| 15 | 已修 | Counters.observe 单锁；SQL first-SQL wait/hold 计数；API event-loop lag；frame 边界校验 |
| 16 | 已修 | 按用户分组合并 reconciliation，限并发，最多一次读取 |
| 17 | 已修 | SQLite 异常路径释放锁；PG 锁随事务；重放不重复写成功审计 |
| 18 | 已修 | PG pending 数/年龄软准入、503 Retry-After、缓存隔离、真实 PG 回滚/恢复/读/dispatcher/API；Redis 有界池与独立 XREAD |
| 19 | 已修 | runner setup 失败也进 finally cleanup；PG/Redis 清理异常计入 exit code；`--keep` 只保留私有 env |
| 20 | 已修 | await handler 后才 commit/ACK；帧串行；resync await 快照；epoch fencing |
| 21 | 已修 | 跨进程测试启动两个真实 WS 进程并设 reconcile=3600 只允许 stream 快速送达 |
| 22 | 已修 | runner 每次随机端口写临时 env |
| 23 | 已修 | 激活脚本以 deploy 运行；sudoers 只列 exact start/stop 固定 unit + backup；测试钩子不经过提权 |
| 24 | 已修 | 锁内识别 previous；成套停止旧 combined/旧 3 角色；stop 失败上报；HTTP/CLI readiness + MainPID cwd；旧 `/api/health`；ACTIVATED 兼容 previous_release |
| 25 | 已修 | Nginx 为可合并 location/upstream fragment；/ws `access_log off`；不丢静态 root/PWA；10m body、$scheme 保持 |
| 26 | 已修 | preflight 按 mode 只验对应角色；split 另验 combined 回退；新角色 worker/scheduler 无 HTTP 端口 |
| 27 | 已修 | systemd ProtectHome=read-only + 窄 ReadWritePaths；worker/scheduler unit 静态测试；现场 systemd-analyze 待管理员 |

## 7. 关键取舍

1. **至少一次而非 exactly-once**：发布后确认前崩溃允许重复；客户端按 event_id 去重、连续 user_seq 提交。
2. **Redis 是加速器，PG 是事实源**：WS 周期回放不依赖 stream 存活；Taskiq 任务 stream 丢失时 outbox 周期 sweep 仍恢复。
3. **角色选择器放运行时**：四个 split 角色共用一个 dotenv，`APP_RUNTIME_ROLE` 只选择进程角色。
4. **框架 owns retry**：`next_retry_at` 不再参与 claim；Taskiq SmartRetry 调度延迟重试，outbox sweep 只兜底；`dead_at` 终止无限重试，人工恢复显式。
5. **AnyIO 保守容量**：按最大帧推导槽位，牺牲部分字节利用率换确定上限；live 满即断、history 有界等待，均不手写队列内部状态。
6. **任务 stream 不 MAXLEN**：避免裁剪未 ACK pending；Redis 8.2+ ACKED 回收仅在全部 group 确认后删除；Redis <8.2 或缺少 XACKDEL ACKED 权限时启动失败，不回退到弱 ACK。
7. **scheduler 单实例**：两个 scheduler 会重复派发；激活脚本成套停止旧 scheduler 后启动一个，静态 schedule_id 固定以避免重启重复。
8. **worker 无 HTTP**：受控 CLI readiness 执行真实 probe，避免每个 worker 抢同一端口或以 PID 冒充消费成功。
9. **combined/jobs 仍用官方框架**：combined 用 InMemoryBroker，jobs 用真实 Redis；两者都没有手写消费/重试循环，但 InMemory 不声称 Redis 可靠性。
10. **激活脚本以 deploy 运行**：只通过精确 sudoers 启停固定 unit，不接受 root 任意脚本/Python。

## 8. 未完成 / 现场验证项

- 生产 systemd 安装、`systemd-analyze verify`、Nginx `nginx -t`、固定用途 sudoers 与 split `/ws` upstream 切换未在本机执行；仓库只提供模板和 fake 测试。
- 真实生产 PostgreSQL 迁移、低权限角色、备份/expand migration、ACTIVATED/回退未在生产链路执行；真实 PG 集成覆盖迁移和权限，但不是生产实例。
- 真实 OSS 双桶、签名 URL、CORS、真实 SMTP 收件箱、浏览器 PWA/WS 人工验收未做。
- 400 混合场景/容量、1/2/4 API worker、pool 4/8/12、WS 连接/重连风暴、真实反向代理链路未测；不宣称 400 通过。
- `EXPLAIN(ANALYZE,BUFFERS)`、搜索 trigram、列表投影进一步优化、commit→gateway→ACK 完整延迟指标未完成。
- 准入是带缓存/在途窗口的软阈值，不是精确全局硬上限；生产需按部署并发预留余量。
- 真实多主机/跨主机 Redis TLS、ACL、AOF everysec、noeviction/maxmemory、FD/内存预算演练未做。
- Jenkins 新增 integration/Taskiq gate 依赖管理员创建 `realtime-ci-pg-admin-url`（当前托管 Redis 不要求 URL 凭据） 凭据；缺凭据会失败而非跳过。GitHub Actions 改为 runner 托管 redis-server 并安装系统包；两者均未在本轮触发验证。Jenkins 外部 Redis 无法进程重启时，restart 测试走真实连接断开路径并在报告中区分；本地/GitHub 托管模式执行完整 `SHUTDOWN NOSAVE` 重启。
- 旧后端/旧前端兼容只通过代码边界和版本检查表达；未启动旧构建做实际互操作测试。

## 9. 上线一次性管理员步骤

1. 按 `scripts/deploy/README.md` 安装 combined/api/ws/worker/scheduler（以及旧 3 角色回退所需 jobs）systemd unit、固定用途 sudoers、split Nginx 模板；先备份并用 `systemd-analyze verify`、`nginx -t`、`visudo -cf` 校验。
2. 在生产 dotenv 配置显式 `ALLOWED_ORIGINS`、共享 Redis/前缀/ACL、AOF everysec、`noeviction`/maxmemory、Taskiq 预算；确认生产/旧版本 pool、worker 进程数与 Redis maxclients 总预算。`ALLOW_QUERY_TOKEN` 保持 false。
3. 创建 Jenkins 凭据 `realtime-ci-pg-admin-url`（当前托管 Redis 不要求 URL 凭据），指向专用 CI 实例；不要让 CI 使用生产凭据。若使用托管 Redis 重启门禁，CI agent 需有 `redis-server` 二进制。
4. 确认迁移/备份/`PREPARED`/`MIGRATED` 后，在维护窗口以 deploy 运行 `se-course-project1-activate --sudo --verify-process --release-id <id> --mode split --backup-dir <predeploy-dir>` 成套切换；脚本按旧 ACTIVATED 服务集合停止旧角色，启动 scheduler→worker→ws→api，worker readiness 会执行真实 probe；再验证真实 ticket→WS→持久事件→ACK，最后人工切 Nginx `/ws` upstream 并开放流量。
5. 失败时保留 `ACTIVATION_FAILED`、旧 `current`、日志与备份；脚本按旧服务集合回退，不自动回滚数据库/Redis/Nginx。管理员必须人工恢复旧 `/ws` upstream/停用新路由；回退后重新升级需客户端 resync/版本水位。
6. 复核 Redis 监听/防火墙/TLS、PostgreSQL 连接预算、文件描述符、内存、代理链 300s WS 超时及前端 PWA 缓存。

## 10. 不得直接部署的限制

本轮未提交、未 push、未创建 PR、未触发 Jenkins、未 SSH、未部署生产、未修改既有 PostgreSQL/Redis/OSS。仓库资产需要主执行者审阅 diff、在隔离环境复跑门禁，并由负责人完成现场安装/凭据/维护窗口和真实验收后才能进入生产；本文件不构成上线批准。

GitHub 托管 runner 从 Redis 官方 APT 仓库安装测试二进制，避免发行版自带旧包缺少 XACKDEL；本地未执行 Ubuntu 安装或远程 GitHub/Jenkins 流水线。现场依赖与实际流水线仍需验证。官方步骤见 [Redis Linux 安装说明](https://redis.io/docs/latest/operate/oss_and_stack/install/archive/install-redis/install-redis-on-linux/)。

## 本次提交前状态

工作目录已迁至 project1；性能测试已按用户要求停止，未完成档位不算通过。最新单元测试135通过，部署及配置迁移检查34通过、1项真实Nginx语法检查因本机无二进制跳过；CI强制要求Nginx校验器。Rust20项及Clippy已通过。业务acceptance迁至四角色尚未实现，保留原SQLite/local门禁；PR为Draft，不声称CI收敛完成或可直接部署生产。

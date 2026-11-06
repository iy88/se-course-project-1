<!--
Version: 0.1.0
Version-Datetime: 2026-11-06T22:35:00+08:00
-->

# issue #36：dsh headless 实施 Prompt

本文件的“任务正文”提交给 DeepSeek Harness headless；关联 [设计合同](realtime-layers-design.md)。用户允许项目源码发送给 DeepSeek 模型及其 API endpoint，禁止把实际配置秘密和业务数据作为上下文。此次实现独立于 [单 worker 基线 PR #35](https://github.com/iy88/se-course-project-1/pull/35)。

## 调用与交接

在独立工作区、分支 `feat/36-realtime-layers` 执行 `dsh headless --permission-mode workspace-write --approval-policy never -`，从标准输入传入任务正文。headless 没有 Git/生产发布授权，不自行创建 agent 或向其他提供商发送代码。模型及 endpoint 使用本机既有 headless profile，调用记录不保存 API key。

实施后由主执行者审阅 diff、运行必要检查、修正问题；保留待现场验证范围。实施状态和验证证据写入 `realtime-layers-implementation.md`，不覆盖设计目标。设计和 prompt 存档不代表实现通过。

## 任务正文

你正在实现校园二手平台 issue #36。你是实际代码执行者，请完成代码、测试、配置示例、仓库 CI/CD、部署模板和文档，不能只回答方案。先完整读取 AGENTS.md、README.md、docs/development/realtime-layers-design.md、部署说明.md、load-testing.md 与本 prompt，再检查当前代码。设计合同是目标；若发现不可行之处，应给出证据和实现取舍，并保持业务正确性，不擅自缩减为仅单测通过。

### 用户授权、分支和安全边界

- 本轮用户明确授权：细化并存档 Redis/WS/数据库/Web 分层设计及 CI/CD/更新方案，调用 dsh headless 实现；允许发送项目源码给 DeepSeek API；新方案单独 issue 和 feat 分支。这构成 AGENTS.md 所要求的本轮文件修改与必要离线/隔离构建测试授权，不需要因已有授权重复停下询问。
- 仅修改当前工作区 `project1-realtime` 的 `feat/36-realtime-layers`。禁止修改原 `project1` 或其 feat/34-load-test，不执行 git checkout/reset/stash/merge/rebase/commit/push，不创建 PR/issue，不触发 Jenkins，不 SSH、不部署生产，不创建其他 agent。
- 不读取真实 .env.dev/.env.prod、私有 var/manifest/log、SSH/keychain/API secrets、其他用户工程与会话。既有 headless profile 的 API credential 仅由工具正常使用，不打印或抄入文件。给模型的文件只来自 tracked 源码/本次设计和新代码。
- 不运行 reset/seed 清现有资源，不修改既有 PostgreSQL/Redis/OSS。测试资源使用工作区临时目录、本机临时进程或显式 CI 测试配置，并具备所有权与清理。不能 FLUSHDB/FLUSHALL，不能向非 DeepSeek 提供商传输代码。
- 可复用原项目已安装的 Python/Node 工具链运行源码测试，但不得改动其环境或源码；若当前 .venv/node_modules 不存在，按锁文件安装到当前工作区。依赖安装、测试所需缓存与临时产物属于本轮实现范围。不要把真实 dotenv 复制进工作区。若无法完成真实 PG/Redis 测试，明确记录，不把替身/SQLite 当真实 PG 通过。
- 保留历史需求口径。封禁用户仍可只读接收本人事件；交易锁顺序/唯一约束、审计不可变、共享已提交图片等规则不得削弱。实际 API/WS 协议前后端与 Rust 一并维护。

### 实施顺序与模块边界

1. 配置/基础设施：Settings 添加明确 API/WS/jobs 角色配置、有限 SQL 与 Redis 池/超时、队列/事件限制。仍由 APP_ENV_FILE 所选 dotenv 提供业务配置，继承 env 不覆盖。combined 兼容现有 `serve` 单 worker；独立 api/ws/jobs 有实际 CLI 入口与生命周期，不启动重复扫描。production/split 多进程拒绝进程内 KV fallback。engine、Redis client、任务在进程内创建并关闭。
2. Redis layer：修复 RedisKV.incr_with_ttl，Lua 保证固定窗口首次 TTL；一次性 ticket 原子消费；owner-token lease；独立阻塞 stream reader 连接；有限控制池；连接/读取/等待超时；安全日志与错误分类。离线 MemoryKV 保留相同语义但不是生产共享状态。验证码不得因 Redis 故障 fail open。新增生命周期 reset/close 不破坏测试全局隔离。
3. 数据库迁移与 realtime：SQLModel 事件模型、per-user 独立 counter、outbox claim lease 与重试。业务/事件/审计同事务；发送消息和 notify 不直接碰 socket。生产迁移显式 app 权限，保持 audit 权限。PG 用 SKIP LOCKED/短 claim 事务；Redis I/O 不持 SQL 事务；发布后崩溃允许重复，支持 lease 接管。实现事件保留与低/高水位、按用户授权的分页 replay/resync。counter 初始化/分配并发安全、统一顺序，不用全局自增消息 ID 当提交序。
4. WS gateway：独立 XREAD cursor 广播过滤，禁止所有 gateway 共用一个分摊 consumer group。一个连接一个 writer、消息数/字节队列、慢连接断开、所有 pong/控制统一发送、帧与频率限制、跨进程连接限额、心跳和优雅排空。ticket+Origin+授权期限；鉴权后及时归还 DB；本地连接注册与持久回放衔接无丢窗。对 Redis 丢 stream/最后事件丢失有 PG 周期水位补偿，不能只检测后继 gap。ready/degraded 明确。
5. 客户端：移动端 ticket 获取、事件 user_seq/event_id 去重与连续游标、ACK、补拉、resync_required、账户切换清理、心跳超时与 jitter 重连；保留 Chat 的既有业务回调和已读语义。Rust loadtest 同步适配 ticket/握手/ACK，steady/race/capacity 判定口径不能退化；测试旧后端兼容或明确版本边界。
6. 请求幂等与数据库/Web 优化：给发布与 IM 等易受连接重置影响的写入口提供可选 Idempotency-Key，幂等记录与业务同事务、并发同键只一份结果、相同键不同 body 拒绝。保留未传键行为。加入安全 pool/SQL/事务/event loop/outbox/投递观测；选择有代码证据的列表/搜索投影/批量加载优化并证明响应不变。不凭猜测修改索引/SQL 或用大连接池掩盖长事务。
7. CI/CD：保留既有功能验收。提供 CI 专用真实 PG+Redis integration runner 和 Jenkins 严格门禁（缺配置失败，不 silent skip）；测试真实迁移与低权限 app 角色、不同进程 WS、原子 KV、rollback/retry/replay/故障/竞态，失败清理仅自有资源。提供 API/WS/jobs systemd、Nginx /ws upstream、固定用途激活脚本/受限 sudoers 模板。Jenkins 归档部署资产、preflight、备份与 expand migration、成套切换/健康/失败回退，遵守现有 release/current/activation lock。首次 split 用明确维护窗口，不假装零停机；旧 combined 路径有兼容回退。系统模板需要管理员安装，不在本机自动安装。
8. 文档：更新开发入口、示例参数、角色命令、连接预算、Redis ACL/AOF/noeviction/maxmemory 升级条件、CI 依赖准备、发布/回退操作、协议兼容矩阵与生产验收未决事项。不要复制外部交接中的真实 IP/邮箱/数据库名进公共新文档，用参数或占位符；既有历史文件不做无关清理。

### 测试与质量门槛

- 执行有意义的针对性 pytest；全离线套件 `python -m pytest -q --ignore=tests/acceptance_real`。现有独立全量验收是 opt-in，不可强行更改它使失败变 skip；新增真实集成独立入口，缺 CI 前置条件失败。
- 真实 PostgreSQL/Redis 测试合同覆盖：跨进程双方多设备、回滚不见事件、counter 并发初始化、claim lease 过期/重复、最后事件无后继也恢复、trim/Redis 重启补偿、慢客户端有界、无 SQL 长期占用、ticket 并发消费、固定窗口 TTL、跨 gateway 限额、同键发布/消息一份结果、交易/发布不变量。
- 对前端协议写可运行测试（可使用 Node 内置 test，避免无谓新增框架），两端构建；Rust cargo test --locked、cargo clippy --locked --all-targets -- -D warnings。处理测试发现的真实问题，不能仅降低阈值。
- 部署/CI 脚本测试覆盖 legacy/split、任一步启动/健康失败的成套回退、release 身份、缺 gate 配置、shell quoting 和资源所有权；可用受控替身，不访问真实 systemd/Nginx/生产。
- 不跑现有 .env.dev 的压测/seed，不宣称 400 混合场景通过；生产准入需要负责人现场配置和真实验收。
- 保持职责模块化，避免把全部实现塞入 main.py/manage.py/ws endpoint；使用 sqlmodel.col 处理 ORM 查询类型，避免原有 Pylance int.in_ 问题。注释说明一致性/失败边界，不堆空占位或 TODO 冒充完成。
- docs/README/AGENTS 按仓库版本规范处理；AGENTS 本身不修改。修改文档的版本以最后提交统一登记，不因多轮重复递增。新设计/prompt 的原始目标保留，可追加有依据的修正。

### 最终交接格式

完成后给出：改动文件与模块、实际命令和结果、真实/替身证据区分、关键取舍、未完成的具体项、上线一次性管理员步骤、不得直接部署的限制。写入 `docs/development/realtime-layers-implementation.md`；若集成或构建受工具/网络限制，记录确切命令和错误类别，不打印 secret。不要提交/push。不要仅完成规划便退出，尽力完成授权范围内实现与回归。


## 第二轮：独立审阅修复 Prompt

首轮在实现/测试检查点结束，第二轮复用 headless 会话处理下列独立审阅意见。以下记录针对初稿，修复时先核查当前源码，已解决项用证据关闭。所有原有工作区、秘密、Git 和生产边界继续适用。优先实际正确性与部署安全，不做无关重构和格式整理。集中完成修复后运行定向回归，再运行一次必要完整门禁；不要为重复计数、清理缓存或无关格式而循环重跑全部检查。完成后立即写入交接记录并结束任务。

# 独立审阅待复核事项

这是主执行者对尚在生成的第一版实现的审阅记录。请先重新核查当前代码，已修正项无需重复改；其余必须用有意义回归验证。仍遵守原 prompt 的工作区、秘密、Git、生产与资源边界。不要只回复解释，修复实际实现并更新实施记录。

1. runtime.py 构造 OutboxDispatcher(settings) 没传 stream，dispatcher._publish 在 stream=None 时直接返回；即使 Redis 已配置也会标记 delivered 却完全不 XADD。需要按角色创建/关闭实际 stream，加真实 Redis XADD 与多进程接收测试，不能只靠 PG 轮询掩盖。
2. events.event_wire 没 recipient_user_id，stream 外层字段是 user_id；gateway._broadcast 却读 frame['recipient_user_id']。核对序列化/解码合同，证明关闭/延长周期补偿后仍通过 stream 快速送达。
3. Connection.sent_seq/acked_seq 初始 0，没有初始化到 ticket.since。高游标重连且没有新事件时 replay_complete 会错误返回 0，fill 从 0 重放。增加非零游标且无新事件、恰好一个新事件的测试。
4. catch_up/fill/broadcast 在 await enqueue 时并行更新 sent_seq，锁只保护队列不保护投递顺序。每连接应有统一交付串行化；gap 校验、cursor 更新和入队作为同一顺序单元；测试广播与补拉交错无 seq 回退/漏项。
5. _fill 使用 conn.since（建连原始值）与 retention low 比较而不是连续交付/ACK 状态，长连接会在旧历史清理后反复 resync。resync_required 后仍标 replay_done、周期 fill 不停发 resync/旧事件，客户端快照与 reconnect 协议需真正完成。
6. JWT/ticket 认证期限只在连接建立检查，reaper 没到期检查；长连接可超期继续接收。限制的 ws_max_connections_per_ip 似乎没有实际使用；handshake 默认 30/IP/min 无法支持同机 100 用户负载，需安全且可配置的压测设置与文档。查明反代信任来源，不能裸信任伪造 XFF。
7. 目前每个 notify/emit 立即分配 counter 锁。一个业务事务多次 notify 的接收者集合排序局部正确并不代表全事务排序正确；可能后续再锁商品/交易，或 txA 先锁 user2 再 user1、txB 反过来。应在事务最终阶段集中全部待发事件按统一 recipient 顺序分配，或证明并实现等价无倒序方案；真实 PG ABBA/rollback/retry 测试。新代码 .in_ ORM 属性请用 sqlmodel.col，避免重新引入用户要求修复的 Pylance 问题。
8. 多处从 sqlalchemy 导入 select 却用 SQLModel AsyncSession.exec，返回 Row 而不是模型/标量；应统一 sqlmodel.select 或正确 scalars，不用 hasattr 零散兜底掩盖。检查 events/dispatcher/health/idempotency 所有查询，而不只已有测试触发的一处。
9. advance_retention 按过期 delivered 最大 seq 更新低水位，没保护 pending/leased 前缀、没有清理 worker 间序列化，可能水位回退或跳过未到期/未发布事件。按用户锁稳定顺序清连续安全前缀、低水位单调推进；并发清理/乱序投递/中间 pending 回归。
10. outbox.age_seconds 目前由 now-now 计算永远 0；outbox_max_attempts 配置未见使用；2**attempts 在长期故障可能溢出；_fail 自身 DB 失败会逃逸并杀掉 dispatcher。重试上限、隔离/人工重放、恢复策略要实际可用；工作循环存活与真实进度要影响 readiness，不能循环发 ready 心跳掩盖死任务。
11. Gateway._reconcile_loop 无条件把 _reconcile_ok 设 true，尚未执行 SQL 就恢复 ready；heartbeat/health 不过滤本 release、实例或 stopping 状态，新版本可借旧版本心跳误判。readiness 应检查本角色当前进程/期望 release 的真实运行循环、订阅和数据库；启动、故障、停机测试。
12. runtime scanner 仍每个 jobs/combined 循环执行 scan_once，没有使用 owner lease；并发 jobs 会重复扫描。保留 DB 锁同时加可靠 lease 或明确单 jobs fence/进程约束，异常不要静默掩盖。
13. Redis 客户端要显式禁用非幂等控制操作自动重试，核查已安装 redis-py 的默认 Retry；retry_on_timeout=False 未必禁用默认 connection retries。总 Redis 预算漏了各 RealtimeStream 自建的 2 个连接及 reader 的 1 个；按所有真实池计算并包含发布重叠。
14. release_id 解析读 release.txt 第一行得到 revision=...，实际文件有 revision/build_number/release_id 三项。按 key 解析并验证，不用不受控继承 env 替代文件/明确部署元数据合同。
15. 观测目前仅 SQL 次数/总耗时，pool checkout 等待/持有并未实现；SQL contextvars 在请求开始未清零；counters.observe.max 写没有完整互斥；API 角色没 event loop lag task。不要把平均值/一直为零当 P95/真实时延。payload max 16KiB 与 wire frame max 16KiB 加 envelope 后会断连接，需校验完整帧边界。
16. Gateway 周期给每个连接单独查 PG，1000 连接每秒几千 SQL，会把池打满。优先按用户批量/合并高水位、限制并发与恢复速率；多个同用户设备共用事件读取。真实恢复测试应证明补偿不是无界任务洪峰。
17. 幂等 Guard 在 __aenter__ 取 SQLite lock 后若 _load 抛异常，__aexit__ 不执行，锁永久不释放；_LOCKS 无限按每次新键增长。控制生命周期、异常释放与旧值清理；PG 键锁与已有业务锁顺序也要测。重放幂等结果不能重复写成功审计。
18. Redis backlog 准入/重放限流/Redis pool wait 等设计若未实现，应补齐或在实现记录明确未完成，不能笼统 production-ready。检查 schema migrate/服务启动/完整前端快照/CI严格门禁/成套部署回退都真实有代码和测试。

优先修正阻断跨进程实际投递、游标/锁一致性、故障/发布误报的项，再跑真实隔离 PG+Redis、多进程及前端/Rust 回归。测试错误不能通过扩大为“允许所有错误”或降低现有语义门槛解决。无需继续扩大业务范围。

19. integration runner 的 _setup 失败路径不清理已创建部分角色/schema，_cleanup 报错只打印而 main 仍返回 pytest 的 0；Redis 清理异常被 suppress，门禁可能在泄漏资源后报告成功。所有权 journal/事务化 setup、每种失败 finally 清理、清理复验必须进入最终 exit code；--keep 只能保留私有调试文件，不能掩盖资源残留。
20. 移动端 applyFrame 同步 dispatch 后立即 commit/ACK，没有等待 async handler 完成；handleResync 发 DOM 事件后立即跳 high 并重连，页面快照尚未完成或失败也持久跳过游标。应有 awaitable 的业务应用/快照合同、串行接收、失败不推进、不吞掉 callback 错误、用户切换 epoch fencing；测试 delayed/rejected handler、snapshot失败/期间新事件。reconnectDelay jitter 可大于 30 秒，文档上限与代码需一致。
21. 跨进程测试当前只有一个 WS 进程（默认 WS_WORKERS=1），不能验证独立两个 gateway 广播；_connect 在 ws_port 请求 API ticket，而 ws role 不装业务路由会404。修测试同时必须验证两个实际 gateway 和 stream（禁止全靠 PG reconciliation使测试假通过）。

22. 集成测试 runner 目前固定 18001/18002/18003，多个 CI job 或开发任务同机可能端口冲突；生成本次隔离端口配置并在报告标明，避免误连已有进程。测试应核验 role/release/实例身份，不仅 HTTP200。

23. 部署严重权限问题：sudoers 授予 root 执行 activate.py 任意参数，脚本支持 --systemctl/--python/--health-command/--deploy-root 测试钩子，且默认会以 root 执行 deploy 可写 release 中的 .venv/bin/python；这实际允许任意 root 代码执行。必须移除这种授权。建议激活脚本以 deploy 执行，只 sudo 精确 start/stop 项目固定 unit 的枚举命令（无通配、无任意脚本），备份仍固定独立命令；测试钩子不得经过提权接口。所有应用 Python/health 以 deploy 运行。
24. activate.run 只 stop combined，没有停止旧 split，切 current 后 systemctl start 已运行的 API/WS/jobs 不会重启，可能整套旧进程继续运行却写新 ACTIVATED。previous 在加锁前读取有并发时序问题；stop 失败被全部忽略；rollback 的 self.cwd 仍是新版本，且旧基线没有 manage health 子命令，首次升级无法回退。必须成套停止旧角色、锁内识别 previous、真正 HTTP/WS 与 systemd MainPID/cwd 身份校验、新旧分别在自己的路径检查、兼容旧 /api/health；任一停止/激活/回退失败不能假成功。ACTIVATED 的 previous= 字段与现有 retention.py 期待的 previous_release= 不匹配。必须保持保留脚本兼容并测试旧基线回退。
25. Nginx 模板声称不记录 query，但默认 combined access_log 使用 $request 会记录完整 ticket；应 WS 专用 access_log off 或不含 query 的显式格式，并说明公网层也要处理。新 server 缺少现有两个前端 root，不能作为完整替换；应提供可并入原 host 分流的 location/upstream 片段，不丢静态路径/PWA缓存规则。保持源站 X-Forwarded-Proto https 与10m body限制，不因新方案改成 http/20m。
26. preflight --role all 同时包含 combined 与 api，二者同端口必然报冲突；配置 API_WORKERS>1 时 combined 验证又必定失败，无法准备正常split发布。按目标mode只校验该角色集合，旧模式单独校验。默认 BACKEND_ROOT 从 scripts/deploy 相对算在源码可用，归档后 deploy/preflight.py 的 parents[2] 却指到 releases 而不是当前 release；部署布局必须同样正确并由测试覆盖。
27. systemd ProtectSystem=strict 没 ReadWritePaths，生产可能需要 staged/storage journal 路径写入；ProtectHome=yes 还可能遮蔽 uv 管理 Python 解释器位于 deploy home 的真实可执行路径。与现有生产 Python布局、非root运行及必要最小可写共享目录兼容，提供verify前置条件，不虚构可直接启动。



## 第二轮架构约束补充

# 第二轮继续：架构约束纠正与剩余审阅修复

本次仍沿用原授权、工作区及全部原始审阅清单。上轮在检查点停止，因为已经写入 events.py 的 realtime:counter-order 全局事务 advisory lock 不符合设计，必须移除。

严禁用全局锁串行所有事件事务来关闭审阅第7项：它把所有写消息/通知都串行，并且事务在第一次 notify 后仍可能继续获取商品/交易锁，仍可与业务锁形成等待环。把这一项简单写为“性能取舍”不合格。

请实现事务末尾集中分配方案：emit_events 仅登记到 db.info 的 event intents（业务 payload 已知），整个事务所有 recipients 在 final commit 前统一排序锁独立 counter 行，再分配全部 seq 并插入事件，随后提交。rollback 清理 intents，重试不继承前一事务意图。可使用 SQLAlchemy Session before_commit 同步事件（AsyncSession.commit 通过 greenlet 调用同步Session，事件内可使用 sync_session.connection()/execute，先 flush 业务），按事务元数据装配而非任意业务全局锁；或采用经过证明的等价集中finalize实现。不要误以为 before_commit 必须直接 await：同步 SQLAlchemy session event 可在 AsyncSession 的绿线程上下文里执行同步数据库API。必须兼容项目 prod SessionLocal 以及测试自建 sqlmodel AsyncSession，且 listener 只注册一次、避免重复触发。

不要在 before_flush 分配游标，因为业务在 flush 后还会继续获取其他锁；不要逐端点散落 finalize 而漏掉后台任务、管理处置和测试调用。事务commit前统一flush+counter分配，所有业务锁→所有counter锁的顺序才成立。多次 notify/消息在同一事务按收件人/事件顺序分配，Counter冲突初始化有并发保护，事务失败不能推送或残留意图。父/嵌套事务与 savepoint 回滚的意图必须隔离；SQLAlchemy event 语义不清楚时查本地库源码/官方文档，不猜测。

真实 PG 回归必须含 txA emit给userB 后还写/锁业务行，txB 相反调用顺序，以及同一事务多次 notify 的交错；证明没有全局排他锁，互不相关用户/商品可以并行提交（持住一用户counter不应阻塞其他用户的独立事务）。延迟创建的事件也要保留与业务/审计同事务原子性，测试直接 emit_events 的断言放在 flush/commit 对应正确阶段。

继续完成其余审阅项，尤其 root提权/成套停止与旧版回退、stream实际投递、游标与客户端await快照、readiness、清理门禁。已修正项不反复重做，不做无关format或缓存清理；所有修复集中完成后跑定向及一次全量门禁，记录结果后立即结束。



## 第三轮：运行时背压与 Redis 池补齐

# 第三轮：补齐运行时背压与 Redis 池，集中验证并交接

继续同一授权、同一工作区。原 project1 已由负责人合并 PR #35 并切回 dev；主执行者在确认 7d40bcf 与 squash 提交 d068333 的树完全相同后，将当前独立分支的基线对齐到 d068333，实施文件不变。禁止修改原工作区、提交/push/生产动作。

第二轮已经完成的修复不要重做。主执行者另外修正了源站 Nginx X-Forwarded-Proto=https（保持现有 HTTPS 边缘终止语义），并将 intent-only 的首次事务改为 await db.begin() 开始逻辑事务，避免 await db.connection() 强制物理 checkout；保留这两个修正，验证即可。

请把实施记录中审阅第18项的“部分”补成实际代码，集中完成下面两个运行时缺项后立即验证交接，不扩大业务范围、不循环做无关format/清缓存/计数。容量400、生产部署、浏览器、真实OSS/SMTP、EXPLAIN和1/2/4worker性能调优仍是现场/后续计划，本轮不要跑既有资源。

## A. Outbox 积压准入与恢复

- 增加所选 dotenv 配置的 pending 数量上限、最老 pending 年龄上限和准入统计缓存间隔。给出有限起始默认值与关系校验，支持明确禁用/测试无缓存方式并记录语义。
- 在业务事务最终分配事件前（所有 intents 收齐后）检查 DB 中持久 outbox 积压；超过预算拒绝本次会新增事件的业务事务并整体回滚，返回稳定503和 Retry-After，不提交业务/审计成功记录后才报错。纯读、补拉、清理、dispatcher 与不新增事件的事务继续可用。未超预算时 Redis 短暂故障仍可提交 outbox。
- PostgreSQL 是门禁依据，不以 Redis 故障时不可读的 KV 标志作为唯一准入依据。不引入全局事务排他锁或全局行锁，不在绿色线程数据库I/O期间持 threading.Lock，互不相关业务仍并行。计数走现有 pending 索引且有SQL超时；可采用每 engine/进程的短时统计缓存降低每次COUNT成本。缓存键必须按测试/数据库/引擎隔离并在dispose时失效，避免测试串扰。
- 缓存门禁是带在途/缓存窗口余量的软准入阈值，不声称精确全局硬上限；记录最坏余量与部署预留。count/age恢复后自动放行；长期失败/隔离事件仍计入磁盘积压，不能通过删除未投递事件“解决”。
- 观测拒绝次数、缓存新鲜度、pending/age与降级。补拉/恢复已有按用户批量和限并发，需要保持；新准入不能阻止 dispatcher 解除积压。
- 测试真实 PG：超数量/超年龄时业务+事件+成功审计全部回滚、读与dispatcher仍可用；积压恢复后放行；两个不同用户不被新增全局锁串行。离线可测边界/缓存隔离，不能代替PG语义。

## B. Redis 有界等待与池观测

- 控制池增加 dotenv 的有限获取等待参数，使用 redis.asyncio 的有界 BlockingConnectionPool 或等价实现，保留按角色max_connections、connect/socket超时、Retry(NoBackoff(),0)禁止非幂等自动重试。阻塞 XREAD 仍独立专用池，发布池与控制池的真实预算都计入总数。
- 记录控制/发布/reader各自的池获取时延、获取失败/耗尽/超时等稳定指标，不记录URL、key、token、payload。清楚说明获取时延可能包含连接创建/健康校验，不冒充纯队列等待；观测不能改变正确性或强制SQL checkout。
- 若 Redis URL 的查询参数能够覆盖 max_connections/timeout/retry 等显式预算参数，应在配置校验拒绝这些冲突参数，或确保显式预算拥有最终优先级；TLS连接参数仍有明确支持范围。
- 测试真实 Redis：池满最多等待配置时间后失败、释放后恢复、等待取消不泄漏槽位、XREAD不耗尽控制池；原子计数/ticket/lease语义不退化。提供安全异常分类，无自动重试导致INCR重复。

## C. 最后核对

- 修复后的所有主执行者独立测试文件都必须跑：test_realtime_event_boundaries.py（4项）、test_db_checkout_lifecycle.py、scripts/deploy/tests/test_activation_identity.py（3项）。不能删除/放宽断言。
- 激活脚本 rollback 中停止新服务失败不能静默当完全回退成功；应尝试停止所有新角色、继续尝试恢复旧版本，并将任何停止失败作为回退失败记录，保持Jenkins失败，提供受控测试。保持 unprivileged activation + 精确sudoers，不增加任意root helper。
- Nginx首次 combined/split 切换仍需管理员维护窗口；部署脚本不会自动修改root-owned Nginx时，必须在更新/回退说明明确人工路由恢复步骤，不能声称已自动回退代理配置。
- 实施记录中的“SQL first-SQL wait”应明确是请求到首次SQL的近似阶段耗时，包含应用前置处理与连接准备，不等于纯连接池排队；hold 是依赖scope时长，不等于物理连接独占时长。精确指标未实现可以作为后续观测计划，不虚报。
- 更新设计/示例dotenv/开发入口/部署说明与实施对照，关闭已实现的第18项，保留真实现场未验证项。不要把计划已写成实现或现场通过。
- 跑定向回归后执行一次适用完整门禁（离线后端、真实PG+Redis、部署替身、前端Node/构建、Rust test/Clippy；未涉及且已有通过证据的前端/Rust无需无理由反复跑），检查diff与本地文档链接，清理本轮专用服务/schema/前缀/临时文件；不得清理原项目资源或headless日志。结束时立即给出真实结果、剩余现场前置条件和文件，不再循环全量测试来刷新计数。


## 已确认选型：AnyIO + Redis Streams + Taskiq

# issue #36：执行已确认的成熟队列方案

用户最新明确决定：采用 WS 连接内 AnyIO 有界流 + WS跨进程Redis Streams + 后台Taskiq及官方taskiq-redis。请实际完成迁移、回归、部署/CI和文档，不能只写方案。

## 范围与授权

- 工作区 /Users/iy88/Work/SE/project1-realtime，分支 feat/36-realtime-layers，基线 dev squash d068333；大量未提交修改是上一轮完整实现，必须保留并在其上迁移。原 /Users/iy88/Work/SE/project1 不得修改，不 commit/push/merge/SSH/生产/Jenkins，不创建其他agent。
- 用户明确授权本轮采用方案并实现，沿用已经授权的 dsh headless/DeepSeek 源码传输。真实 .env.dev/.env.prod、私有manifest、生产数据、密钥、原项目var/日志禁止读取/发送；本工作区专用临时测试资源可以创建/使用/清理，不接既有DB/Redis/OSS，不 FLUSHDB/FLUSHALL。
- 必要依赖、锁文件、构建、离线测试与本轮专用PG/Redis临时实例属于本次实现；不做生产安装。依赖已由主执行者 uv add 并锁定：taskiq 0.13.0、taskiq-redis 1.2.4、anyio 4.15.1，backend/.venv 可用。依赖API必须读当前安装源码/官方文档，不猜测不存在参数或重新手写替代框架。
- 先读 AGENTS/README、docs/development/realtime-layers-design.md、realtime-layers-implementation.md、realtime-headless-prompt.md、部署说明.md、scripts/deploy/README.md、当前diff。新方案细则优先于旧稿中“手写dispatcher循环/三角色”的过渡实现。保留SQLModel/col类型修复、交易锁/唯一约束/审计不可变、outbox同事务、非零游标/补拉/幂等/背压/Redis池/安全修复。

## 当前实现与必须保留的主执行者修正

- Outbox intents 只在最外层before_commit集中分配，业务锁→按整个事务recipient排序counter锁；没有全局counter锁；savepoint commit/rollback/flush失败、session复用与首SQL前回滚都有独立测试。不能把队列迁移改为提交前直接push。
- 主执行者已统一 Jenkins combined/split 两种模式到同一个 versioned deploy/activate.py，脚本以deploy运行，sudo只精确start/stop固定unit。不要恢复旧的combined单独激活内联脚本。scripts/deploy/tests/test_jenkins_activation.py 执行提取的shell并fake SSH，必须通过。
- preflight检查API127.0.0.1:8001、WS127.0.0.1:8002与现有Nginx upstream匹配；jobs健康端口可内部配置但不对外。新scheduler/worker拓扑调整时同步合同/测试，不偷偷放开端口检查。
- Nginx是源站HTTP在外层HTTPS后，X-Forwarded-Proto固定https；不丢前端root/PWA缓存，/ws不记录query。
- gateway当前history重放用自制space_available/queued_bytes控制，主执行者已加“20条history+容量4+1ms/frame健康接收方不能被误关”测试；实时队列满必须立即关闭慢连接，不等待它拖累广播。catch_up每页SQL会话在发送/等待前关闭，避免slow socket持SQL连接。迁移AnyIO必须保持这些行为。
- Rust ticket准备已先GET /realtime/watermark再POSTticket(since=high_seq)，避免持久seed反复压测时重放全部旧事件；游标替代无限HashSet并检测gap，ACK所有event，不只有message。保留并给HTTP准备流程加受控回归，cargo test/clippy验证。

## A. 连接内成熟有界流

- 使用 anyio.create_memory_object_stream 与官方send/send_nowait/receive/close接口，移除自制队列容量循环、space_available Event、手写等待唤醒、queued_bytes递增递减等队列内部实现。只保留业务层单writer、发送超时、慢连接策略、游标串行与授权/心跳。
- 实时广播send_nowait满则关闭该连接，不阻塞其他连接；历史重放使用有界await send并设置超时，库处理等待、取消、关闭。close/drain必须唤醒等候者，不能为塞入关闭sentinel再手动清队列；取消与writer独占close由生命周期明确管理。
- 内存同时有消息数与字节安全上限。可按 effective_capacity=min(WS_QUEUE_MAX_MESSAGES, WS_QUEUE_MAX_BYTES // WS_MAX_FRAME_BYTES) 保守推导最大缓冲槽，确保任何合法帧组合不会超过字节预算，不需要手写加权字节队列；记录这种保守容量语义，启动拒绝bytes<单帧上限。流+一个inflight帧的余量也写明。若选择其他成熟库加权限流，需给出官方支持依据。
- 更新依赖中的直接AnyIO声明已完成；不要拷贝第三方队列源码或把原手写queue换名字。测试按行为适配native stream接口，原有断言语义不能降低。

## B. 后台任务使用 Taskiq

- 新增职责明确的 app/jobs 或 app/tasks 模块。使用官方 taskiq_redis.RedisStreamBroker，任务队列namespace与 realtime广播stream分离；task consumer group只用于分摊后台任务，WS各gateway仍独立XREAD广播，不能把WS投递交给同一consumer group。
- Taskiq实际管理worker执行、并发、ACK、失败重试；使用执行后的ACK（如 when_executed），不能收到就ACK。使用官方SmartRetryMiddleware与持久schedule source/框架scheduler处理延迟重试、次数、退避/jitter；不能再写一套Python while/sleep任务消费/重试/延迟队列。明确可重试异常、最终失败可观测和人工恢复。task与outbox业务必须幂等，不声称exactly once。
- outbox批量投递、交易超时扫描、retention/幂等过期清理都作为实际Taskiq任务；使用官方scheduler的interval/cron功能。固定周期用框架静态schedule source，延迟重试需要时用官方Redis schedule source。务必读0.13/1.2.4安装源码与API，避免自己实现scheduler。
- 保留PostgreSQL outbox作为业务提交后断电/Redis丢任务的补偿依据，保留短事务claim + 可回收lease及发布后条件确认；任务框架不能替代SQL原子性。改造现有OutboxDispatcher为有限batch domain service，不再拥有常驻run()/自制指数退避sleep循环；不要让旧next_retry_at调度和Taskiq重试重复叠加。schema兼容字段可保留，但明确最终谁调度retry。
- 高频outbox任务按批处理、有限运行时间/批数与有限并发；周期补扫兜底任务丢失。避免一事件一任务造成Redis任务风暴或周期任务积压爆炸；用框架可用的并发/排程能力、domain lease/coalescing边界防止重叠。即时事务后唤醒若实现，只能best-effort、失败不把已提交HTTP变成失败；周期补扫始终覆盖。
- 任务参数只放ID/小的控制信息，不放JWT、消息正文、签名URL、dotenv或secret；选择安全JSON等序列化，不引入可执行pickle上下文。Redis环境prefix、ACL与maxmemory/noeviction/AOF前提保留；broker pending不能因MAXLEN裁剪而丢未ACK任务，明确任务queue保留/清理合同。
- “任务重试”与“WS客户端断线补拉”是不同机制。WS真实消息从PG+广播stream恢复，不能被framework ACK当设备ACK；客户端已读语义不变。

## C. 运行角色与配置

- split目标是 API / WS / Taskiq worker / scheduler。框架nativeCLI优先；如用官方programmatic runner，必须是真正框架Receiver/Scheduler且生命周期/信号经测试，不能借名字包装旧while loop。scheduler单实例，worker数量、每worker async并发/prefetch、任务超时、ack idle/reclaim、retry、各Redis池及SQL预算全部来自选定dotenv；APP_ENV_FILE业务配置规则保留。
- 各进程SQL/Redis资源在本进程事件循环创建/关闭，不能跨fork/loop复用。broker/control/retry schedule/result backend（若使用）池都计入预算；scheduler如果不使用SQL不虚构SQL池预算。可不用通用result backend，但部署readiness需要有真实任务执行证据。
- 使用任务framework生命周期hook/中间件记录worker与scheduler心跳、release/protocol/实际消费与调度进度。health不能只有PID或独立心跳就假装消费成功。发布检查至少一次真正入队并由正确release worker执行的probe任务；不输出secret。NativeCLI没有HTTP时可用受控CLI/持久心跳/框架结果探针，修改activator对应检查，不强行每个worker抢同一HTTP端口。
- combined/serve兼容入口保持可运行的开发与旧发布边界。任何模式都不能继续启动旧手写任务消费/扫描/重试循环。生产可要求外部worker/scheduler；离线测试允许Taskiq InMemoryBroker等官方测试实现，明确不等于真实Redis可靠性。既有CI SQLite/local功能验收要继续有可运行路径，可用测试专用框架适配或本轮专用Redis；禁止加生产测试路由、silent skip或改验收断言来掩盖后台任务不工作。

## D. CI/CD与更新

- 更新systemd任务worker/scheduler单元、精确sudoers服务枚举、版本化激活/停止/探针/回退、retention保护与preflight预算。框架参数仍从dotenv构建，systemd不展开秘密或重复业务配置。API/WS/worker/scheduler成套停止旧角色后切换；不能旧scheduler和新scheduler同时发任务。
- 兼容回退旧combined基线和本轮过渡的3角色release；ACTIVATED记录角色集合/模式/协议和previous_release；不要自动回滚DB/Redis。任务名称/参数版本化并给出新旧worker共存或排空策略；首次升级维护窗口，Nginx人工切换/恢复边界明确，不假称零停机。
- 当前Jenkins统一激活和真实PG/Redis门禁保留，新增框架依赖/worker+scheduler启动、杀worker接管与队列重试门禁；GitHub Actions同步。缺CI专用资源仍fail closed，禁止连接生产。
- 文档重写为最终选型，不再把当前手写dispatcher循环当最终实现。更新design、implementation、prompt存档、开发入口、dotenv示例、部署操作。docs新文件与README版本在未提交前不重复递增，AGENTS本身不改。

## E. 验证与交接

1. AnyIO：历史页大于buffer但健康客户端成功；实时慢连接不阻塞其他用户；关闭/取消唤醒等待sender；没有SQL lease跨socket等待；容量/最大帧边界与排空。
2. 真实PG+Redis：至少独立API、两个WS gateway、Taskiq worker与scheduler进程，真实框架投递outbox、超时扫描/清理；杀worker后broker恢复/重复幂等；重试成功/最终失败可见；scheduler重启不重复注册任务；Redis断开/重启后PG补扫；worker缺席readiness失败。不能用直接调用task函数证明队列运行。
3. 保留所有root审阅测试：event boundaries、懒checkout、backlog/incoming budget、长retry、有限NaN/inf、Jenkins shell fake SSH、activation identity、preflight listeners。因迁移移除私有旧方法时可重写测试到新的domain/framework行为，不能仅删掉测试。
4. 离线后端完整套件（独立真实integration入口offline跳过有明确记录）、真实PG/Redis新框架集成、部署替身、前端Node与必要构建、Rust test/clippy。仅当新变更/失败需要时重复测试，别为刷新计数、无关format或清缓存循环重跑。
5. 所有资源只用本工作区临时目录/专用临时PG集群Redis实例/随机schema角色prefix。清理错误进入退出码，保留headless日志，不动原项目资源。末尾立即写真实通过数/命令/实际框架进程证据/未覆盖现场项并交接，禁止commit/push。生产OSS/SMTP/浏览器/400负载/正式部署仍未授权本轮执行。

官方参考：Taskiq https://taskiq-python.github.io/guide/cli.html 与 scheduling-tasks.html、available-components/middlewares.html；https://github.com/taskiq-python/taskiq-redis；AnyIO https://anyio.readthedocs.io/en/stable/streams.html。以已安装版本源码为准。

## 最终选型执行：AnyIO + Redis Streams + Taskiq

用户最终确认采用 WS 连接内 AnyIO 有界流 + WS 跨进程 Redis Streams + 后台 Taskiq 及官方 taskiq-redis 1.2.4，并在原工作区迁移既有实现，不重写方案。执行约束：

- 保留 SQLModel/col 类型修复、业务锁→全事务 recipient 排序 counter 锁、审计不可变、outbox 同事务、非零游标/补拉/幂等/背压/Redis 池/安全修复；不得改成提交前直接 push。
- gateway 用 `anyio.create_memory_object_stream` 替换自制 queue/space_available/queued_bytes；live `send_nowait` 满即 1013，history 有界 `await send` + timeout；close 关闭流唤醒等待者，writer 独占 WebSocket close。容量用 `min(messages, bytes//max_frame)`，另计一个 inflight 帧余量；启动拒绝 bytes<max_frame。
- `app/jobs` 使用官方 `RedisStreamBroker`，任务 namespace 与 realtime 广播 stream 分离；执行后 ACK；`SmartRetryMiddleware` + 官方 `ListRedisScheduleSource`（JSON，非 pickle）负责延迟重试；outbox/超时/retention/幂等清理为真实任务，固定周期用静态 schedule source。broker 不 MAXLEN 裁剪未 ACK pending；Redis 8.2+ ACKED 回收需全部 group 确认。
- `OutboxService` 只保留有限 batch/时间预算的 claim→publish→confirm，不再有常驻 run/sleep/自制退避；`next_retry_at` 不参与 claim，`dead_at` 为终态，`realtime-retry` 人工恢复。任务与 outbox 幂等，不声称 exactly once；任务 ACK 不等于设备已读。
- split 角色 api/ws/worker/scheduler；worker/scheduler 用 native CLI 封装且参数全部从 dotenv 构建；scheduler 单实例。worker/scheduler 无 HTTP，使用 SQL/Redis 心跳 + 真实 task probe 的受控 CLI readiness；worker 缺席必须失败。
- combined 保留 official InMemoryBroker + SchedulerLoop；jobs 保留为旧 3 角色回退入口（official Receiver/SchedulerLoop + 真实 Redis），任何模式不得恢复手写消费/扫描/重试循环。
- systemd 新增 worker/scheduler unit，sudoers 精确 unit 枚举；激活脚本按旧 ACTIVATED services 成套停止 combined/旧 3 角色，启动 scheduler→worker→ws→api，worker 执行真实 probe；ACTIVATED 记录 roles/services/protocol/previous_*。回退不自动回滚 DB/Redis/Nginx。
- Jenkins/GitHub Actions 保留真实 PG/Redis fail-closed 门禁，新增 worker/scheduler 启动、杀 worker 接管、重试/终态、scheduler 重启、Redis 重启/断连后 PG 补扫；缺资源失败不跳过。托管 Redis 重启门禁需要 `redis-server`，外部 Redis 只做真实连接断开并明确记录。
- 验证：离线后端全套、真实 PG/Redis 新框架集成、部署替身、前端 Node/构建、Rust test/clippy；保留 root 审阅测试，不删减断言。所有资源用本工作区临时 PG/Redis/schema/prefix 并清理，禁止 FLUSHDB/FLUSHALL、提交/push/SSH/生产动作。


## 成熟框架迁移独立审阅补充

继续同一 issue36 实现任务，授权与隔离范围不变；刚在审查检查点 SIGINT。不要 commit/push/SSH/生产，原项目勿改。请先处理以下具体审查结论，避免继续猜测 IM-01：

1. IM-01 的错误 message66 实际来自 sender 自己的上一条消息。读 acceptance.py4290-4340：buyer发66只读取seller的socket；seller发67读取buyer的socket，buyer不应积压self66。旧WS仅推对方，新v2为了多设备向双方推。保持v2双方推送；仅 legacy mode 在 _deliver_frame 看到 payload.type==message 且 sender_id==conn.user_id 时推进sent_seq但不enqueue。删除刚新增 created_at<connected_at 时间过滤；它会丢握手前创建、握手后提交的有效事件，不是正确语义。主执行者已把legacy高水位捕获移到ws.accept之前，防101后立即HTTP提交被吞，保留。
2. 主执行者已补 readiness 查询 details.role==worker，防combined中的gateway/scheduler心跳选成worker；你已补first-success强制写心跳，这两个都保留。给legacy selfecho/连续游标与first-success加有意义的回归，重跑实际SQLite/local验收。
3. 严重回归：当前 _fill、_fill_user 重新把 await _deliver_event(wait_for_space=True) 放在 async with DB 内，慢socket占SQL。请按页先读取event_wire等纯数据并关闭SQLsession，再对socketawait；high/low/分页每次短会话，不让SQL生命周期跨任何enqueue/resync/send。_catch_up同样检查。对_fill和_fill_user写明确阻塞sender时SQLscope已退出的测试，不能只测试_catch_up。
4. 主执行者已完成并验证的修复不要还原：ReclaimingRedisStreamBroker保留官方消费/reclaim/retry，只覆盖ACK钩子XACKDEL ACKED；强制Redis>=8.2、startup无副作用命令探测ACL/版本，consumer_id0-0，不存在旧版本XACK回退。真实ACK retention2passed。scheduler/probe producerclose不写假停止心跳、不打开SQL；独立任务invocation唯一outbox leaseowner与timeoutleaseowner；OutboxPublishError映射RetryableJobError。Redis预算新增publish池和每并发任务临时结果记录连接，scheduler control health pool最少1（0在redis-py是无界），ObservedPool拒绝0；CI预算128。xread/unackbatch默认8/8，reclaim300000ms，非test校验任务timeout+预取budget；示例已更新。对应docs需同步，旧60000/worker预算117/旧XACK回退等描述移除。
5. 主执行者已加强test_redis_restart：停止worker后，在Redis仍然停止期间提交事件并收WS，证明PG补偿，之后才恢复Redis和worker；托管真实测试1passed。external模式只按本轮随机prefix的client_name精确KILL自己WSreader并删自己stream，禁止CLIENT KILL TYPE normal；该测试也已通过。保留安全边界。
6. Jenkins不要再增加完全重复跑相同测试的Taskiq专门stage：完整真实PG/Redis门禁已经含该覆盖，合成一个清晰stage即可。README/docs同步。
7. 文档版本按AGENTS每次commit最终内容登记，不要多轮递增：新未追踪文档/README统一0.1.0；tracked文档先沿用HEAD版本，尚未获本轮commit授权不登记中间版本。使用git show HEAD:file仅恢复头部Version/Version-Datetime，不覆盖正文。文档移除暂时迁移措辞/错误旧架构，在最终记录清晰区分托管Redis真重启与external只断连接。修正源站Nginx X-Forwarded-Proto https，不写$scheme。准确测试数以最新一次最终全套为准，别根据新增数猜。不要提前声称资源已停止删除，实际清理后再写。
8. 最后执行一次受变更影响的后端完整离线+真实PGRedis托管全套+部署测试+实际SQLite/local验收。前端52/6及build、Rust17+Clippy已由你/主执行者通过，若无新修改不要再重复。root-offline-check.py可用。直接报告真实验收缺口，不删断言/路由隐藏新接口；新realtime和health路由若coverage gate有缺口需补语义调用。真实生产OSS/SMTP/浏览器/400容量本轮不执行。
9. 避免无关style格式化；检查diff与docs引用即可。完成后清理本轮专用PG55432、Redis56379以及runner新临时实例/schema/角色/namespace/派生autoclaim锁；清理失败须明确报告。不得停其他服务。headless日志保留。不要再开始泛化“最后再看看”循环，必要问题修完、相关门禁通过、文档准确即交接。

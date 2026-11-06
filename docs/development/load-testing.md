<!--
Version: 0.1.0
Version-Datetime: 2026-11-06T19:32:01+08:00
-->

# 真实负载压测与独立播种

本模块对应 [issue #34](https://github.com/iy88/se-course-project-1/issues/34)：100 名同时活跃用户、10,000 条商品下常用操作 P95 ≤3 秒，在线文本消息送达 P95 ≤2 秒。图片上传按文件大小和网络条件单独记录，不应用普通操作 3 秒阈值。

数据准备位于后端 `app.devtools.load_seed`，入口为 `app.manage load-seed`，不依赖 `tests/`。独立 Rust 工具位于仓库根 `loadtest/`，不把压测逻辑或测试路由加入常驻应用，不改变生产服务的接口与参数。开发测试数据是合成内容，数据库、Redis、OSS、HTTP 和 WebSocket 均使用所选环境的真实资源；这里的 mock data 不表示 mock 这些基础设施。

## 服务器与本地执行

服务器先准备 `backend/.env.dev`（数据库、Redis、OSS 与生产隔离），按开发指南安装锁定后端依赖、配置迁移角色。实际监听端口由 `.env.dev` 的 `API_PORT` 决定；下列 `8000` 只是示例。压测不读取 `.env.prod`；load-seed 拒绝 prod 环境与名为 `.env.prod` 的文件。不要把连接生产资源的配置写进 `.env.dev`。

在仓库根目录操作。先停止使用这些测试资源的后端、定时任务、自动化测试及其他写入进程。reset 不会自动停止服务、备份或回滚；开发测试清空会删除管理员与既有业务记录。

```bash
# 1. 默认只预览；先核对数据库/schema、Redis 前缀与两个 OSS 桶/前缀
(cd backend && .venv/bin/python -m app.devtools.reset --env-file .env.dev)

# 2. 确定可以删除后执行：数据库名必须按预览结果填写
(cd backend && .venv/bin/python -m app.devtools.reset \
  --env-file .env.dev --execute --confirm <预览中的数据库名>)
# OSS 前缀为空时，确认清空两个配置桶的当前对象后额外加 --whole-buckets
```

reset 复用现有实现：删除应用 schema 全部表后执行正式迁移；Redis 仅清理配置前缀；OSS 只清理配置前缀的当前对象（空前缀配合 `--whole-buckets`），不删除桶、不清历史版本、不清未完成分片。生产资源不属于本流程。跨资源无整体事务，失败后应核对输出中的阶段，再修复重跑。

reset 后旧 load/demo manifest 已失效；将旧 `var/load/manifest.json` 私有归档或显式指定新 manifest。不要只删除 manifest 然后向未清理环境反复播种，否则会生成额外账号和数据。以下假设使用一个全新的 manifest 路径：

```bash
# 3. 新库迁移已由 reset 执行；不清库时须先独立执行 manage migrate
(cd backend && .venv/bin/python -m app.manage load-seed \
  --env-file .env.dev --users 100 --products 10000 \
  --manifest ../var/load/manifest.json --upload-workers 16)

# 4. 在启动负载前核验全部数据库引用和全部 OSS 图片字节
(cd backend && .venv/bin/python -m app.manage load-seed \
  --env-file .env.dev --users 100 --products 10000 \
  --manifest ../var/load/manifest.json --verify-only)

# 5. 独立终端启动后端；本地日志应保持私有，WS access log 可能含 token
(cd backend && .venv/bin/python -m app.manage serve)
```

从仓库根执行 Rust 工具（服务器需先安装 Rust 编译工具链）：

```bash
cargo build --release --locked --manifest-path loadtest/Cargo.toml
loadtest/target/release/campus-loadtest \
  --base-url http://127.0.0.1:8000 \
  --manifest var/load/manifest.json --output var/load/report.json \
  --users 100 --warmup-seconds 30 --duration-seconds 120 \
  --think-ms 1000 --timeout-seconds 60 --min-samples 20
```

Windows 使用 `backend/.venv/Scripts/python.exe` 和 `loadtest/target/release/campus-loadtest.exe`，命令本身参数相同。manifest 在 seed 所在主机生成，Rust 本机执行无需复制；若独立压测机执行，只私下传输该清单，保持权限受限，禁止发布清单。默认路径相对 `loadtest/`，仓库根运行必须像上例显式指定。

## 数据规模、恢复与核验

默认 100 个普通用户、5 个分类、10,000 个已审核在售商品，每个商品有独立 JPEG 对象、ProductImage、分类关联、通过的审核记录与 committed StoredObject。当前seed v2轮换键盘、教材、台灯、自行车、相机、水杯、笔记、球拍8种已有JPEG样本，每个商品独立key；图片字节和大小随样本变化，但不代表大图/视频分布。标题使用不同关键词与成色，描述长度和交付方式变化；同一卖家的商品跨分类轮换。每个用户平均100个商品，价格和时间确定分散。审核快照复用正式业务的 `product_content_dict` 格式（images/tags）。预置 100 个环形普通私聊、每会话 20 条历史消息。压测期间的发布、交易、消息、审计、通知和上传租约由真实业务接口继续累积。

seed 用批量数据库写入和可配置线程数上传图片；不通过 HTTP 逐条生成 10,000 商品，不把 seed 吞吐量当 API 性能。对象 key 由先持久化的 tag 与序号确定，上传不可覆盖；再次执行同一清单会校验已有账号、商品/图片/登记引用和会话，抽查首/中/末图片字节，不重复插入、不恢复业务状态。`--verify-only` 对所有图片校验 SHA-256。账号统一使用随机测试密码及同一 bcrypt hash 以减少准备耗时；压测仍对每个账号通过正式登录接口验证密码。此方式不覆盖注册与验证码投递。

manifest 以私有原子写入记录目标指纹、规模、tag、账号和 ID。上传前记录 tag/count，数据库提交前记录 ID，可恢复上传响应丢失、事务回滚以及提交成功但最终清单写入失败的情形。遇到已有对象内容不同、目标/规模不匹配、账号密码变更或引用缺失会拒绝接管。中断遗留的对象可由同清单复用；若本地文件写入被打断留下残缺字节，会拒绝覆盖，需核对资源后 reset 并换新清单。不要同时对同一数据集执行 reset、seed 与压测。

## 负载与指标口径

每个虚拟用户持有自己的登录会话与接收 WebSocket。启动时逐个真实登录，并验证返回 ID；全部连接完成鉴权 ping/pong 后统一开始。用户数必须等于清单 cohort 数，避免部分在线导致私聊接收方缺失。登录耗时单独记录在 `login_ms`，不属于稳态并发登录测试。

采用闭环用户：每个用户持续操作，场景结束后默认思考 1000 ms；20 槽循环按用户索引错开，配比为首页 30%、带分类/分页的搜索 25%、商品详情 25%、发布 5%、交易完整推进 5%、IM 10%。这是场景配比，交易有多个 HTTP 请求，实际请求配比由报告各项样本数给出；闭环模型在变慢时实际请求率会下降，不能据此宣称达到固定 RPS 的容量或消除 coordinated omission。调整 `--think-ms` 与用户数探索更高负载时应另存报告。

发布路径：申请租约 → 带签名直接 PUT 到 OSS（或 local）→ 完成 SHA-256/解码验证 → 提交商品并校验待审核状态。OSS 请求不带应用 bearer token。交易路径：购买请求 → 卖方接受 → 买方提出约定 → 卖方同意 → 买方确认 → 卖方确认 → 回读 completed → 卖方重新上架。稳态模式中，每个买方在下一位卖方的库存中轮换商品，保持用户间不争抢；同商品争抢由独立race模式覆盖。失败不会自动重试或清理，真实错误保留在报告，存在未完交易时宜清库重播后比较。

IM 路径在 POST 前登记唯一关联内容，持续监听真实接收方 WS 帧，校验接收用户、会话、发送者和内容，使用压测机同一单调时钟计算送达延迟，10 秒未收到计失败；HTTP 发送与 WS 送达分别记录。此指标是接收端收到帧，不包含浏览器渲染/页面文字显示。服务若在数据库提交前广播，WS 测量不会证明消息持久化时序正确；应另做功能与事务验证。

默认预热 30 秒、采样 120 秒。HTTP 从请求前到完整响应体接收并解析完成；按请求开始时间归入预热或采样窗口，窗口末在途请求会排空，流程中窗口外才发起的后续请求不计入本次窗口。思考时间不计入延迟。`scenario_*` 另记完整场景耗时，交易跨多步之和不套单步 3 秒阈值。所有延迟使用 nearest-rank P50/P95/P99，并输出最大值、样本量、错误数和状态码；错误样本不会被悄悄丢弃。

首页/搜索/详情、发布提交、交易各步骤及 IM 发送的 P95 阈值为 3000 ms；`im_delivery` 为 2000 ms；`upload_*` 与场景总时长单独报告。普通操作需每项至少 `--min-samples`（默认20）；缺项、样本不足、任意正式请求错误、预热请求错误、运行中 WS 断连、虚拟用户任务失败、活跃用户不齐均失败。报告v2将 `steady_state_passed` 与整轮 `passed` 分开：预热有请求、送达或场景语义错误时，即使稳态达标，整轮仍失败；`warmup_request_errors` 给出数量。退出码 `0/1/2` 分别为本次负载通过/指标失败/准备或运行异常。小规模通过不满足 issue 数据规模；报告同时输出规模达标字段与 API/WS 层结论。

原始JSON v2还包含HTTP请求关联ID、相对起始毫秒、脱敏错误类别和允许列表中的底层原因标签（timeout/connect/connection_reset/connection_closed等）；X-Request-ID同步传给后端，可与审计关联。不会保存原始错误文本或私有URL。Rust显式关闭自动重试。默认请求总预算60秒，覆盖常见OSS单次15秒、最多3次尝试及处理开销；调整OSS超时/重试配置时需同步评估总预算，不能只增大超时掩盖错误。

原始 JSON 含参数、数据集标记、登录样本、预热汇总、采样汇总、每项原始延迟样本与实际 HTTP RPS，不含密码/JWT/签名 URL/响应正文。保留报告及对应源码版本、机器配置、服务实例数、网络路径、反向代理设置与运行期间资源监控，才能比较本机和服务器结果。可另存 `--output` 多次运行，不覆盖此前证据。

## 历史v1本地执行证据

2026-11-06 在 `feat/34-load-test` 分支上实现，基于 `dev` 的 `b199840`，尚未提交。运行平台 macOS 27.2 / arm64，18 个逻辑 CPU；Rust 1.95.0 release 构建；驱动与单进程 FastAPI 后端在同机 loopback 通信，真实 PostgreSQL、Redis 位于本机，真实 OSS 为远端测试双桶。本轮先按明确授权无备份清理 `.env.dev` 的应用表、Redis 配置前缀和两个测试 OSS 桶当前对象，并完成正式迁移。

seed 成功写入 100 用户、10,000 在售商品、10,000 独立 JPEG 对象及登记、100 普通私聊/2,000 历史消息；随后 `--verify-only` 对全部预置图片读回并校验 SHA-256，通过。合成图片大小为 39 KiB 左右，同一张键盘样本以独立 key 写入每个商品。15 秒短测覆盖全部场景，2,250 HTTP 请求、150.00 请求/秒，零错误；它还新增了90商品、90交易，所以正式首轮开始时实有 10,090 商品，而清单的预置规模仍是10,000。

正式首轮从北京时间 16:35:27 起统一开始，30秒预热+120秒采样，100 HTTP 用户与100接收 WS，场景后思考1000ms，默认15秒请求超时。采样共17,434 HTTP请求，145.28请求/秒。所有常用接口及 IM 的 P95 低于阈值，但 `upload_complete` 有1次15,001ms客户端超时（581个样本中580次200、1次无状态码），对应发布场景失败1次，因此整体 `passed=false`。同轮服务端有1条 `storage_get_failed`，GET约15,015ms，异常链为ReadTimeout，未获得OSS HTTP状态码；这与远端读取超时一致，尚未定位为具体网络或OSS服务端原因。未提高超时或添加自动重试来隐藏失败。

原始首轮报告保存在本地 `var/load/report-100-users.json`，短测为 `var/load/smoke.json`；它们均被Git忽略，禁止用日志或清单中的凭据发布证据。下表为正式首轮的采样结果，错误列不含预热：

| 操作 | 样本 | P95 (ms) | 错误 |
|---|---:|---:|---:|
| 首页 | 3486 | 39.17 | 0 |
| 搜索 | 2901 | 41.53 | 0 |
| 详情 | 2902 | 28.83 | 0 |
| 发布提交 | 579 | 99.42 | 0 |
| 创建购买请求 | 582 | 45.43 | 0 |
| 卖方接受 | 582 | 57.56 | 0 |
| 提出约定 | 582 | 34.19 | 0 |
| 同意约定 | 582 | 41.36 | 0 |
| 买方确认完成 | 582 | 43.50 | 0 |
| 卖方确认完成 | 582 | 68.78 | 0 |
| 回读已完成交易 | 582 | 24.71 | 0 |
| 重新上架 | 582 | 42.95 | 0 |
| IM HTTP发送 | 1165 | 28.30 | 0 |
| IM 接收方WS送达 | 1165 | 24.46 | 0 |
| 上传完成确认（单独统计） | 581 | 65.26 | 1 |

首轮失败报告保留后，以相同参数复测，另写 `var/load/report-100-users-repeat.json`。复测于北京时间16:39:35起统一开始，正式120秒采样期17,505个HTTP请求、145.88请求/秒，100活跃用户、零WS断连、正式采样期零错误，全部14项普通操作/送达指标均达到样本下限并通过，`passed=true`。但预热阶段有2次无HTTP状态码的传输失败：用户77的 `upload_complete`（约0.11ms）和用户39的 `im_send`（约0.14ms），后者同时使该次送达失败。报告保留这些预热错误，`passed`只评价正式采样窗口和连接健康，不宣告整轮全过程无错误；该两次失败尚未定位。

| 复测操作 | 正式样本 | P95 (ms) | 正式错误 |
|---|---:|---:|---:|
| 首页 | 3509 | 40.73 | 0 |
| 搜索 | 2912 | 46.70 | 0 |
| 详情 | 2906 | 33.26 | 0 |
| 发布提交 | 584 | 108.18 | 0 |
| 创建购买请求 | 585 | 51.34 | 0 |
| 卖方接受 | 585 | 61.01 | 0 |
| 提出约定 | 585 | 39.92 | 0 |
| 同意约定 | 585 | 48.27 | 0 |
| 买方确认完成 | 585 | 49.66 | 0 |
| 卖方确认完成 | 585 | 64.30 | 0 |
| 回读已完成交易 | 585 | 29.42 | 0 |
| 重新上架 | 585 | 44.51 | 0 |
| IM HTTP发送 | 1170 | 32.93 | 0 |
| IM 接收方WS送达 | 1170 | 27.97 | 0 |
| 图片直接PUT（单独统计） | 581 | 38.88 | 0 |
| 上传完成确认（单独统计） | 582 | 69.60 | 0 |

两次正式运行连同各自预热及短测产生累积数据，因此复测的数据量大于首轮；未重播成完全相同快照，两轮是同参数观察，不能作为严格A/B对照。最终只读核对：100用户、11,547商品及图片、11,549对象登记（11,547 committed、2 staged）、1,549交易且全部completed、8,192消息。两个staged对象来自失败发布，未擅自删除。压测结束后停止本轮单独启动的后端，保留数据、私有manifest、日志与三份报告；原demo manifest因清库已失效，需另行重置后重新demo-seed，不能把旧清单当作可用演示数据。

开发检查：不含真实全量功能验收入口的后端回归为53 passed，包含新增seed完整性/恢复/拒绝测试2项；Rust百分位与判定回归1项通过，Clippy `-D warnings`、release构建通过。首次默认全仓pytest触发既有 `RUN_REAL_ACCEPTANCE` 未启用的失败门禁，真实全量功能验收本轮未执行；以上53项不等于全量真实功能验收通过。

上述历史v1执行对应源码 SHA-256：`backend/app/devtools/load_seed.py` 为 `0d05d5fb528de6eeafa9ae249a14b31badf606c0e823b3a8abe33e78a2ef2b19`；`loadtest/src/main.rs` 为 `0800152a078a519329ebd687b6f376272fdaaa3b84b2e5ab91d949a2c881e427`；`loadtest/Cargo.lock` 为 `82b3031d47db84eabe61cd0da847b215047a798bde1b1ee952d3c094e7d9bcb7`。

接口压测与浏览器、人机页面验收分别记录；未执行服务器环境、生产链路、浏览器渲染/显示、真实收件SMTP、广域网或多实例测试。没有完整CPU/内存/数据库资源监控时间序列，这份记录也不用于推断最大容量或解释全部资源瓶颈。不因本机接口P95达标而关闭生产或UI性能验收缺口。


## 竞态模式与后端事务保护

竞态测试属于同一压测模块，使用同一 `.env.dev`、manifest和真实HTTP服务，不另建schema、不mock PostgreSQL或OSS。从仓库根运行：

```bash
loadtest/target/release/campus-loadtest --mode race --race-rounds 5 \
  --manifest var/load/manifest.json --output var/load/races-v2.json
```

每轮使用清单中卖家0的另一个商品，必须有足够预置库存。覆盖：同买方同商品并发重复请求返回同一交易；同商品两笔请求并发接受只允许200/409各一次，失败方closed且无接受转移；双方并发确认只完成一次；新购买请求与接受竞争时，新请求要么被拒绝，要么先创建再被关闭；同上传租约并发确认返回同一key；同卖方并发发布两件不同商品，每件有一份审核；发布途中分类校验失败应回滚已插入商品。确认与取消后通过正常业务重新上架恢复预置商品，不直接改库。发布和历史交易会累积，未通过时保留现场。

预期409/400在各场景按精确允许状态计为成功，其他状态/传输错误仍失败；除响应码外还回读交易状态、转移、审核和本人商品。race输出 `race_checks` 与原始请求样本，结果不冒充100活跃用户稳态性能通过。单个请求使用 `tokio::join!` 同时发起；样本包含起始偏移和耗时，可检查请求时间重叠。

后端已有以下保护：交易先按“商品→交易”取得PostgreSQL行锁、锁后刷新状态；同商品锁单及同买方pending请求有条件唯一索引；接受请求对死锁/序列化失败整事务回滚后有限重试。商品、交易、分支、通知、审核事项、成功审计在同一SQL会话中提交，异常退出会回滚。发布中StoredObject按key排序取得行锁，与staged清理串行；上传完成先锁租约、再锁对象登记，重复确认幂等。OSS文件与数据库没有分布式原子事务，失败上传可保留staged对象。

并发发布两件不同商品是合法行为；当前发布接口没有幂等键，相同请求体的重复发布也不能承诺只生成一件商品。这个边界与同商品抢单保护分开记录，不将现有共享图片能力改为禁止共享。当前竞态集不穷尽封禁/冻结与发布、分类停用与发布等跨领域时序。仓库真实功能验收中另有5轮并发接受、5轮重复请求，以及审核编辑/认领处置、超时确认/冻结等场景；存在这些代码不代表本轮执行了整套真实功能验收。

Rust目录按职责分为config、model、http、scenarios、ws、races、diagnostics、report和runner；main只解析参数和处理退出码。seed v2拒绝使用v1清单继续播种，避免把旧数据静默视为新分布；Rust仍能读取v1清单以保留既有真实压测数据和历史复现。当前 `.env.dev` 旧数据没有被本轮清空或升级为v2分布，新分布已通过隔离seed回归，服务器新seed使用v2。


## 修复后竞态实测

在同一 `.env.dev` PostgreSQL/Redis/OSS 环境及原v1压测清单上运行 `--mode race --race-rounds 5`，没有创建临时schema，没有清空或重新seed现有数据。报告 `var/load/races-v2.json`：165个HTTP请求，7类场景各5轮，共35项检查全部通过；race模式只让3个业务角色参与争用，不代表100用户稳态性能结论。重复请求、并发接受、双方确认、重复上传完成和并发发布的各5对请求均由起始偏移与结束时间确认发生HTTP时间重叠。接受请求每轮200/409各一次，重复请求和确认均为预期200。

独立只读SQL核对通过：10件新发布商品=10份审核=10条事项=10条成功发布审计；5个赢家均completed、共10条有效完成确认、5条completed转移；5个失败方均closed且成功接受审计0；5个上传对象各只有一次成功租约确认审计；10个原始购买请求各只有一次成功创建审计；5次无效分类发布的商品残留0；全库同商品重复锁单0。测试结束时10,000预置商品仍全部listed，新增待审核商品累计1,557条。测试产生的商品/历史交易保留，未删除业务记录。

OSS已修复对 `OperationError → ResponseError → requests.ReadTimeout` 的重试识别；隔离回归覆盖第二次恢复成功、最多3次失败后退出以及日志不泄露原始异常文本。该回归不模拟真实网络超时的发生率，不证明OSS/网络原始抖动已消除。后端离线回归55 passed（两个既有Starlette弃用警告）；Rust百分位/判定、错误分类脱敏测试通过，Clippy严格检查与release构建通过。


修复后的稳态负载继续使用同一v1数据集（包含此前测试累积数据），30秒预热、120秒采样、100用户、100接收WS、1000ms思考、60秒请求预算。`var/load/steady-v2.json`：17,506个正式HTTP请求，145.88请求/秒；预热及采样全部失败样本0、断连0、整轮passed=true；服务端本轮无storage retry/failed日志。首页P95 37.94ms、搜索43.24ms、详情26.82ms、发布99.90ms、IM发送28.13ms、接收23.30ms；全部交易步骤P95约20.28—61.86ms且零错误。上传PUT P95 34.39ms、完成确认65.90ms（单独统计）。原来两次快速传输失败未复现，不据此宣告其具体根因已确定或网络抖动已根除。结束后停止本轮后端，保留数据及私有日志。

本次稳态执行的release二进制SHA-256为 `d6f8684f5433566db6f91d20c83d9725cd9e0e82cbec542a81ff07c09cc43743`；对应Rust源树摘要为 `934a0aef15c1c0e22ea5fd59d7c5cacdcf05afeedadf6be74a8418224b7b13fa`（按src内.rs文件名排序，将文件名、NUL、内容、NUL逐项拼接后SHA-256）。最终源码另增强了仅发生预热送达/语义失败时的整轮拒绝判定并补回归，此次实测没有任何失败样本，结论不受该增强影响；最终构建以实际工作区为准。


## 容量探测：single与mixed

capacity独立于steady/race，不修改它们的负载定义。single表示每个预定到达只调用一个应用HTTP接口，速率单位HTTP RPS；mixed表示每个到达启动一个完整业务场景，单位场景/秒，实际HTTP请求速率独立输出。不能把100场景/秒写成100 HTTP RPS，不能把100个活跃用户视为100个始终在途请求。账号数目前仍须等于清单cohort数，single也会在准备阶段逐个登录，登录不计入容量窗口。

从仓库根运行（需先启动后端）：

```bash
loadtest/target/release/campus-loadtest --mode capacity \
  --capacity-case single --single-operation search \
  --manifest var/load/manifest.json --output var/load/capacity-single-search.json \
  --capacity-start-rate 25 --capacity-max-rate 400 \
  --capacity-stage-seconds 30 --capacity-warmup-seconds 5 \
  --capacity-validation-seconds 300 --monitor-pid <本机后端PID>

loadtest/target/release/campus-loadtest --mode capacity \
  --capacity-case mixed \
  --manifest var/load/manifest.json --output var/load/capacity-mixed.json \
  --capacity-start-rate 25 --capacity-max-rate 400 \
  --capacity-stage-seconds 30 --capacity-warmup-seconds 5 \
  --capacity-validation-seconds 300 --monitor-pid <本机后端PID>
```

single目前支持home/search/detail/publish/im，分别固定列表、搜索、详情、商品发布提交、消息发送接口；不支持把需要预先建立交易状态的任意交易步骤伪装为无前置条件的单接口。单接口publish使用当前用户的预置图片，省去独立上传请求，因此仅应用POST /products是施压接口，后端图片存在性等工作仍算入响应时间。mixed发布包括租约、OSS直传、完成验证和发布，交易包括请求到完成及重新上架，IM用真实接收方WS核对。mixed每20次场景按6/5/5/1/1/2分配首页/搜索/详情/发布/交易/聊天，原始HTTP比例由多步流程自然产生。

调度按固定时间表发起任务，不因请求耗时而降低目标速率；不等待上一场景完成、不执行think-ms。每个到达有最大调度延迟，超过默认100ms跳过而不补发突发请求；默认最多2048个同时在途场景，达到限制时记录未发送任务。调度丢弃/在途限制表示本次无法完整施加目标强度，会给不确定结果，不能据此判定服务端最大吞吐。mixed将前半商品用于详情、后半用于交易，每笔在途交易独占商品，成功恢复后才归还，异常/取消则隔离保留，避免重复pending或抢单干扰容量测试。不要同时运行另一份会修改同一压测数据的工具。

每档包含预热和采样，按预定到达时刻统计目标场景数，另按实际HTTP请求起始时间分窗口；流程在窗口末仍会排空，因此另报窗口内完成量、排空耗时和drain样本，不能把排空后完成量除以窗口时间冒充窗口内吞吐。交易末尾在窗口外才发起的请求记为drain，不计入窗口HTTP RPS。资源采样每秒读取本机ps的CPU报告值/RSS，ps CPU百分比的含义受操作系统影响，不作为瞬时CPU利用率或具体瓶颈的证明；未配置远端观测时，它不代表远程服务器资源。

通过规则：所需操作样本至少min-samples，普通操作P95≤3000ms、IM送达≤2000ms；上传独立统计。默认非预期错误预算0，可用capacity-max-error-rate显式设置[0,1)比例，逐操作和场景均检查；预热错误仍严格拒绝。检查在途曲线后2/3的线性增长，斜率超过max(1场景/秒,目标速率的2%)视为持续积压；这只是可复核的稳定性判据，不代表排队论最大容量证明。超过请求预算加15秒仍未排空会取消剩余任务并标失败，失败商品不回收到池中，现场需人工核对。

控制流程：从capacity-start-rate翻倍，到capacity-max-rate或首次失败；仅业务指标失败可建立观测失败上界，随后最多capacity-refinements次在已知通过/失败区间细测，区间小于capacity-resolution即停止。对最高观察通过强度进行capacity-validation-seconds持续验证（默认300秒）；持续验证失败则只尝试此前通过的更低档。没有通过验证的档位不输出可用容量；达到配置上限仍通过只输出已验证下界，上限未知。瞬时网络/OSS抖动也可能造成失败，因此报告用“观察到的失败档位/区间”，不能直接宣称物理极限或某个资源的根因。

容量汇总含highest_validated_rate、first_observed_failing_rate、boundary_bracketed、conclusion、long_validation及各档指标；每档完整原始样本先落盘到本次独立stages目录，再继续下一档。持续验证短于300秒时long_validation=false，只代表短窗验证。HTTP传输错误、业务语义失败和IM送达失败均保留。

数据库监控可在另一个终端单独启动：

```bash
(cd backend && .venv/bin/python -m app.devtools.load_monitor \
  --env-file .env.dev --output ../var/load/capacity-postgres.jsonl \
  --duration-seconds 1800 --interval-seconds 1)
```

只允许dev/test PostgreSQL，以应用连接角色和配置schema为范围，默认只读事务，每秒记录连接state计数、等待Lock的连接数、未获准的schema关系锁数量。监控自身连接排除在连接统计外；不导出SQL文本或连接串；输出使用独占创建和0600权限，已有文件拒绝覆盖。Ctrl-C可停止。原始JSONL与容量报告按时间关联，统计是采样值，不能据“未采到锁等待”证明运行期间从未等待。


容量探测会在采样开始10秒后、每5秒检查已完成场景的错误预算及single的“预定到达→完成”P95，明确违反时提前停止新增任务并排空。报告分开保存planned_sample_seconds与实际sample_seconds，速率用实际窗口计算，窗口后的HTTP步骤改记drain；计划验证300秒但提前失败不算完成5分钟验证。single还检查包含调度等待的端到端P95，mixed的整个流程端到端延迟单独报告，不把交易多步总和套作单步SLA。持续验证失败时，也可在失败档以下补做细测，再验证新的候选。

为约束发压进程内存，默认每档计划到达最多200,000次/场景（可显式设置capacity-max-arrivals）；每档默认最多保留500,000条原始事件（可显式设置capacity-max-samples），超过会记录omitted_samples并判为不确定，不能继续报容量通过。资源采样覆盖施压及排空，不包含大型JSON报告序列化期间的全部瞬时内存峰值。


单接口publish复用已committed的预置图片，度量固定输入下的POST提交路径；它不代表将全新staged图片转成业务引用的完整发布容量。完整上传、验证和新引用转换由mixed发布场景覆盖。capacity控制器与单档调度/采样分别位于独立模块，main继续只保留参数入口。


高强度mixed可将capacity-max-rate提高到400，单位仍是场景/秒，按本配比约产生580应用HTTP RPS和20 OSS PUT RPS。报告将http_rps（总HTTP）、application_http_rps（应用后端）和storage_http_put_rps分开，不将OSS直传当作后端接口请求。普通操作和IM送达的实时SLA也参与提前停止，交易多步总时长单独记录。失败交易商品的ID会列在quarantined_product_ids中，便于后续核对；工具不擅自修改这些未知状态。


速率口径进一步区分：started_rate是场景发起率，http_rps/application_http_rps是采样窗内HTTP发起率；http_successful_response_rps/application_successful_response_rps按响应实际完成时间统计成功可用结果，包含预热发起但在采样窗内完成的响应。旧的http_completions_in_window及scenario_completions字段跟踪采样窗内发起的cohort，排除预热carry-in，不直接冒充服务端全部完成吞吐；原始事件可复核两种口径。


## 容量探测本地执行结果（2026-11-06）

环境为同机loopback、macOS/arm64、18逻辑CPU、1个Uvicorn worker、GIL启用、真实PostgreSQL/Redis/OSS，沿用v1数据及此前测试积累数据。没有清库，也没有改worker或数据库池大小。以下为观测值，不能直接代替服务器部署环境的容量。

单接口search：25/50/100/200/400 HTTP RPS短档通过；首次400持续档因默认512在途保护产生5,348次未发送任务、实际382.17 RPS，同时P95=3,111.39ms，不达标且无法完整施加400。降低到200持续300秒通过，P95=9.10ms。扩大保护限额并补测后，400持续300秒通过，实际400应用HTTP RPS，错误0、丢弃0，P95=32.90ms、P99=73.74ms、含调度等待P95=33.86ms。保留首次及补测两份报告，不因补测通过删掉前次波动。由于400为配置上限，只能给已验证下界，更高上限未知。报告为 `var/load/capacity-single-search.json` 与 `var/load/capacity-single-search-refined.json`。

mixed首先完成100场景/秒的300秒验证：约150总HTTP RPS，其中应用145、OSS PUT 5，错误/丢弃/WS断连0。随后按用户要求把最高强度提高到400场景/秒，从200开始，保护限额4096。实际记录如下：

| 场景强度 | 实际采样时长 | 结果及原因 |
|---|---:|---|
| 200/s | 30s | 短档通过 |
| 400/s | 10s | 发起约399.97/s，无跳过/保护丢弃；多操作P95约5—8s、IM送达约6.56s，触发SLA提前停止 |
| 300/s | 30s | 短档通过 |
| 350/s | 10s | 多操作P95超过3s，IM超过2s，提前停止 |
| 325/s | 15s | IM送达P95约2.35s，不达标 |
| 300/s | 80.03s（计划300s） | 持续验证失败，多操作P95约3—3.75s，IM约3.08s |
| 250/s | 30s | 短档通过 |
| 250/s | 220.11s（计划300s） | 响应P95均符合阈值，最大普通操作P95约116.60ms；2次connection_reset触发零错误策略 |
| 225/s | 30s | 短档通过 |
| 225/s | 300s | 持续验证通过，错误/丢弃/WS断连0 |

225场景/秒持续档约337.5总HTTP RPS，其中应用326.25、OSS PUT 11.25；首页P95=12.37ms、搜索17.76ms、详情6.89ms、发布63.17ms、IM发送5.44ms、送达3.98ms，交易各步P95约9.10—20.42ms。在途峰值和排空数据见原始报告。mixed原始报告为 `var/load/capacity-mixed.json`、`var/load/capacity-mixed-400.json`；逐档原始事件位于各自stages目录，辅助解释为 `var/load/capacity-mixed-400-analysis.json`。

解释边界：225是当前“P95目标+严格零错误+完整发压+300秒验证”组合策略下的持续通过档位。250的失败属于连接稳定性；该窗口延迟仍低，不能把225—250解释为CPU吞吐上限。300及以上存在明确响应退化。400场景/秒的理论稳态请求量约600总HTTP RPS，但失败窗口中许多后续步骤进入drain，所以窗口内实际请求量低于理论值，这不是主动降低场景到达率。后续可以在明示错误预算、同部署与多轮验证的条件下进一步收敛范围，不能把单次观测当作绝对物理极限。

250场景/秒的2次错误在im_send和trade_request，传输原因标签为connection_reset，耗时约1.04/4.35ms；不是3秒响应超限或数据库超时。只读按请求ID关联成功审计均为0，隔离的1件商品仍listed且无有效交易；没有发现这两次请求的已提交业务副作用。工具保留隔离商品ID，不自动重试POST或改状态。首次旧报告丢失的快速异常细节不能据本次记录倒推为同一根因。

Web瓶颈证据：实际日志只出现1个server process；高强度失败时该进程CPU报告值约102%—103%，而机器有18逻辑CPU，故整机CPU仍可能很空闲。数据库应用角色采样最多5个active连接、未采到锁等待，曾有15个idle-in-transaction连接；当前SQLAlchemy池为默认5+10，连接占用/排队与数据库CPU满载是不同概念。现有证据支持优先检查单Web worker的Python处理/事件循环排队，但未测完整SQL耗时、连接池等待和数据库IO，尚不能证明唯一根因。

当前WS连接注册表位于进程内存，没有跨worker分发；直接增加worker会使HTTP发送与接收WS落到不同进程而漏掉实时推送。因此多核对照应先支持跨进程广播，并核算各worker独立连接池的总连接数，再做1/2/4 worker同负载对照，不直接把workers调大宣告容量提升。

测试结束后停止本轮后端和只读监控，保留数据、日志和报告。只读核对当前10,000商品listed、14,231 pending_review；交易14,225 completed、10 closed、5 terminated，无pending/in_progress/disputed/abnormal，无同商品重复锁单；原有2个staged对象仍保留。Rust受控回归13项通过、Clippy -D warnings与release构建通过；只读监控回归2项通过。真实全量功能验收没有因本次容量测试而重新宣称通过。capacity退出0表示至少一个候选通过持续验证，允许更高档位失败；应读取highest_validated_rate及各stage，不能用退出0宣称400档通过。

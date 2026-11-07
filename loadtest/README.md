<!--
Version: 0.1.2
Version-Datetime: 2026-11-07T21:51:45+08:00
-->

# Rust 真实接口压测

独立 HTTP/WebSocket 性能测试驱动，用于验证 100 名活跃用户、10,000 条商品下的操作延迟和消息送达性能。Python 后端负责批量准备真实数据与资源，Rust 只读取私有 manifest，通过真实登录、业务 HTTP 和接收方 WebSocket 操作。服务器使用同一份代码和自己的 `backend/.env.dev`，不需要 Rust 访问数据库、Redis、OSS AK 或 JWT 签发密钥。

运行前准备开发/测试数据库、Redis 前缀、OSS 范围、压测清单和服务。工具读取清单，通过真实 HTTP/WebSocket 业务流程执行测量，并将结果写入指定报告。需要 Rust 1.95+（本轮已验证版本）；使用 `cargo build --release --locked` 构建，`Cargo.lock` 固定本次依赖。Linux 服务器请在目标平台构建对应平台的二进制。

从本目录执行：

```bash
cargo build --release --locked
./target/release/campus-loadtest \
  --base-url http://127.0.0.1:8000 \
  --manifest ../var/load/manifest.json \
  --users 100 --warmup-seconds 30 --duration-seconds 120 \
  --think-ms 1000 --min-samples 20 \
  --output ../var/load/report.json
```

从其他工作目录执行时，显式传入 manifest/output 路径。`--base-url` 只接受源站 origin，不带 `/api/v1`；工具自动使用 `/api/v1` 与 `/ws`，可经过反向代理访问。日志不输出账号密码、JWT、响应正文或 OSS 签名 URL。manifest 含测试账号密码，应保持私有、不提交、不公开分享；原始报告位于被 Git 忽略的 `var/load/`。

退出码：`0` 表示本次配置下所有指标通过，`1` 表示错误、断连、样本不足或超阈值，`2` 表示配置/登录/握手等准备失败。小规模试跑通过只说明该规模通过；JSON 中的规模达标结果还要求至少 100 用户与 10,000 个预置商品，代表 API/WS 层，不等于浏览器渲染与页面文字显示验收。

运行 `cargo test --locked` 验证百分位算法、缺项/样本不足/错误/延迟超限的失败判定，`cargo clippy --locked --all-targets -- -D warnings` 检查 Rust 代码。压测工具无自动重试、清库、服务启停或生产部署行为。

竞态属于同一工具：`--mode race --race-rounds 5` 使用同一manifest与真实服务，覆盖抢单、重复请求、并发完成、请求与接受竞争、重复上传确认、并发发布及事务回滚。预期业务冲突与非预期错误分别判定；它输出独立报告，不作为稳态P95结论。`main.rs`只保留参数入口，具体职责分散到config/model/http/scenarios/ws/races/diagnostics/report/runner。

默认HTTP总超时60秒，显式禁用自动重试；报告v2保留脱敏错误分类、请求关联ID与起始偏移。预热请求错误会使整轮passed为false，同时单独给出steady_state_passed。seed v2支持8种图片与不同关键词，Rust兼容历史v1清单；v1数据需重新seed才能得到新分布。


## 请求强度与容量探测

`--mode capacity` 使用固定到达速率，与steady的“请求结束后再等待”模型分开。两个case分别执行：

```bash
# 单接口：搜索，目标单位HTTP RPS
./target/release/campus-loadtest --mode capacity --capacity-case single \
  --single-operation search --manifest ../var/load/manifest.json \
  --capacity-start-rate 25 --capacity-max-rate 400 \
  --output ../var/load/capacity-single.json

# 混合业务：目标单位场景启动次数/秒，另报实际HTTP RPS
./target/release/campus-loadtest --mode capacity --capacity-case mixed \
  --manifest ../var/load/manifest.json \
  --capacity-start-rate 25 --capacity-max-rate 400 \
  --output ../var/load/capacity-mixed.json
```

默认从配置上限的一半开始（向上取整，`--capacity-start-rate` 可显式覆盖），每档5秒预热+30秒采样；通过后翻倍升压。首次业务指标失败后采用整数二分：取通过/失败边界之间的整数中点，直到相邻整数（默认 resolution=1）或达到细测预算（默认12次），再对候选强度持续验证300秒。最高强度仍通过时只给已验证下界，不宣称测到了系统上限。在途上限、调度丢弃、数据池耗尽和样本不足均为不确定结果，不当作服务端容量边界。

单接口支持home/search/detail/publish/im。单接口发布复用该用户已播种的图片，只发一次POST /products，后端自身的OSS验证仍在接口耗时内；混合发布包含上传全流程，交易保持完整步骤依赖。mixed沿用30%首页、25%搜索、25%详情、5%发布、5%交易、10%IM；不使用think-ms节流，每项任务由预定时间发起。详情池与交易池分开，未完成/失败交易的商品不复用。

报告包含目标/实际发送/窗口内完成速率、排空时间、延迟/错误、调度延迟、跳过和在途上限次数、积压曲线。每档完整样本另存到输出旁的独立stages目录，汇总报告引用其路径。`--monitor-pid <本机后端PID>`可加入本机后端CPU/RSS采样；发压进程默认采样。数据库只读监控见开发文档。

保护与判定：默认最多2048个在途场景；SLA/错误预算明确失败时停止新增任务，按实际采样时长计算速率，并保留drain样本。单接口同时报告“预定到达→完成”的P95，混合业务完整流程延迟另列。达到配置最高强度并不等于已测得上限；未完成300秒持续验证的候选不会作为长期通过档位。


## 实时协议 v2

驱动启动时为每个虚拟用户请求 `POST /api/v1/realtime/ticket`（Bearer JWT，先读持久高水位并使用 `since=high_seq`），再用一次性 ticket 连接 `/ws`，等待 `hello`/`replay_complete` 后开始；事件 envelope 的 `payload` 保留旧 `message` 字段，驱动在业务匹配后发送 `user_seq/event_id` ACK，并用连续 user_seq 游标去重。目标后端必须支持 ticket 且 `protocol_version >= 2`；旧后端会在准备阶段明确失败，不回退 query token。同机 100 用户压测需显式提高 `WS_HANDSHAKE_RATE_LIMIT`（默认 30/IP/min）与 `WS_MAX_CONNECTIONS_PER_IP`（默认 50），并只在隔离环境设置 `ALLOW_MISSING_ORIGIN=true`。非浏览器驱动需让目标环境显式允许其 Origin，或仅在隔离测试中设置 `ALLOW_MISSING_ORIGIN=true`，生产不得放宽来源。本轮未重新执行 100 用户/400 混合场景，历史单 worker 数据不能作为 split 容量结论。

直连独立角色时可传 `--base-url http://127.0.0.1:8000 --ws-base-url http://127.0.0.1:8002`；登录、水位和 ticket 仍走 API，WebSocket 直连指定 WS origin，Origin 仍为 API origin。经过同一 Nginx origin 时不需要此参数。只接受不含凭据、路径、query 的 HTTP(S) origin。

提高上限时，例如 `--capacity-max-rate 800` 默认从400开始；下一轮1600则从800开始。start/max/resolution 均要求整数（start=0表示自动）；失败上界内继续二分，不越过该失败档继续加压。每个 case 的结论与持续验证分别保存。

上限超过400时也需显式提高采样保护预算。例如800可使用 `--capacity-max-rate 800 --capacity-max-arrivals 1000000 --capacity-max-samples 3000000`；该预算包含每档预热和300秒验证，混合业务一条场景产生多条HTTP/送达/场景样本。达到保护预算仅代表本次发压不完整，不能据此宣称服务上限。
